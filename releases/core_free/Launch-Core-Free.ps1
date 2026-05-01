param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$releaseRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundleRoot = Split-Path -Parent (Split-Path -Parent $releaseRoot)
$runUi = Join-Path $releaseRoot "run_ui.py"
$guide = Join-Path $releaseRoot "FIRST_RUN.md"

function Resolve-PythonCommand {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @("py", "-3.11")
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @("python")
  }

  $python3 = Get-Command python3 -ErrorAction SilentlyContinue
  if ($python3) {
    return @("python3")
  }

  return @()
}

$pythonCmd = Resolve-PythonCommand
if ($pythonCmd.Count -eq 0) {
  Write-Host "Python 3.11+ was not found." -ForegroundColor Red
  Write-Host "Install Python first, then relaunch this bundle." -ForegroundColor Yellow
  Write-Host "Guide: $guide"
  exit 1
}

Write-Host "AI Meeting Manager - Core Free" -ForegroundColor Cyan
Write-Host "Bundle root: $bundleRoot"
Write-Host "Release guide: $guide"
Write-Host "Note: bundled Whisper Tiny is ready for the first transcription run." -ForegroundColor Yellow
Write-Host "No llama GGUF model is bundled." -ForegroundColor Yellow
Write-Host "On first run, use Settings > Transcription only if you want to upgrade from Tiny." -ForegroundColor Yellow
Write-Host "Then open Settings > AI Processing and choose one local LLM model setup path:" -ForegroundColor Yellow
Write-Host "  1. Download from catalog"
Write-Host "  2. Add direct .gguf URL"
Write-Host "  3. Select local .gguf file"
Write-Host ""

$pythonExe = $pythonCmd[0]
$pythonArgs = @()
if ($pythonCmd.Count -gt 1) {
  $pythonArgs = @($pythonCmd[1..($pythonCmd.Count - 1)])
}

& $pythonExe @pythonArgs $runUi
exit $LASTEXITCODE
