param(
  [Parameter(Mandatory = $false)]
  [string]$SourceDir = "",

  [Parameter(Mandatory = $false)]
  [string]$BuildType = "Release",

  [Parameter(Mandatory = $false)]
  [switch]$BuildVulkan = $true,

  [Parameter(Mandatory = $false)]
  [switch]$BuildCpu = $true
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-SourceDir([string]$RepoRoot, [string]$Raw) {
  if ($Raw -and (Test-Path $Raw)) {
    return (Resolve-Path $Raw).Path
  }
  $candidates = @(
    (Join-Path $RepoRoot "external\\llama.cpp"),
    (Join-Path $RepoRoot "llama.cpp")
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) {
      return (Resolve-Path $c).Path
    }
  }
  return $null
}

function Require-CMake {
  $cmake = (Get-Command cmake -ErrorAction SilentlyContinue)
  if (-not $cmake) {
    throw "cmake_not_found: install CMake and ensure 'cmake' is on PATH"
  }
}

function Find-Artifact([string]$BuildDir, [string]$FileName) {
  $items = Get-ChildItem -Path $BuildDir -Recurse -File -Filter $FileName -ErrorAction SilentlyContinue
  if (-not $items) { return $null }
  return $items[0].FullName
}

function Copy-IfExists([string]$Path, [string]$DestDir, [string]$DestName) {
  if (-not $Path) { return }
  if (-not (Test-Path $Path)) { return }
  $dest = Join-Path $DestDir $DestName
  Copy-Item -Force $Path $dest
}

function Invoke-LlamaBuild {
  param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [Parameter(Mandatory = $true)]
    [string]$SourceDir,

    [Parameter(Mandatory = $true)]
    [string]$BuildDir,

    [Parameter(Mandatory = $true)]
    [hashtable]$CMakeDefines
  )

  New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

  $defs = @()
  foreach ($k in $CMakeDefines.Keys) {
    $v = $CMakeDefines[$k]
    $defs += "-D$k=$v"
  }

  Write-Host "Configuring: $BuildDir"
  & cmake -S $SourceDir -B $BuildDir @defs | Out-Host

  Write-Host "Building: $BuildDir ($BuildType)"
  & cmake --build $BuildDir --config $BuildType --target llama-cli llama-server | Out-Host
}

function Merge-HashTables([hashtable]$A, [hashtable]$B) {
  $out = @{}
  foreach ($k in $A.Keys) { $out[$k] = $A[$k] }
  foreach ($k in $B.Keys) { $out[$k] = $B[$k] }
  return $out
}

if ($env:OS -notlike "*Windows*") {
  throw "windows_only"
}

$repoRoot = Resolve-RepoRoot
$src = Resolve-SourceDir -RepoRoot $repoRoot -Raw $SourceDir
if (-not $src) {
  throw "llama_cpp_source_not_found: pass -SourceDir or place sources under 'external\\llama.cpp'"
}

Require-CMake

$outDir = Join-Path $repoRoot "bin\\llama"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Portable build settings:
# - GGML_NATIVE=OFF to avoid machine-specific CPU flags baked into the main binary.
# - GGML_CPU_ALL_VARIANTS=ON + GGML_BACKEND_DL=ON to ship CPU variant DLLs.
# - GGML_VULKAN=ON for ggml Vulkan backend (iGPU/dGPU acceleration).
$common = @{
  "CMAKE_BUILD_TYPE"        = $BuildType
  "GGML_NATIVE"             = "OFF"
  "GGML_BACKEND_DL"         = "ON"
  "GGML_CPU_ALL_VARIANTS"   = "ON"
}

if ($BuildVulkan) {
  $buildDirVk = Join-Path $repoRoot "output_build\\llama_cpp_vk"
  $vkDefines = Merge-HashTables $common @{
    "GGML_VULKAN" = "ON"
  }
  Invoke-LlamaBuild -RepoRoot $repoRoot -SourceDir $src -BuildDir $buildDirVk -CMakeDefines $vkDefines

  $cli = Find-Artifact -BuildDir $buildDirVk -FileName "llama-cli.exe"
  $srv = Find-Artifact -BuildDir $buildDirVk -FileName "llama-server.exe"
  if (-not $cli) { throw "build_failed_missing_llama_cli_exe(vulkan)" }
  Copy-IfExists -Path $cli -DestDir $outDir -DestName "llama-cli.exe"
  if ($srv) { Copy-IfExists -Path $srv -DestDir $outDir -DestName "llama-server.exe" }

  foreach ($dll in @("ggml.dll","ggml-base.dll","ggml-vulkan.dll","llama.dll","mtmd.dll")) {
    $p = Find-Artifact -BuildDir $buildDirVk -FileName $dll
    if ($p) { Copy-IfExists -Path $p -DestDir $outDir -DestName $dll }
  }

  foreach ($cpuDll in @(
    "ggml-cpu-x64.dll",
    "ggml-cpu-sse42.dll",
    "ggml-cpu-haswell.dll",
    "ggml-cpu-alderlake.dll",
    "ggml-cpu-icelake.dll",
    "ggml-cpu-sandybridge.dll",
    "ggml-cpu-skylakex.dll"
  )) {
    $p = Find-Artifact -BuildDir $buildDirVk -FileName $cpuDll
    if ($p) { Copy-IfExists -Path $p -DestDir $outDir -DestName $cpuDll }
  }
}

if ($BuildCpu) {
  $buildDirCpu = Join-Path $repoRoot "output_build\\llama_cpp_cpu"
  $cpuDefines = Merge-HashTables $common @{
    "GGML_VULKAN" = "OFF"
  }
  Invoke-LlamaBuild -RepoRoot $repoRoot -SourceDir $src -BuildDir $buildDirCpu -CMakeDefines $cpuDefines

  $cli = Find-Artifact -BuildDir $buildDirCpu -FileName "llama-cli.exe"
  if (-not $cli) { throw "build_failed_missing_llama_cli_exe(cpu)" }
  Copy-IfExists -Path $cli -DestDir $outDir -DestName "llama-cli-cpu.exe"
}

Write-Host ""
Write-Host "Done. Output: $outDir"
