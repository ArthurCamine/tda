param(
    [string]$Python = ".venv/Scripts/python.exe",
    [string]$Wix = ".wix/wix.exe",
    [string]$OutputRoot = "local-companion/out/windows"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$pythonPath = if ([IO.Path]::IsPathRooted($Python)) { $Python } else { Join-Path $repoRoot $Python }
$output = if ([IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot } else { Join-Path $repoRoot $OutputRoot }
$packageSource = Join-Path $repoRoot "local-companion"

if (-not (Test-Path $pythonPath)) {
    throw "PYTHON_NOT_FOUND: $pythonPath"
}

$wixPath = if ([IO.Path]::IsPathRooted($Wix)) {
    $Wix
} elseif (Test-Path (Join-Path $repoRoot $Wix)) {
    Join-Path $repoRoot $Wix
} else {
    (Get-Command $Wix -ErrorAction Stop).Source
}
if (-not (Test-Path $wixPath)) {
    throw "WIX_NOT_FOUND: $wixPath"
}

$version = (& $pythonPath -c "import tda_companion; print(tda_companion.VERSION)").Trim()
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "VERSION_NOT_FOUND" }

$work = Join-Path $output "work"
$dist = Join-Path $output "dist"
$maintenanceDist = Join-Path $output "maintenance-dist"
$packageRoot = Join-Path $output "TDACompanion-$version"
$appRoot = Join-Path $packageRoot "app"
$metadataRoot = Join-Path $output "metadata"

Remove-Item $output -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work, $dist, $maintenanceDist, $packageRoot, $metadataRoot | Out-Null

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name TDACompanion `
    --paths $packageSource `
    --distpath $dist `
    --workpath $work `
    --specpath $work `
    --collect-submodules uvicorn `
    --collect-data tda_companion `
    --collect-all webview `
    --collect-submodules pystray `
    (Join-Path $PSScriptRoot "windows_entry.py")
if ($LASTEXITCODE -ne 0) { throw "PYINSTALLER_FAILED" }

Copy-Item (Join-Path $dist "TDACompanion") $appRoot -Recurse

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name TDACompanionMaintenance `
    --distpath $maintenanceDist `
    --workpath (Join-Path $work "maintenance") `
    --specpath (Join-Path $work "maintenance") `
    (Join-Path $PSScriptRoot "maintenance_entry.py")
if ($LASTEXITCODE -ne 0) { throw "MAINTENANCE_PYINSTALLER_FAILED" }
$maintenanceExe = Join-Path $maintenanceDist "TDACompanionMaintenance.exe"
if (-not (Test-Path $maintenanceExe)) { throw "MAINTENANCE_EXE_NOT_CREATED" }
Copy-Item $maintenanceExe (Join-Path $appRoot "TDACompanionMaintenance.exe")
Copy-Item (Join-Path $PSScriptRoot "run-physical-acceptance.ps1") (Join-Path $appRoot "run-physical-acceptance.ps1")
Copy-Item (Join-Path $PSScriptRoot "install-rc-runtimes.ps1") (Join-Path $appRoot "install-rc-runtimes.ps1")

Copy-Item (Join-Path $PSScriptRoot "install-windows.ps1") (Join-Path $packageRoot "install.ps1")
Copy-Item (Join-Path $PSScriptRoot "uninstall-windows.ps1") (Join-Path $packageRoot "uninstall.ps1")
Set-Content -Path (Join-Path $packageRoot "version.txt") -Value $version -Encoding ascii -NoNewline
Set-Content -Path (Join-Path $metadataRoot "current-version.txt") -Value $version -Encoding ascii -NoNewline

$readme = @"
TDA Companion $version

Instalação recomendada: execute TDACompanion-x64.msi.

Alternativa portátil/manual:
1. Extraia este pacote para uma pasta local.
2. Execute install.ps1 no PowerShell.
3. Abra "TDA Companion" pelo Menu Iniciar.
4. A interface Desktop usa WebView2 e mantém o Agent em segundo plano.
5. Em https://dnd.faysk.dev/edit/processamento, conecte o Companion quando necessário.

Instalação por usuário, sem privilégios administrativos.
Diretório do aplicativo: %LOCALAPPDATA%\TDA\Companion\versions\$version
Diretório de dados:      %LOCALAPPDATA%\TDA\Data

Preparação de runtimes para teste RC sem publicar releases stable:
1. Baixe os artifacts validados `TDAWhisperRuntime-windows-x64` e `TDAQwenRuntimeBundle-windows-x64` do GitHub Actions.
2. Obtenha o digest SHA-256 informado pelo GitHub para cada artifact e use apenas os 64 caracteres hexadecimais, sem o prefixo `sha256:`.
3. Execute o helper instalado, por exemplo:

& app\install-rc-runtimes.ps1 `
  -WhisperArtifact "C:\artifacts\TDAWhisperRuntime-windows-x64.zip" `
  -WhisperArtifactSha256 "<sha256-do-artifact-whisper>" `
  -QwenArtifact "C:\artifacts\TDAQwenRuntimeBundle-windows-x64.zip" `
  -QwenArtifactSha256 "<sha256-do-artifact-qwen>"

O helper verifica primeiro o SHA-256 externo do artifact e, em seguida, os hashes/tamanhos internos do runtime antes da instalação. Somente Whisper 1.1.1 e Qwen 1.0.1 são aceitos neste RC. Python, CUDA Toolkit e PATH globais não são modificados.

Depois, app\run-physical-acceptance.ps1 executa o gate físico local dos perfis ASR sem enviar áudio ao cloud. Os modelos pinados são materializados separadamente em Models na primeira execução. Por padrão o gate grava somente receipts sanitizados; transcrições exigem -WriteTranscripts explícito.

O token, a fila e os dados locais não são removidos durante atualização do aplicativo.
Este aplicativo NÃO usa, inicia, modifica ou depende do antigo DnDScribeCompanion.exe.
"@
Set-Content -Path (Join-Path $packageRoot "README.txt") -Value $readme -Encoding utf8

$zip = Join-Path $output "TDACompanion-$version-windows-x64.zip"
Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $zip -CompressionLevel Optimal

$msi = Join-Path $output "TDACompanion-x64.msi"
& $wixPath build `
    (Join-Path $PSScriptRoot "TDACompanion.wxs") `
    -arch x64 `
    -d "Version=$version" `
    -bindpath "App=$appRoot" `
    -bindpath "Metadata=$metadataRoot" `
    -pdbtype none `
    -o $msi
if ($LASTEXITCODE -ne 0) { throw "WIX_BUILD_FAILED" }
if (-not (Test-Path $msi)) { throw "MSI_NOT_CREATED" }

$msiHash = (Get-FileHash -Algorithm SHA256 $msi).Hash.ToLowerInvariant()
Set-Content -Path (Join-Path $output "TDACompanion-x64.msi.sha256") -Value "$msiHash  TDACompanion-x64.msi" -Encoding ascii -NoNewline

Write-Host "TDA Companion package: $packageRoot"
Write-Host "ZIP: $zip"
Write-Host "MSI: $msi"
Write-Host "MSI SHA256: $msiHash"
