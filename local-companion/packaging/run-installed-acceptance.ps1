param(
    [Parameter(Mandatory = $true)]
    [string]$CandidateMsi,
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

function Resolve-RequiredFile([string]$Value, [string]$Code) {
    try {
        return (Resolve-Path -LiteralPath $Value -ErrorAction Stop).Path
    } catch {
        throw $Code
    }
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
        if ($null -ne $health -and [int]$health.pid -gt 0 -and [int]$health.pid -ne $PreviousPid) {
            return $health
        }
        Start-Sleep -Milliseconds 300
    }
    return $null
}

if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA_NOT_FOUND" }
$candidate = Resolve-RequiredFile $CandidateMsi "CANDIDATE_MSI_NOT_FOUND"
$craig = Resolve-RequiredFile $CraigZip "CRAIG_ZIP_NOT_FOUND"
if ([IO.Path]::GetExtension($candidate).ToLowerInvariant() -ne ".msi") { throw "CANDIDATE_MSI_REQUIRED" }
if ([IO.Path]::GetExtension($craig).ToLowerInvariant() -ne ".zip") { throw "CRAIG_ZIP_REQUIRED" }
if ($candidate.Contains('"') -or $craig.Contains('"') -or $ReceiptPath.Contains('"')) { throw "UNSUPPORTED_QUOTE_IN_PATH" }

$companionRoot = Join-Path $env:LOCALAPPDATA "TDA\Companion"
$marker = Join-Path $companionRoot "current-version.txt"
if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { throw "INSTALLED_VERSION_MARKER_MISSING" }
$version = (Get-Content -LiteralPath $marker -Raw -Encoding UTF8).Trim()
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "INSTALLED_VERSION_INVALID" }
$executable = Join-Path (Join-Path (Join-Path $companionRoot "versions") $version) "TDACompanion.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw "INSTALLED_EXECUTABLE_MISSING" }

Write-Host "TDA Companion installed acceptance" -ForegroundColor Yellow
Write-Host "Versão instalada: $version"
Write-Host "Source SHA candidato: $($SourceSha.ToLowerInvariant())"
Write-Host "MSI SHA256: $((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant())"
Write-Host ""
Write-Host "Este roteiro NÃO executa ações destrutivas automaticamente. Cada interferência no Agent/porta/rede é feita por você e só vira evidência depois de PASS explícito." -ForegroundColor DarkYellow

$observations = New-Object System.Collections.Generic.List[string]

