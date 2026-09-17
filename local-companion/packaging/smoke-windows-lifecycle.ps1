param(
    [Parameter(Mandatory = $true)]
    [string]$CurrentMsiPath,
    [Parameter(Mandatory = $true)]
    [string]$RollbackProbeMsiPath,
    [Parameter(Mandatory = $true)]
    [string]$CurrentVersion
)

$ErrorActionPreference = "Stop"
# Use the exact generation implicated in the real deleted-EXE zombie incident.
$previousVersion = "0.3.4"
$previousUrl = "https://github.com/Faysk/tda/releases/download/companion-rc-v0.3.4-43307c819877/TDACompanion-x64.msi"
$previousSha256 = "e96e2f3245184937a22965b71fb216323ad36add3767277f28429b25527e77b6"
$msi = (Resolve-Path $CurrentMsiPath).Path
$rollbackProbeMsi = (Resolve-Path $RollbackProbeMsiPath).Path
if ($CurrentVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "INVALID_CURRENT_VERSION" }
if ([version]$CurrentVersion -le [version]$previousVersion) { throw "CURRENT_VERSION_NOT_NEWER" }
if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA_NOT_FOUND" }

$tdaRoot = Join-Path $env:LOCALAPPDATA "TDA"
$previousMsi = Join-Path $env:TEMP "TDACompanion-$previousVersion-baseline.msi"
$logsRoot = Join-Path $env:TEMP "tda-lifecycle"
New-Item -ItemType Directory -Force -Path $logsRoot | Out-Null
$productKey = "HKCU:\Software\Faysk\TDA Companion"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\TDA\TDA Companion.lnk"

function Invoke-Msi([string[]]$Arguments, [string]$LogName) {
    $log = Join-Path $logsRoot $LogName
    $result = Start-Process -FilePath "msiexec.exe" -ArgumentList @($Arguments + @("/norestart", "/L*v", "`"$log`"")) -Wait -PassThru
    if ($result.ExitCode -notin @(0, 3010)) {
        if (Test-Path $log) { Get-Content $log -Tail 160 | Write-Host }
        throw "MSI_EXIT_CODE:$($result.ExitCode):$LogName"
    }
}

function Invoke-RollbackProbe([string]$ProbeMsi, [string]$LogName) {
    $log = Join-Path $logsRoot $LogName
    $result = Start-Process -FilePath "msiexec.exe" -ArgumentList @(
        "/i", "`"$ProbeMsi`"", "/qn", "/norestart", "/L*v", "`"$log`""
    ) -Wait -PassThru
    if ($result.ExitCode -in @(0, 3010)) {
        throw "ROLLBACK_PROBE_UNEXPECTED_SUCCESS:$($result.ExitCode)"
    }
    if (-not (Test-Path $log)) { throw "ROLLBACK_PROBE_LOG_MISSING" }
    $probeMarker = Select-String -Path $log -SimpleMatch "TDA Companion rollback probe: forced upgrade failure." -Quiet
    if (-not $probeMarker) {
        Write-Host "--- rollback probe action trace ---"
        Select-String -Path $log -Pattern "PrepareMajorUpgrade|PrepareUninstall|RollbackProbeFailure|Return value 3|CustomAction" |
            Select-Object -Last 80 |
            ForEach-Object { Write-Host $_.Line }
        Write-Host "--- rollback probe tail ---"
        Get-Content $log -Tail 200 | Write-Host
        throw "ROLLBACK_PROBE_DID_NOT_REACH_FORCED_FAILURE:$($result.ExitCode)"
    }
    Write-Host "Rollback probe failed intentionally with MSI exit $($result.ExitCode)."
}

function Assert-FileValue([string]$Path, [string]$Expected, [string]$Code) {
    if (-not (Test-Path $Path)) { throw "$Code`:MISSING" }
    if ((Get-Content $Path -Raw).Trim() -ne $Expected) { throw "$Code`:CHANGED" }
}

function Get-RegistryValueSnapshot([string]$Path, [string]$Name) {
    if (-not (Test-Path $Path)) {
        return [pscustomobject]@{ Exists = $false; Value = $null }
    }
    $key = Get-Item -Path $Path -ErrorAction Stop
    $names = @($key.GetValueNames())
    if ($names -notcontains $Name) {
        return [pscustomobject]@{ Exists = $false; Value = $null }
    }
    return [pscustomobject]@{
        Exists = $true
        Value = $key.GetValue(
            $Name,
            $null,
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
    }
}

function Assert-RegistryValueSnapshot(
    [string]$Path,
    [string]$Name,
    $Expected,
    [string]$Code
) {
    $actual = Get-RegistryValueSnapshot $Path $Name
    if ([bool]$actual.Exists -ne [bool]$Expected.Exists) {
        throw "$Code`:EXISTENCE_CHANGED"
    }
    if ($actual.Exists -and ([string]$actual.Value -cne [string]$Expected.Value)) {
        throw "$Code`:VALUE_CHANGED"
    }
}

function Seed-PersistentRoots([string]$Value) {
    foreach ($name in @("State", "Data", "Logs", "Cache", "Models", "Runtime")) {
        $folder = Join-Path $tdaRoot $name
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        Set-Content -Path (Join-Path $folder "lifecycle-preserve.txt") -Value $Value -Encoding ascii -NoNewline
    }
}

function Assert-PersistentRoots([string]$Value) {
    foreach ($name in @("State", "Data", "Logs", "Cache", "Models", "Runtime")) {
        Assert-FileValue (Join-Path $tdaRoot "$name\lifecycle-preserve.txt") $Value "PERSIST_$name"
    }
}

function Current-MaintenanceExe {
    return Join-Path $tdaRoot "Companion\versions\$CurrentVersion\TDACompanionMaintenance.exe"
}

function Start-PreviousAgent([string]$Executable) {
    # Match the field failure: old installed Agent launched as the Startup service.
    $process = Start-Process -FilePath $Executable -ArgumentList @("--agent", "--startup") -PassThru -WindowStyle Hidden
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    while ([DateTime]::UtcNow -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) {
            throw "PREVIOUS_AGENT_EXITED_EARLY:$($process.ExitCode)"
        }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/v1/health" -UseBasicParsing -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                return $process
            }
        } catch {}
        Start-Sleep -Milliseconds 150
    }
    try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
    throw "PREVIOUS_AGENT_START_TIMEOUT"
}

