param(
    [Parameter(Mandatory = $true)]
    [string]$MsiPath,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$msi = (Resolve-Path $MsiPath).Path
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "INVALID_VERSION" }
if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA_NOT_FOUND" }

$installLog = Join-Path $env:TEMP "tda-companion-msi-install.log"
$uninstallLog = Join-Path $env:TEMP "tda-companion-msi-uninstall.log"
$tdaRoot = Join-Path $env:LOCALAPPDATA "TDA"
$installedDir = Join-Path $tdaRoot "Companion\versions\$Version"
$installedExe = Join-Path $installedDir "TDACompanion.exe"
$maintenanceExe = Join-Path $installedDir "TDACompanionMaintenance.exe"
$acceptanceScript = Join-Path $installedDir "run-physical-acceptance.ps1"
$runtimeSetupScript = Join-Path $installedDir "install-rc-runtimes.ps1"
$currentVersion = Join-Path $tdaRoot "Companion\current-version.txt"
$stateRoot = Join-Path $tdaRoot "State"
$tokenPath = Join-Path $stateRoot "pairing-token.txt"
$dataRoot = Join-Path $tdaRoot "Data"
$keepMarker = Join-Path $dataRoot "msi-preserve-marker.txt"
$invalidRcArtifact = Join-Path $env:TEMP "tda-invalid-rc-runtime.zip"
$invalidRcResult = Join-Path $env:TEMP "tda-invalid-rc-runtime-result.json"
$startMenuShortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\TDA\TDA Companion.lnk"
$productKey = "HKCU:\Software\Faysk\TDA Companion"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$port = 8765
$process = $null
$installed = $false
$uninstalled = $false

Remove-Item $invalidRcArtifact, $invalidRcResult, "$invalidRcResult.partial" -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
Set-Content -Path $keepMarker -Value "preserve-me" -Encoding ascii -NoNewline

function Invoke-Msi([string[]]$Arguments, [string]$ExpectedLog) {
    $result = Start-Process -FilePath "msiexec.exe" -ArgumentList $Arguments -Wait -PassThru
    if ($result.ExitCode -notin @(0, 3010)) {
        if (Test-Path $ExpectedLog) { Get-Content $ExpectedLog -Tail 160 | Write-Host }
        throw "MSI_EXIT_CODE:$($result.ExitCode)"
    }
}

function Test-HealthDown {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health" -Method Get -TimeoutSec 1 | Out-Null
        return $false
    } catch {
        return $true
    }
}

function Get-VerifiedInstalledAgent {
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health" -Method Get -TimeoutSec 1
            if (
                $health.product_id -eq "tda-companion" -and
                $health.api_version -eq "1" -and
                $health.service_version -eq $Version -and
                [int]$health.port -eq $port -and
                [int]$health.pid -gt 0
            ) {
                $candidate = Get-Process -Id ([int]$health.pid) -ErrorAction Stop
                $candidate.Refresh()
                if ($candidate.HasExited) { throw "AGENT_EXITED" }
                if ([IO.Path]::GetFullPath($candidate.Path) -ne [IO.Path]::GetFullPath($installedExe)) {
                    throw "MSI_INSTALLED_AGENT_PATH_MISMATCH:$($candidate.Path)"
                }
                return $candidate
            }
        } catch {
            Start-Sleep -Milliseconds 150
        }
    }
    throw "MSI_DID_NOT_LEAVE_VERIFIED_AGENT_RUNNING"
}

