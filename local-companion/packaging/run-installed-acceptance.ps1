param(
    [Parameter(Mandatory = $true)]
    [string]$CandidateMsi,
    [Parameter(Mandatory = $true)]
    [string]$PayloadManifest,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-fA-F0-9]{40}$')]
    [string]$SourceSha,
    [Parameter(Mandatory = $true)]
    [string]$CraigZip,
    [string]$ReceiptPath = (Join-Path $env:LOCALAPPDATA "TDA\State\acceptance\installed-journey.json"),
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$script:ExpectedVersion = $null

function Resolve-RequiredFile([string]$Value, [string]$Code) {
    try { return (Resolve-Path -LiteralPath $Value -ErrorAction Stop).Path } catch { throw $Code }
}

function Confirm-Observation([string]$Name, [string]$Instructions) {
    Write-Host ""
    Write-Host "[$Name]" -ForegroundColor Cyan
    Write-Host $Instructions
    $answer = Read-Host "Digite PASS somente se você observou exatamente esse comportamento"
    return $answer.Trim().ToUpperInvariant() -eq "PASS"
}

function Get-AgentHealth {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(2)
    try {
        $response = $client.GetAsync("http://127.0.0.1:$Port/api/v1/health").GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200) { return $null }
        $raw = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $value = $raw | ConvertFrom-Json -ErrorAction Stop
        if ([string]$value.product_id -ne "tda-companion") { return $null }
        if ([string]$value.api_version -ne "1") { return $null }
        if ([int]$value.port -ne $Port -or [int]$value.pid -le 0) { return $null }
        if ($null -ne $script:ExpectedVersion -and [string]$value.service_version -ne $script:ExpectedVersion) { return $null }
        return $value
    } catch {
        return $null
    } finally {
        $client.Dispose()
    }
}

function Wait-AgentReplacement([int]$PreviousPid, [int]$TimeoutSeconds = 30) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $health = Get-AgentHealth
        if ($null -ne $health -and [int]$health.pid -ne $PreviousPid) { return $health }
        Start-Sleep -Milliseconds 300
    }
    return $null
}

function Get-Sha256Text([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        return -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
    } finally {
        $sha.Dispose()
    }
}

function Get-TdaBitsJobs {
    try {
        Import-Module BitsTransfer -ErrorAction Stop
        $jobs = @(Get-BitsTransfer -ErrorAction SilentlyContinue)
    } catch {
        throw "BITS_EVIDENCE_UNAVAILABLE"
    }
    return @($jobs | Where-Object {
        ([string]$_.DisplayName).StartsWith("TDA Companion ", [StringComparison]::Ordinal) -and @($_.FileList).Count -eq 1
    })
}

function Get-TdaBitsSnapshot([object]$Job) {
    $files = @($Job.FileList)
    if ($files.Count -ne 1) { throw "BITS_EVIDENCE_FILELIST_INVALID" }
    $remote = [string]$files[0].RemoteName
    $local = [IO.Path]::GetFullPath([string]$files[0].LocalName)
    try { $uri = [Uri]$remote } catch { throw "BITS_EVIDENCE_REMOTE_INVALID" }
    if ($uri.Scheme -ne "https" -or $uri.Host -ne "github.com" -or -not $uri.AbsolutePath.StartsWith("/Faysk/tda/releases/download/", [StringComparison]::Ordinal)) {
        throw "BITS_EVIDENCE_REMOTE_INVALID"
    }
    $cacheRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "TDA\Cache"))
    $cachePrefix = $cacheRoot.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $local.StartsWith($cachePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "BITS_EVIDENCE_DESTINATION_INVALID" }
    $jobId = [string]$Job.JobId
    if ($jobId -notmatch '^[0-9a-fA-F-]{36}$') { throw "BITS_EVIDENCE_JOB_ID_INVALID" }
    $transferred = [int64]$Job.BytesTransferred
    $total = [int64]$Job.BytesTotal
    if ($transferred -lt 0 -or $total -le 0 -or $transferred -gt $total) { throw "BITS_EVIDENCE_BYTES_INVALID" }
    return [pscustomobject]@{
        JobId = $jobId
        State = [string]$Job.JobState
        BytesTransferred = $transferred
        BytesTotal = $total
    }
}