function Assert-ProcessExited($Process, [string]$Code) {
    $deadline = [DateTime]::UtcNow.AddSeconds(6)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { return }
        Start-Sleep -Milliseconds 100
    }
    try { Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue } catch {}
    throw $Code
}

try {
    # Releases are mutable on GitHub in theory, so never trust the URL alone.
    Invoke-WebRequest -Uri $previousUrl -OutFile $previousMsi -UseBasicParsing
    $downloadedSha = (Get-FileHash -Algorithm SHA256 $previousMsi).Hash.ToLowerInvariant()
    if ($downloadedSha -ne $previousSha256) { throw "PREVIOUS_RELEASE_HASH_MISMATCH" }

    Remove-Item $tdaRoot -Recurse -Force -ErrorAction SilentlyContinue

    Invoke-Msi @("/i", "`"$previousMsi`"", "/qn") "01-install-$previousVersion.log"
    $previousMarker = Join-Path $tdaRoot "Companion\current-version.txt"
    $previousExe = Join-Path $tdaRoot "Companion\versions\$previousVersion\TDACompanion.exe"
    $previousVersionRoot = Split-Path $previousExe -Parent
    $candidateExe = Join-Path $tdaRoot "Companion\versions\$CurrentVersion\TDACompanion.exe"
    $currentVersionRoot = Split-Path $candidateExe -Parent
    Assert-FileValue $previousMarker $previousVersion "PREVIOUS_VERSION_MARKER"
    if (-not (Test-Path $previousExe)) { throw "PREVIOUS_EXECUTABLE_MISSING" }
    if (-not (Test-Path $productKey)) { throw "PREVIOUS_PRODUCT_REGISTRY_MISSING" }
    if (-not (Test-Path $shortcut)) { throw "PREVIOUS_SHORTCUT_MISSING" }

    # Capture exactly what the historical MSI produced and require rollback to
    # restore the same presence/absence and values instead of assuming current
    # registry/startup metadata existed in the previous release.
    $baselineRegistry = @{}
    foreach ($name in @("Installed", "Version", "ProductCode", "InstallDir")) {
        $baselineRegistry[$name] = Get-RegistryValueSnapshot $productKey $name
    }
    if (-not $baselineRegistry["Installed"].Exists -or [int]$baselineRegistry["Installed"].Value -ne 1) {
        throw "PREVIOUS_INSTALLED_REGISTRY_INVALID"
    }
    $baselineStartup = Get-RegistryValueSnapshot $runKey "TDA Companion Agent"

    Seed-PersistentRoots "keep-across-upgrade"
    $oldToken = Join-Path $tdaRoot "State\pairing-token.txt"
    if (-not (Test-Path $oldToken)) {
        Set-Content -Path $oldToken -Value ("p" * 43) -Encoding ascii -NoNewline
    }
    $tokenBefore = (Get-Content $oldToken -Raw).Trim()

    # The rollback path must first prove that the new MSI can stop an Agent that
    # belongs to the old installed version before touching transactional MSI state.
    $rollbackAgent = Start-PreviousAgent $previousExe

    # C-07: fail after RemoveExistingProducts. With Schedule=afterInstallInitialize,
    # this happens inside the MSI transaction and must restore the previous product.
    Invoke-RollbackProbe $rollbackProbeMsi "02-rollback-probe-$CurrentVersion.log"
    Assert-ProcessExited $rollbackAgent "ROLLBACK_OLD_AGENT_SURVIVED_PREPARE_MAJOR_UPGRADE"

    Assert-FileValue $previousMarker $previousVersion "ROLLBACK_VERSION_MARKER"
    if (-not (Test-Path $previousExe)) { throw "ROLLBACK_PREVIOUS_EXECUTABLE_NOT_RESTORED" }
    if (Test-Path $candidateExe) { throw "ROLLBACK_CANDIDATE_EXECUTABLE_LEFT_BEHIND" }
    Assert-PersistentRoots "keep-across-upgrade"
    Assert-FileValue $oldToken $tokenBefore "PAIRING_TOKEN_ROLLBACK"
    if (-not (Test-Path $productKey)) { throw "ROLLBACK_PRODUCT_REGISTRY_MISSING" }
    foreach ($name in @("Installed", "Version", "ProductCode", "InstallDir")) {
        Assert-RegistryValueSnapshot $productKey $name $baselineRegistry[$name] "ROLLBACK_REGISTRY_$name"
    }
    Assert-RegistryValueSnapshot $runKey "TDA Companion Agent" $baselineStartup "ROLLBACK_STARTUP"
    if (-not (Test-Path $shortcut)) { throw "ROLLBACK_SHORTCUT_NOT_RESTORED" }

    # Repeat with a live old Agent for the successful MajorUpgrade path.
    $upgradeAgent = Start-PreviousAgent $previousExe
    Invoke-Msi @("/i", "`"$msi`"", "/qn") "03-upgrade-to-$CurrentVersion.log"
    Assert-ProcessExited $upgradeAgent "UPGRADE_OLD_AGENT_SURVIVED_PREPARE_MAJOR_UPGRADE"

    $currentMarker = Join-Path $tdaRoot "Companion\current-version.txt"
    Assert-FileValue $currentMarker $CurrentVersion "CURRENT_VERSION_MARKER"
    if (-not (Test-Path $candidateExe)) {
        throw "CURRENT_EXECUTABLE_MISSING_AFTER_UPGRADE"
    }
    Assert-PersistentRoots "keep-across-upgrade"
    Assert-FileValue $oldToken $tokenBefore "PAIRING_TOKEN_UPGRADE"
    if (Test-Path $previousExe) {
        throw "PREVIOUS_EXECUTABLE_LEFT_AFTER_MAJOR_UPGRADE"
    }
    if (Test-Path $previousVersionRoot) {
        throw "PREVIOUS_VERSION_DIRECTORY_LEFT_AFTER_MAJOR_UPGRADE"
    }
    $currentVersionRegistry = Get-RegistryValueSnapshot $productKey "Version"
    $currentProductCode = Get-RegistryValueSnapshot $productKey "ProductCode"
    if (-not $currentVersionRegistry.Exists -or [string]$currentVersionRegistry.Value -ne $CurrentVersion) {
        throw "CURRENT_REGISTRY_VERSION_INVALID"
    }
    if (-not $currentProductCode.Exists -or -not [string]$currentProductCode.Value) {
        throw "CURRENT_REGISTRY_PRODUCT_CODE_INVALID"
    }
    if (-not (Test-Path $shortcut)) { throw "CURRENT_SHORTCUT_MISSING" }

    # Preserve uninstall keeps persistent roots but removes every application-owned
    # executable/marker/registry/shortcut/startup artifact.
    $maintenanceExe = Current-MaintenanceExe
    if (-not (Test-Path $maintenanceExe)) { throw "MAINTENANCE_EXE_MISSING_AFTER_UPGRADE" }
    $uninstall = Start-Process -FilePath $maintenanceExe -ArgumentList @("--uninstall", "--parent-pid", "0") -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) { throw "MAINTENANCE_PRESERVE_UNINSTALL_FAILED:$($uninstall.ExitCode)" }
    Assert-PersistentRoots "keep-across-upgrade"
    if (Test-Path $candidateExe) { throw "PRESERVE_UNINSTALL_EXECUTABLE_LEFT_BEHIND" }
    if (Test-Path $currentVersionRoot) { throw "PRESERVE_UNINSTALL_VERSION_DIRECTORY_LEFT_BEHIND" }
    if (Test-Path $currentMarker) { throw "PRESERVE_UNINSTALL_VERSION_MARKER_LEFT_BEHIND" }
    if (Test-Path $productKey) { throw "PRESERVE_UNINSTALL_PRODUCT_REGISTRY_LEFT_BEHIND" }
    if (Test-Path $shortcut) { throw "PRESERVE_UNINSTALL_SHORTCUT_LEFT_BEHIND" }
    $startupAfterUninstall = Get-RegistryValueSnapshot $runKey "TDA Companion Agent"
    if ($startupAfterUninstall.Exists) { throw "PRESERVE_UNINSTALL_STARTUP_LEFT_BEHIND" }

    # Reinstall and verify explicit purge removes every TDA per-user root.
    Invoke-Msi @("/i", "`"$msi`"", "/qn") "04-reinstall-for-purge.log"
    $maintenanceExe = Current-MaintenanceExe
    if (-not (Test-Path $maintenanceExe)) { throw "MAINTENANCE_EXE_MISSING_BEFORE_PURGE" }
    $purge = Start-Process -FilePath $maintenanceExe -ArgumentList @("--uninstall", "--purge", "--parent-pid", "0") -Wait -PassThru
    if ($purge.ExitCode -ne 0) { throw "MAINTENANCE_PURGE_FAILED:$($purge.ExitCode)" }
    if (Test-Path $tdaRoot) { throw "PURGE_ROOT_LEFT_BEHIND" }

    Write-Host "TDA Companion rollback, live-Agent MajorUpgrade, metadata cleanup, preserve uninstall and purge smoke: PASS ($CurrentVersion)"
}
finally {
    try {
        Get-Process TDACompanion -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -like (Join-Path $tdaRoot "Companion\versions\*") } |
            Stop-Process -Force -ErrorAction SilentlyContinue
    } catch {}
    try {
        $installedCode = (Get-ItemProperty -Path $productKey -ErrorAction SilentlyContinue).ProductCode
        if ($installedCode) {
            Start-Process -FilePath "msiexec.exe" -ArgumentList @("/x", $installedCode, "/qn", "/norestart") -Wait | Out-Null
        }
    } catch {}
    Remove-Item $tdaRoot -Recurse -Force -ErrorAction SilentlyContinue
}