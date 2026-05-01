param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$logsDir = Join-Path $root "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

$localTemp = Join-Path $root ".codex_tmp_test"
if (-not (Test-Path $localTemp)) {
    New-Item -ItemType Directory -Path $localTemp | Out-Null
}
$pytestCache = Join-Path $localTemp "pytest_cache"
if (-not (Test-Path $pytestCache)) {
    New-Item -ItemType Directory -Path $pytestCache | Out-Null
}

$env:TEMP = $localTemp
$env:TMP = $localTemp

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logsDir ("tests_local_temp_{0}.log" -f $timestamp)

if ($PytestArgs.Count -gt 0) {
    $targetArgs = $PytestArgs
} else {
    $targetArgs = @("tests", "-v")
}
$targetArgs = @("-o", "cache_dir=$pytestCache") + $targetArgs

Write-Host ("TEMP={0}" -f $env:TEMP)
Write-Host ("PYTEST_CACHE_DIR={0}" -f $pytestCache)
Write-Host ("Logging test output to {0}" -f $logPath)

Push-Location $root
try {
    & python -m pytest @targetArgs 2>&1 | Tee-Object -FilePath $logPath
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