function Capture-BitsResumeEvidence([string]$Destination) {
    Write-Host ""
    Write-Host "[background_download_resume — prova medida]" -ForegroundColor Cyan
    Write-Host "Inicie pelo Companion um download GRANDE que ainda não exista localmente (prefira Qwen)."
    Write-Host "Durante a transferência, desligue temporariamente a Internet até a UI informar que o download continua em segundo plano."
    [void](Read-Host "Quando esse estado aparecer, pressione ENTER; não religue a Internet ainda")

    $before = $null
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
    while ([DateTimeOffset]::UtcNow -lt $deadline -and $null -eq $before) {
        $jobs = @(Get-TdaBitsJobs)
        if ($jobs.Count -gt 1) { throw "BITS_EVIDENCE_JOB_AMBIGUOUS" }
        if ($jobs.Count -eq 1) {
            try {
                $candidate = Get-TdaBitsSnapshot $jobs[0]
                if ($candidate.BytesTransferred -lt $candidate.BytesTotal) { $before = $candidate }
            } catch {
                if ($_.Exception.Message -notmatch '^BITS_EVIDENCE_') { throw }
                throw
            }
        }
        if ($null -eq $before) { Start-Sleep -Milliseconds 250 }
    }
    if ($null -eq $before) { throw "BITS_EVIDENCE_PENDING_JOB_NOT_FOUND" }

    Write-Host "Job BITS pendente capturado. Bytes: $($before.BytesTransferred)/$($before.BytesTotal)" -ForegroundColor DarkYellow
    Write-Host "Religue a Internet e acione novamente a instalação/download no Companion."
    [void](Read-Host "Logo após acionar novamente, pressione ENTER para observar a retomada do mesmo job")

    $after = $null
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    while ([DateTimeOffset]::UtcNow -lt $deadline -and $null -eq $after) {
        try {
            $job = Get-BitsTransfer -JobId ([Guid]$before.JobId) -ErrorAction Stop
            $candidate = Get-TdaBitsSnapshot $job
            if ($candidate.JobId -ne $before.JobId) { throw "BITS_EVIDENCE_JOB_CHANGED" }
            if ($candidate.BytesTotal -ne $before.BytesTotal) { throw "BITS_EVIDENCE_TOTAL_CHANGED" }
            if ($candidate.BytesTransferred -gt $before.BytesTransferred -and $candidate.State -in @("Connecting", "Transferring", "Transferred")) {
                $after = $candidate
            }
        } catch {
            if ($_.Exception.Message -match '^BITS_EVIDENCE_') { throw }
        }
        if ($null -eq $after) { Start-Sleep -Milliseconds 200 }
    }
    if ($null -eq $after) { throw "BITS_EVIDENCE_SAME_JOB_PROGRESS_NOT_OBSERVED" }

    $evidence = [ordered]@{
        schema = "tda_bits_resume_evidence_v1"
        pass = $true
        job_id_sha256 = Get-Sha256Text $before.JobId.ToLowerInvariant()
        bytes_before = [int64]$before.BytesTransferred
        bytes_after = [int64]$after.BytesTransferred
        bytes_total = [int64]$before.BytesTotal
        state_before = [string]$before.State
        state_after = [string]$after.State
        same_job = $true
        reused_job = $true
        contains_paths = $false
        contains_url = $false
    }
    $parent = Split-Path -Parent $Destination
    if (-not $parent) { throw "BITS_EVIDENCE_DESTINATION_INVALID" }
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Destination.partial"
    $evidence | ConvertTo-Json -Compress | Set-Content -LiteralPath $temporary -Encoding UTF8 -NoNewline
    Move-Item -LiteralPath $temporary -Destination $Destination -Force
    return $evidence
}

