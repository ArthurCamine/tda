param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$DataRoot
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$install = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\','/')
$data = [IO.Path]::GetFullPath($DataRoot).TrimEnd('\','/')
if ($install -eq $data -or $data.StartsWith($install + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or $install.StartsWith($data + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'INSTALL_AND_DATA_MUST_BE_SEPARATE'
}

$companionRoot = Split-Path -Parent $PSScriptRoot
$pyprojectPath = Join-Path $companionRoot 'pyproject.toml'
$initPath = Join-Path $companionRoot 'tda_companion/__init__.py'
if (-not (Test-Path -LiteralPath $pyprojectPath -PathType Leaf)) { throw 'PYPROJECT_NOT_FOUND' }
if (-not (Test-Path -LiteralPath $initPath -PathType Leaf)) { throw 'COMPANION_VERSION_SOURCE_NOT_FOUND' }

$pyproject = Get-Content -LiteralPath $pyprojectPath -Raw -Encoding UTF8
$init = Get-Content -LiteralPath $initPath -Raw -Encoding UTF8
$projectVersionMatch = [regex]::Match($pyproject, '(?m)^version\s*=\s*"(?<value>[0-9]+\.[0-9]+\.[0-9]+)"\s*$')
$pythonMatch = [regex]::Match($pyproject, '(?m)^requires-python\s*=\s*"(?<value>[^"]+)"\s*$')
$runtimeVersionMatch = [regex]::Match($init, '(?m)^VERSION\s*=\s*"(?<value>[0-9]+\.[0-9]+\.[0-9]+)"\s*$')
if (-not $projectVersionMatch.Success -or -not $runtimeVersionMatch.Success) { throw 'COMPANION_VERSION_METADATA_INVALID' }
if (-not $pythonMatch.Success) { throw 'COMPANION_PYTHON_REQUIREMENT_INVALID' }

$version = $projectVersionMatch.Groups['value'].Value
$runtimeVersion = $runtimeVersionMatch.Groups['value'].Value
$pythonRequirement = $pythonMatch.Groups['value'].Value
if ($version -ne $runtimeVersion) { throw "COMPANION_VERSION_METADATA_MISMATCH:${version}:${runtimeVersion}" }

[ordered]@{
    schema_version = 'tda_install_plan_v1'
    mode = 'per-user-versioned-bundle'
    version = $version
    install_root = $install
    data_root = $data
    privileges = 'current-user'
    runtime = "Self-contained PyInstaller onedir bundle; Python requirement $pythonRequirement"
    operations = @('Verify package layout', 'Install versioned bundle', 'Create Start Menu shortcut', 'Generate user-only pairing token on first launch', 'Run loopback HTTP supervisor')
    automatic_startup = $false
    registry_changes = $false
    service_installation = $false
    legacy_dependency = $false
    legacy_process_changes = $false
    rollback = 'Close this instance; select/reinstall a prior TDA Companion bundle; preserve TDA data root unless removal is explicit'
} | ConvertTo-Json -Depth 5