$initialHealth = Get-AgentHealth
$initialPid = if ($null -ne $initialHealth) { [int]$initialHealth.pid } else { 0 }
if ($initialPid -gt 0) {
    Write-Host "Agent atual identificado pelo /health: PID $initialPid"
}
$recoveryPrompt = @"
Com a UI do Companion aberta, finalize manualmente SOMENTE o processo Agent no Gerenciador de Tarefas.
A interface deve mostrar recovery/reconexão e voltar a Ready sem abrir uma segunda UI, sem loop de erro e sem você reiniciar o aplicativo.
"@
$recoveryObserved = Confirm-Observation "agent_recovery" $recoveryPrompt
if ($recoveryObserved -and $initialPid -gt 0) {
    $replacement = Wait-AgentReplacement $initialPid
    if ($null -eq $replacement) {
        Write-Warning "O /health não confirmou um novo PID do Agent. A observação não será aceita."
        $recoveryObserved = $false
    } else {
        Write-Host "Novo Agent confirmado pelo /health: PID $([int]$replacement.pid)" -ForegroundColor Green
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

$downloadPrompt = @"
Teste um download grande real pelo Companion (Whisper ou Qwen) que ainda precise ser baixado nesta máquina.
Com o download em andamento, interrompa temporariamente a Internet por tempo suficiente para a chamada da UI deixar de aguardar. O Companion deve informar de forma amigável que o download continua em segundo plano, sem mostrar WinError/URLError/BITS_* cru.
Feche/oculte e reabra a interface se desejar; isso não deve cancelar o job do Windows. Reconecte a Internet e acione a instalação novamente. O Companion deve reutilizar/retomar a transferência existente e concluir a verificação por tamanho + SHA-256 antes de instalar, sem reiniciar o download completo por causa da queda de rede.
Digite PASS somente depois de a instalação terminar íntegra e a UI mostrar o runtime como pronto.
"@
if (Confirm-Observation "background_download_resume" $downloadPrompt) { $observations.Add("background_download_resume") }

$closePrompt = @"
Com a preferência 'Ao fechar: Ocultar a interface' e o tray ativo, clique no X. A janela deve desaparecer, o tray deve permanecer e o Agent deve continuar operacional.
"@
if (Confirm-Observation "close_hides_ui" $closePrompt) { $observations.Add("close_hides_ui") }

$trayPrompt = @"
Reabra a interface pelo tray e use 'Sair da interface'. A UI deve encerrar de verdade sem encerrar o Agent.
Depois abra novamente o Companion para continuar o aceite.
"@
if (Confirm-Observation "tray_exit" $trayPrompt) { $observations.Add("tray_exit") }

$craigPrompt = @"
Na tela Processar sessão, selecione exatamente o Craig ZIP fornecido a este roteiro.
Confirme que as faixas/speakers aparecem e que o ZIP não é rejeitado por uma falha posterior de Agent/perfis.
"@
if (Confirm-Observation "craig_selected" $craigPrompt) { $observations.Add("craig_selected") }

$craigHealth = Get-AgentHealth
$craigPid = if ($null -ne $craigHealth) { [int]$craigHealth.pid } else { 0 }
if ($craigPid -gt 0) { Write-Host "Agent antes do teste Craig/recovery: PID $craigPid" }
$craigRecoveryPrompt = @"
Sem remover a sessão Craig da tela, finalize manualmente SOMENTE o Agent.
Após o recovery, a sessão Craig deve continuar selecionada e válida; a UI não pode dizer que o ZIP é inválido/rejeitado só porque o Agent caiu.
"@
$craigRecoveryObserved = Confirm-Observation "craig_survives_agent_loss" $craigRecoveryPrompt
if ($craigRecoveryObserved -and $craigPid -gt 0) {
    $replacement = Wait-AgentReplacement $craigPid
    if ($null -eq $replacement) {
        Write-Warning "O /health não confirmou recovery do Agent após o teste Craig. A observação não será aceita."
        $craigRecoveryObserved = $false
    }
}
if ($craigRecoveryObserved) { $observations.Add("craig_survives_agent_loss") }

$arguments = @(
    "--installed-acceptance",
    "--acceptance-candidate-msi", "`"$candidate`"",
    "--acceptance-source-sha", $SourceSha.ToLowerInvariant(),
    "--acceptance-craig-zip", "`"$craig`"",
    "--acceptance-result-file", "`"$ReceiptPath`"",
    "--port", [string]$Port
)
foreach ($observation in $observations) {
    $arguments += @("--acceptance-observation", $observation)
}

$process = Start-Process -FilePath $executable -ArgumentList $arguments -Wait -PassThru
if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) { throw "ACCEPTANCE_RECEIPT_MISSING" }
$receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
if ([string]$receipt.schema -ne "tda_installed_acceptance_v1") { throw "ACCEPTANCE_RECEIPT_SCHEMA_INVALID" }
if ([int]$process.ExitCode -ne 0 -or $receipt.pass -ne $true) {
    $code = if ($receipt.error_code) { [string]$receipt.error_code } else { "ACCEPTANCE_NOT_PASSED" }
    Write-Error "Aceite instalado não passou: $code"
    exit 1
}

Write-Host ""
Write-Host "ACEITE INSTALADO: PASS" -ForegroundColor Green
Write-Host "Receipt sanitizado: $ReceiptPath"
exit 0
