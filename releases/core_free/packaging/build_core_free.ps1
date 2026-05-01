param(
  [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$releaseRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $releaseRoot "..\..")).Path
$bundleManifestPath = Join-Path $releaseRoot "bundle_manifest.json"
$validateScript = Join-Path $PSScriptRoot "validate_core_free.ps1"

if (-not (Test-Path -LiteralPath $bundleManifestPath)) {
  throw "missing_bundle_manifest: $bundleManifestPath"
}

$bundle = Get-Content -LiteralPath $bundleManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

if (-not $OutputDir) {
  $OutputDir = Join-Path $repoRoot "output_build\core_free_profile"
}

$resolvedOutput = (New-Item -ItemType Directory -Force -Path $OutputDir).FullName

function Reset-TargetPath([string]$RelativePath) {
  $target = Join-Path $resolvedOutput $RelativePath
  if (-not (Test-Path -LiteralPath $target)) {
    return
  }
  $item = Get-Item -LiteralPath $target
  if ($item.PSIsContainer) {
    Remove-Item -LiteralPath $target -Recurse -Force
  } else {
    Remove-Item -LiteralPath $target -Force
  }
}

function Should-SkipPath([string]$FullName) {
  if ($FullName -match '(^|[\\/])__pycache__([\\/]|$)') {
    return $true
  }
  if ($FullName -like '*.pyc') {
    return $true
  }
  return $false
}

function Copy-RelativeFile([string]$RelativePath) {
  $source = Join-Path $repoRoot $RelativePath
  if (-not (Test-Path -LiteralPath $source)) {
    throw "missing_bundle_source_file: $RelativePath"
  }
  $target = Join-Path $resolvedOutput $RelativePath
  $parent = Split-Path -Parent $target
  if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
  }
  Copy-Item -LiteralPath $source -Destination $target -Force
}

function Copy-RelativeDirectory([string]$RelativePath) {
  $source = Join-Path $repoRoot $RelativePath
  if (-not (Test-Path -LiteralPath $source)) {
    throw "missing_bundle_source_directory: $RelativePath"
  }
  Get-ChildItem -LiteralPath $source -Recurse -File | ForEach-Object {
    if (Should-SkipPath $_.FullName) {
      return
    }
    $relativeChild = $_.FullName.Substring($source.Length).TrimStart('\', '/')
    $target = Join-Path (Join-Path $resolvedOutput $RelativePath) $relativeChild
    $parent = Split-Path -Parent $target
    if ($parent) {
      New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -LiteralPath $_.FullName -Destination $target -Force
  }
}

foreach ($managedRoot in @($bundle.managed_roots)) {
  Reset-TargetPath ([string]$managedRoot)
}

foreach ($relativePath in @($bundle.copy_directories)) {
  Copy-RelativeDirectory ([string]$relativePath)
}

foreach ($relativePath in @($bundle.copy_files)) {
  Copy-RelativeFile ([string]$relativePath)
}

foreach ($relativePath in @($bundle.empty_directories)) {
  New-Item -ItemType Directory -Force -Path (Join-Path $resolvedOutput ([string]$relativePath)) | Out-Null
}

& $validateScript -StagingRoot $resolvedOutput

Write-Host "Core Free staged bundle created at: $resolvedOutput"
Write-Host "Launch with: $resolvedOutput\\releases\\core_free\\Launch-Core-Free.cmd"
Write-Host "Guide: $resolvedOutput\\releases\\core_free\\FIRST_RUN.md"