try {
    Invoke-Msi @("/i", "`"$msi`"", "/qn", "/norestart", "/L*v", "`"$installLog`"") $installLog
    $installed = $true

    if (-not (Test-Path $installedExe)) { throw "MSI_EXECUTABLE_NOT_INSTALLED" }
    if (-not (Test-Path $maintenanceExe)) { throw "MSI_MAINTENANCE_NOT_INSTALLED" }
    if (-not (Test-Path $acceptanceScript)) { throw "MSI_PHYSICAL_ACCEPTANCE_HARNESS_NOT_INSTALLED" }
    if (-not (Test-Path $runtimeSetupScript)) { throw "MSI_RC_RUNTIME_SETUP_NOT_INSTALLED" }
    if (-not (Test-Path $currentVersion)) { throw "MSI_VERSION_MARKER_NOT_INSTALLED" }
    if ((Get-Content $currentVersion -Raw).Trim() -ne $Version) { throw "MSI_VERSION_MARKER_MISMATCH" }
    if (-not (Test-Path $startMenuShortcut)) { throw "MSI_START_MENU_SHORTCUT_NOT_INSTALLED" }
    if (-not (Test-Path $productKey)) { throw "MSI_PRODUCT_REGISTRY_NOT_INSTALLED" }
    $metadata = Get-ItemProperty -Path $productKey
    if ($metadata.Version -ne $Version) { throw "MSI_REGISTRY_VERSION_MISMATCH" }
    if (-not $metadata.ProductCode) { throw "MSI_PRODUCT_CODE_NOT_REGISTERED" }
    $startup = (Get-ItemProperty -Path $runKey -Name "TDA Companion Agent" -ErrorAction Stop)."TDA Companion Agent"
    if ($startup -notlike "*$Version*TDACompanion.exe*--agent*--startup*") { throw "MSI_STARTUP_REGISTRATION_INVALID" }

    # Installation itself now proves the exact Agent before MSI commit. The smoke
    # must observe that same surviving Agent rather than starting a duplicate.
    $process = Get-VerifiedInstalledAgent

    Set-Content -Path $invalidRcArtifact -Value "not-a-zip" -Encoding ascii -NoNewline
    $invalidRcHash = (Get-FileHash -Algorithm SHA256 $invalidRcArtifact).Hash.ToLowerInvariant()
    $rcArguments = "--install-rc-runtime whisper --rc-artifact `"$invalidRcArtifact`" --rc-artifact-sha256 $invalidRcHash --rc-result-file `"$invalidRcResult`""
    $rcProcess = Start-Process -FilePath $installedExe -ArgumentList $rcArguments -Wait -PassThru
    if ($rcProcess.ExitCode -ne 66) { throw "MSI_RC_RUNTIME_INVALID_ARTIFACT_EXIT_MISMATCH:$($rcProcess.ExitCode)" }
    if (-not (Test-Path $invalidRcResult)) { throw "MSI_RC_RUNTIME_RESULT_NOT_WRITTEN" }
    $rcResult = Get-Content $invalidRcResult -Raw | ConvertFrom-Json
    if (
        $rcResult.schema -ne "tda_rc_runtime_install_v1" -or
        $rcResult.ok -ne $false -or
        $rcResult.error -ne "RC_RUNTIME_ARTIFACT_INVALID"
    ) {
        throw "MSI_RC_RUNTIME_RESULT_INVALID"
    }

    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/health" -Method Get -TimeoutSec 3
    if ($health.api_version -ne "1" -or $health.service_version -ne $Version -or [int]$health.pid -ne $process.Id) {
        throw "MSI_INSTALLED_HEALTH_MISMATCH"
    }

    if (-not (Test-Path $tokenPath)) { throw "MSI_PAIRING_TOKEN_NOT_CREATED" }
    $token = (Get-Content $tokenPath -Raw).Trim()
    if ($token.Length -lt 43) { throw "MSI_PAIRING_TOKEN_INVALID" }
    $origin = "https://dnd.faysk.dev"
    $headers = @{
        Authorization = "Bearer $token"
        Origin = $origin
        "Idempotency-Key" = "msi-worker-smoke"
    }
    $body = @{
        kind = "synthetic.fixture"
        campaign_id = "msi"
        session_id = "worker"
        source_id = "packaged"
        units = 3
    } | ConvertTo-Json -Compress
    $job = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$port/api/v1/jobs" `
        -Method Post `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 5
    if (-not $job.id) { throw "MSI_WORKER_JOB_NOT_CREATED" }

    $jobDeadline = [DateTime]::UtcNow.AddSeconds(15)
    $jobState = $null
    while ([DateTime]::UtcNow -lt $jobDeadline) {
        $jobState = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$port/api/v1/jobs/$($job.id)" `
            -Method Get `
            -Headers @{ Authorization = "Bearer $token"; Origin = $origin } `
            -TimeoutSec 3
        if ($jobState.status -in @("succeeded", "failed", "cancelled", "interrupted")) { break }
        Start-Sleep -Milliseconds 100
    }
    if (-not $jobState -or $jobState.status -ne "succeeded") {
        throw "MSI_PACKAGED_WORKER_FAILED:$($jobState.status)"
    }
    if ($jobState.progress.completed -ne 3 -or $jobState.progress.total -ne 3) {
        throw "MSI_PACKAGED_WORKER_PROGRESS_INVALID"
    }
    $capabilities = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$port/api/v1/capabilities" `
        -Method Get `
        -Headers @{ Authorization = "Bearer $token"; Origin = $origin } `
        -TimeoutSec 3
    if ($capabilities.capabilities -notcontains "worker.subprocess") {
        throw "MSI_WORKER_SUBPROCESS_CAPABILITY_MISSING"
    }

    Invoke-Msi @("/x", "`"$msi`"", "/qn", "/norestart", "/L*v", "`"$uninstallLog`"") $uninstallLog
    $uninstalled = $true

    $process.Refresh()
    $exitDeadline = [DateTime]::UtcNow.AddSeconds(8)
    while (-not $process.HasExited -and [DateTime]::UtcNow -lt $exitDeadline) {
        Start-Sleep -Milliseconds 200
        $process.Refresh()
    }
    if (-not $process.HasExited) { throw "MSI_AGENT_LEFT_RUNNING_AFTER_UNINSTALL" }
    if (-not (Test-HealthDown)) { throw "MSI_PORT_LEFT_OPEN_AFTER_UNINSTALL" }
    if (Test-Path $installedExe) { throw "MSI_EXECUTABLE_LEFT_AFTER_UNINSTALL" }
    if (Test-Path $maintenanceExe) { throw "MSI_MAINTENANCE_LEFT_AFTER_UNINSTALL" }
    if (Test-Path $acceptanceScript) { throw "MSI_PHYSICAL_ACCEPTANCE_HARNESS_LEFT_AFTER_UNINSTALL" }
    if (Test-Path $runtimeSetupScript) { throw "MSI_RC_RUNTIME_SETUP_LEFT_AFTER_UNINSTALL" }
    if (Test-Path $currentVersion) { throw "MSI_VERSION_MARKER_LEFT_AFTER_UNINSTALL" }
    if (Test-Path $startMenuShortcut) { throw "MSI_SHORTCUT_LEFT_AFTER_UNINSTALL" }
    if (Test-Path $productKey) { throw "MSI_PRODUCT_REGISTRY_LEFT_AFTER_UNINSTALL" }
    if (Test-Path $runKey) {
        $startupAfterUninstall = Get-ItemProperty -Path $runKey -Name "TDA Companion Agent" -ErrorAction SilentlyContinue
        if ($null -ne $startupAfterUninstall) { throw "MSI_STARTUP_LEFT_AFTER_UNINSTALL" }
    }
    if (-not (Test-Path $keepMarker)) { throw "MSI_UNINSTALL_REMOVED_USER_DATA" }
    if ((Get-Content $keepMarker -Raw).Trim() -ne "preserve-me") { throw "MSI_USER_DATA_CHANGED" }

    Write-Host "Installed TDA Companion MSI + pre-commit Agent verification + subprocess worker + guarded uninstall smoke: PASS ($Version)"
}
finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit(5000) | Out-Null
    }
    if ($installed -and -not $uninstalled -and (Test-Path $installedExe)) {
        try { Invoke-Msi @("/x", "`"$msi`"", "/qn", "/norestart", "/L*v", "`"$uninstallLog`"") $uninstallLog } catch { }
    }
    Remove-Item $keepMarker, $invalidRcArtifact, $invalidRcResult, "$invalidRcResult.partial" -Force -ErrorAction SilentlyContinue
}

Write-Host "TDA Companion MSI uninstall smoke: PASS"