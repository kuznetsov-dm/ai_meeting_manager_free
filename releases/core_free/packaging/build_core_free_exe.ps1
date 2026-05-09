param(
  [string]$StagingDir = "",
  [string]$PyInstallerDistDir = "",
  [string]$FinalOutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$packagingRoot = $PSScriptRoot
$releaseRoot = Split-Path -Parent $packagingRoot
$repoRoot = (Resolve-Path (Join-Path $releaseRoot "..\..")).Path
$buildBundleScript = Join-Path $packagingRoot "build_core_free.ps1"
$launcherScript = Join-Path $packagingRoot "core_free_launcher.py"
$iconPath = Join-Path $repoRoot "src\aimn\ui\assets\app_icon.ico"

if (-not $StagingDir) {
  $StagingDir = Join-Path $repoRoot "output_build\core_free_profile"
}
if (-not $PyInstallerDistDir) {
  $PyInstallerDistDir = Join-Path $repoRoot "dist"
}
if (-not $FinalOutputDir) {
  $FinalOutputDir = Join-Path $repoRoot "output_build\core_free_release"
}

$resolvedDistRoot = (New-Item -ItemType Directory -Force -Path $PyInstallerDistDir).FullName
$exeName = "AI Meeting Manager Core Free"
$pyInstallerOutput = Join-Path $resolvedDistRoot $exeName

if (Test-Path -LiteralPath $pyInstallerOutput) {
  Remove-Item -LiteralPath $pyInstallerOutput -Recurse -Force
}
if (Test-Path -LiteralPath $FinalOutputDir) {
  Remove-Item -LiteralPath $FinalOutputDir -Recurse -Force
}

& powershell -ExecutionPolicy Bypass -File $buildBundleScript -OutputDir $StagingDir

Push-Location $repoRoot
try {
  & python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $exeName `
    --distpath $resolvedDistRoot `
    --workpath (Join-Path $repoRoot "build\pyinstaller_core_free") `
    --icon $iconPath `
    --paths (Join-Path $repoRoot "src") `
    --collect-submodules aimn `
    --collect-data aimn.ui.assets `
    --collect-data huggingface_hub `
    --collect-submodules huggingface_hub `
    --collect-data sentence_transformers `
    --collect-submodules sentence_transformers `
    --collect-data transformers `
    --collect-submodules transformers.models.auto `
    --collect-submodules transformers.models.bert `
    --collect-submodules transformers.models.roberta `
    --collect-submodules transformers.models.xlm_roberta `
    --collect-submodules tokenizers `
    --collect-submodules safetensors `
    --collect-data torch `
    --collect-binaries torch `
    --hidden-import torch `
    --hidden-import sklearn.metrics.pairwise `
    --hidden-import sklearn.metrics._pairwise_distances_reduction `
    --collect-binaries scipy `
    --collect-binaries numpy `
    $launcherScript
} finally {
  Pop-Location
}

if (-not (Test-Path -LiteralPath $pyInstallerOutput -PathType Container)) {
  throw "missing_pyinstaller_output: $pyInstallerOutput"
}

Copy-Item -LiteralPath $pyInstallerOutput -Destination $FinalOutputDir -Recurse -Force

Get-ChildItem -LiteralPath $StagingDir -Force | ForEach-Object {
  $target = Join-Path $FinalOutputDir $_.Name
  if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
  }
  Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
}

$exePath = Join-Path $FinalOutputDir "$exeName.exe"
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
  throw "missing_release_exe: $exePath"
}

$legacyPortableSetupPath = Join-Path $FinalOutputDir "AI Meeting Manager Free Portable Setup.exe"
if (Test-Path -LiteralPath $legacyPortableSetupPath) {
  Remove-Item -LiteralPath $legacyPortableSetupPath -Force
}

Write-Host "Core Free release bundle created at: $FinalOutputDir"
Write-Host "Executable: $exePath"
