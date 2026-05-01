$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $root "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logsDir ("tests_{0}.log" -f $timestamp)

Write-Host ("Logging test output to {0}" -f $logPath)

$cmd = "python -m pytest tests -v"
& powershell -NoProfile -Command $cmd 2>&1 | Tee-Object -FilePath $logPath

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
