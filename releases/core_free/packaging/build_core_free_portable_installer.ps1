param(
  [string]$ReleaseDir = "",
  [string]$PayloadZipPath = "",
  [string]$PyInstallerDistDir = "",
  [string]$OutputExePath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$packagingRoot = $PSScriptRoot
$releaseRoot = Split-Path -Parent $packagingRoot
$repoRoot = (Resolve-Path (Join-Path $releaseRoot "..\..")).Path
$buildBundleScript = Join-Path $packagingRoot "build_core_free_exe.ps1"
$installerScript = Join-Path $packagingRoot "core_free_portable_installer.py"
$manifestPath = Join-Path $releaseRoot "manifest.json"

if (-not $ReleaseDir) {
  $ReleaseDir = Join-Path $repoRoot "output_build\core_free_release"
}
if (-not $PayloadZipPath) {
  $PayloadZipPath = Join-Path $repoRoot "output_build\core_free_release_payload.zip"
}
if (-not $PyInstallerDistDir) {
  $PyInstallerDistDir = Join-Path $repoRoot "dist"
}
if (-not $OutputExePath) {
  $OutputExePath = Join-Path $repoRoot "output_build\AI Meeting Manager Free Portable Installer.exe"
}

& powershell -ExecutionPolicy Bypass -File $buildBundleScript -FinalOutputDir $ReleaseDir

if (-not (Test-Path -LiteralPath $ReleaseDir -PathType Container)) {
  throw "missing_release_dir: $ReleaseDir"
}

if (Test-Path -LiteralPath $PayloadZipPath) {
  Remove-Item -LiteralPath $PayloadZipPath -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($ReleaseDir, $PayloadZipPath)

$resolvedDistRoot = (New-Item -ItemType Directory -Force -Path $PyInstallerDistDir).FullName
$exeName = "AI Meeting Manager Free Portable Installer"
$pyInstallerExePath = Join-Path $resolvedDistRoot "$exeName.exe"
$workPath = Join-Path $repoRoot "build\pyinstaller_core_free_portable_installer"

if (Test-Path -LiteralPath $pyInstallerExePath) {
  Remove-Item -LiteralPath $pyInstallerExePath -Force
}
if (Test-Path -LiteralPath $workPath) {
  Remove-Item -LiteralPath $workPath -Recurse -Force
}

Push-Location $repoRoot
try {
  & python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $exeName `
    --distpath $resolvedDistRoot `
    --workpath $workPath `
    --collect-data huggingface_hub `
    --collect-submodules huggingface_hub `
    --add-data "$PayloadZipPath;." `
    --add-data "$manifestPath;." `
    $installerScript
} finally {
  Pop-Location
}

if (-not (Test-Path -LiteralPath $pyInstallerExePath -PathType Leaf)) {
  throw "missing_installer_exe: $pyInstallerExePath"
}

$outputParent = Split-Path -Parent $OutputExePath
if ($outputParent) {
  New-Item -ItemType Directory -Force -Path $outputParent | Out-Null
}
Copy-Item -LiteralPath $pyInstallerExePath -Destination $OutputExePath -Force

Write-Host "Portable installer created at: $OutputExePath"
Write-Host "Payload archive: $PayloadZipPath"