if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA_NOT_FOUND" }
$candidate = Resolve-RequiredFile $CandidateMsi "CANDIDATE_MSI_NOT_FOUND"
$payload = Resolve-RequiredFile $PayloadManifest "PAYLOAD_MANIFEST_NOT_FOUND"
$craig = Resolve-RequiredFile $CraigZip "CRAIG_ZIP_NOT_FOUND"
if ([IO.Path]::GetExtension($candidate).ToLowerInvariant() -ne ".msi") { throw "CANDIDATE_MSI_REQUIRED" }
if ([IO.Path]::GetExtension($payload).ToLowerInvariant() -ne ".json") { throw "PAYLOAD_MANIFEST_REQUIRED" }
if ([IO.Path]::GetExtension($craig).ToLowerInvariant() -ne ".zip") { throw "CRAIG_ZIP_REQUIRED" }
if ($candidate.Contains('"') -or $payload.Contains('"') -or $craig.Contains('"') -or $ReceiptPath.Contains('"')) { throw "UNSUPPORTED_QUOTE_IN_PATH" }

$receiptDirectory = Split-Path -Parent ([IO.Path]::GetFullPath($ReceiptPath))
$bitsEvidencePath = Join-Path $receiptDirectory "bits-resume-evidence.json"
Remove-Item -LiteralPath $bitsEvidencePath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$bitsEvidencePath.partial" -Force -ErrorAction SilentlyContinue

$companionRoot = Join-Path $env:LOCALAPPDATA "TDA\Companion"
$marker = Join-Path $companionRoot "current-version.txt"
if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { throw "INSTALLED_VERSION_MARKER_MISSING" }
$version = (Get-Content -LiteralPath $marker -Raw -Encoding UTF8).Trim()
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "INSTALLED_VERSION_INVALID" }
$script:ExpectedVersion = $version
$executable = Join-Path (Join-Path (Join-Path $companionRoot "versions") $version) "TDACompanion.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw "INSTALLED_EXECUTABLE_MISSING" }

Write-Host "TDA Companion installed acceptance" -ForegroundColor Yellow
Write-Host "Versão instalada: $version"
Write-Host "Source SHA candidato: $($SourceSha.ToLowerInvariant())"
Write-Host "MSI SHA256: $((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant())"
Write-Host "Payload manifest SHA256: $((Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant())"
Write-Host ""
Write-Host "As observações humanas são atestações; recovery, identidade do Agent e retomada BITS exigem prova medida." -ForegroundColor DarkYellow

$observations = New-Object System.Collections.Generic.List[string]

$initialHealth = Get-AgentHealth
if ($null -eq $initialHealth) { throw "AGENT_INITIAL_IDENTITY_REQUIRED" }
$initialPid = [int]$initialHealth.pid
Write-Host "Agent inicial exato: PID $initialPid, versão $([string]$initialHealth.service_version)"
$recoveryPrompt = @"
Com a UI do Companion aberta, finalize manualmente SOMENTE o processo Agent no Gerenciador de Tarefas.
A interface deve mostrar recovery/reconexão e voltar a Ready sem abrir uma segunda UI, sem loop de erro e sem você reiniciar o aplicativo.
"@
$recoveryObserved = Confirm-Observation "agent_recovery" $recoveryPrompt
if ($recoveryObserved) {
    $replacement = Wait-AgentReplacement $initialPid
    if ($null -eq $replacement) {
        Write-Warning "O /health não confirmou um novo Agent exato/PID. A observação não será aceita."
        $recoveryObserved = $false
    } else {
        Write-Host "Novo Agent exato confirmado: PID $([int]$replacement.pid)" -ForegroundColor Green
    }
}
if ($recoveryObserved) { $observations.Add("agent_recovery") }

$portPrompt = @"
Teste manualmente o conflito da porta 8765: com o Agent parado, ocupe 127.0.0.1:8765 com um listener que NÃO seja TDA, mantenha a UI aberta e tente/aguarde o recovery.
A UI deve indicar conflito de porta/processo incompatível e NÃO deve tratar esse listener como Agent. Depois libere a porta e confirme que o Agent consegue voltar.
"@
if (Confirm-Observation "port_conflict" $portPrompt) { $observations.Add("port_conflict") }

$diagnosticPrompt = @"
Abra Diagnóstico na UI instalada. Confirme que o resumo por capability aparece, que erros de rede são tipados/amigáveis e que WebView2 não aparece como ausente enquanto essa mesma UI WebView2 está aberta.
"@
if (Confirm-Observation "diagnostics_ui" $diagnosticPrompt) { $observations.Add("diagnostics_ui") }

$bitsEvidence = Capture-BitsResumeEvidence $bitsEvidencePath
if ($bitsEvidence.pass -eq $true) {
    $observations.Add("background_download_resume")
    Write-Host "Retomada BITS medida: mesmo job, $($bitsEvidence.bytes_before) -> $($bitsEvidence.bytes_after) bytes." -ForegroundColor Green
}

$closePrompt = @"
Com a preferência 'Ao fechar: Ocultar a interface' e o tray ativo, clique no X. A janela deve desaparecer, o tray deve permanecer e o Agent deve continuar operacional.
"@
if (Confirm-Observation "close_hides_ui" $closePrompt) { $observations.Add("close_hides_ui") }

$trayPrompt = @"
Reabra a interface pelo tray e use 'Sair da interface'. A UI deve encerrar de verdade sem encerrar o Agent. Depois abra novamente o Companion para continuar o aceite.
"@
if (Confirm-Observation "tray_exit" $trayPrompt) { $observations.Add("tray_exit") }

$craigPrompt = @"
Na tela Processar sessão, selecione exatamente o Craig ZIP fornecido. Confirme que as faixas/speakers aparecem e que o ZIP não é rejeitado por uma falha posterior de Agent/perfis.
"@
if (Confirm-Observation "craig_selected" $craigPrompt) { $observations.Add("craig_selected") }

$craigHealth = Get-AgentHealth
if ($null -eq $craigHealth) { throw "CRAIG_AGENT_INITIAL_IDENTITY_REQUIRED" }
$craigPid = [int]$craigHealth.pid
Write-Host "Agent exato antes do teste Craig/recovery: PID $craigPid"
$craigRecoveryPrompt = @"
Sem remover a sessão Craig da tela, finalize manualmente SOMENTE o Agent. Após o recovery, a sessão Craig deve continuar selecionada e válida; a UI não pode dizer que o ZIP é inválido/rejeitado só porque o Agent caiu.
"@
$craigRecoveryObserved = Confirm-Observation "craig_survives_agent_loss" $craigRecoveryPrompt
if ($craigRecoveryObserved) {
    $replacement = Wait-AgentReplacement $craigPid
    if ($null -eq $replacement) {
        Write-Warning "O /health não confirmou recovery exato do Agent após o teste Craig."
        $craigRecoveryObserved = $false
    }
}
if ($craigRecoveryObserved) { $observations.Add("craig_survives_agent_loss") }

$arguments = @(
    "--installed-acceptance",
    "--acceptance-candidate-msi", "`"$candidate`"",
    "--acceptance-payload-manifest", "`"$payload`"",
    "--acceptance-source-sha", $SourceSha.ToLowerInvariant(),
    "--acceptance-craig-zip", "`"$craig`"",
    "--acceptance-bits-evidence", "`"$bitsEvidencePath`"",
    "--acceptance-result-file", "`"$ReceiptPath`"",
    "--port", [string]$Port
)
foreach ($observation in $observations) { $arguments += @("--acceptance-observation", $observation) }

$process = Start-Process -FilePath $executable -ArgumentList $arguments -Wait -PassThru
if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) { throw "ACCEPTANCE_RECEIPT_MISSING" }
$receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
if ([string]$receipt.schema -ne "tda_installed_acceptance_v2") { throw "ACCEPTANCE_RECEIPT_SCHEMA_INVALID" }
if ([int]$process.ExitCode -ne 0 -or $receipt.pass -ne $true) {
    $code = if ($receipt.error_code) { [string]$receipt.error_code } else { "ACCEPTANCE_NOT_PASSED" }
    Write-Error "Aceite instalado não passou: $code"
    exit 1
}

Write-Host ""
Write-Host "ACEITE INSTALADO: PASS" -ForegroundColor Green
Write-Host "Receipt sanitizado: $ReceiptPath"
Write-Host "BITS evidence sanitizada: $bitsEvidencePath"
exit 0
