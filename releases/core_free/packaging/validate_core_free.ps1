param(
  [string]$StagingRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$releaseRoot = Split-Path -Parent $PSScriptRoot
$configRoot = Join-Path $releaseRoot "config"
$bundleManifestPath = Join-Path $releaseRoot "bundle_manifest.json"

function Read-Text([string]$Path) {
  return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

$manifestPath = Join-Path $releaseRoot "manifest.json"
$firstRunGuidePath = Join-Path $releaseRoot "FIRST_RUN.md"
$launcherPs1Path = Join-Path $releaseRoot "Launch-Core-Free.ps1"
$launcherCmdPath = Join-Path $releaseRoot "Launch-Core-Free.cmd"
$bundleManifest = Get-Content -LiteralPath $bundleManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$distributionPath = Join-Path $configRoot "plugin_distribution.json"
$entitlementsPath = Join-Path $configRoot "plugin_entitlements.json"
$pluginsTomlPath = Join-Path $configRoot "plugins.toml"
$defaultPresetPath = Join-Path $configRoot "settings\pipeline\default.json"

foreach ($required in @($bundleManifestPath, $manifestPath, $firstRunGuidePath, $launcherPs1Path, $launcherCmdPath, $distributionPath, $entitlementsPath, $pluginsTomlPath, $defaultPresetPath)) {
  if (-not (Test-Path $required)) {
    throw "missing_required_file: $required"
  }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$distribution = Get-Content -LiteralPath $distributionPath -Raw -Encoding UTF8 | ConvertFrom-Json
$entitlements = Get-Content -LiteralPath $entitlementsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$preset = Get-Content -LiteralPath $defaultPresetPath -Raw -Encoding UTF8 | ConvertFrom-Json
$pluginsToml = Read-Text $pluginsTomlPath
$expectedBundledPluginIds = @(
  "transcription.whisperadvanced",
  "llm.llama_cli",
  "text_processing.minutes_heuristic_v2",
  "text_processing.semantic_refiner"
)
$expectedReleasePluginSettings = @(
  "llm.llama_cli.json",
  "transcription.whisperadvanced.json"
)

if ($manifest.release_id -ne "core_free") {
  throw "invalid_release_id"
}

if ($entitlements.edition -ne "core_free") {
  throw "invalid_entitlements_edition"
}

if ($entitlements.platform_edition.enabled -ne $false) {
  throw "platform_edition_must_be_disabled"
}

if ($manifest.ui_flags.show_management_tab -ne $false) {
  throw "management_tab_must_be_hidden"
}

if ($manifest.ui_flags.show_plugin_marketplace -ne $false) {
  throw "plugin_marketplace_must_be_hidden"
}

if ($manifest.ui_flags.allow_plugin_package_install -ne $false) {
  throw "package_management_must_be_disabled"
}

$bundledPluginIds = @($manifest.bundled_plugins | ForEach-Object { [string]$_ } | Sort-Object -Unique)
$expectedBundledJoined = ($expectedBundledPluginIds | Sort-Object -Unique) -join "|"
$actualBundledJoined = $bundledPluginIds -join "|"
if ($actualBundledJoined -ne $expectedBundledJoined) {
  throw "bundled_plugins_mismatch: expected=$expectedBundledJoined actual=$actualBundledJoined"
}

$baselinePluginIds = @($distribution.baseline_plugin_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
$baselineJoined = $baselinePluginIds -join "|"
if ($baselineJoined -ne $expectedBundledJoined) {
  throw "baseline_plugin_ids_mismatch: expected=$expectedBundledJoined actual=$baselineJoined"
}

if ($pluginsToml -match "management\." -or $pluginsToml -match "service\." -or $pluginsToml -match "integration\.") {
  throw "free_profile_contains_forbidden_plugins"
}

if ($preset.stages.llm_processing.plugin_id -ne "llm.llama_cli") {
  throw "llm_processing_must_point_to_llama_cli"
}

if ([string]$preset.stages.llm_processing.params.gpu_layers -ne "-1") {
  throw "gpu_layers_must_remain_minus_one"
}

$releasePluginSettingsDir = Join-Path $configRoot "settings\plugins"
$releasePluginSettings = @()
if (Test-Path -LiteralPath $releasePluginSettingsDir) {
  $releasePluginSettings = @(
    Get-ChildItem -LiteralPath $releasePluginSettingsDir -File -Filter "*.json" |
      Select-Object -ExpandProperty Name |
      Sort-Object -Unique
  )
}
$expectedReleasePluginSettingsJoined = ($expectedReleasePluginSettings | Sort-Object -Unique) -join "|"
$actualReleasePluginSettingsJoined = ($releasePluginSettings | Sort-Object -Unique) -join "|"
if ($actualReleasePluginSettingsJoined -ne $expectedReleasePluginSettingsJoined) {
  throw "release_plugin_settings_mismatch: expected=$expectedReleasePluginSettingsJoined actual=$actualReleasePluginSettingsJoined"
}

if ($StagingRoot) {
  $resolvedStagingRoot = (Resolve-Path -LiteralPath $StagingRoot).Path

  foreach ($relativePath in @($bundleManifest.copy_directories)) {
    $target = Join-Path $resolvedStagingRoot ([string]$relativePath)
    if (-not (Test-Path -LiteralPath $target -PathType Container)) {
      throw "missing_staging_directory: $relativePath"
    }
  }

  foreach ($requiredReleaseFile in @(
    "releases/core_free/manifest.json",
    "releases/core_free/FIRST_RUN.md",
    "releases/core_free/Launch-Core-Free.ps1",
    "releases/core_free/Launch-Core-Free.cmd",
    "releases/core_free/run_ui.py"
  )) {
    $target = Join-Path $resolvedStagingRoot $requiredReleaseFile
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
      throw "missing_staging_release_file: $requiredReleaseFile"
    }
  }

  foreach ($relativePath in @($bundleManifest.copy_files)) {
    $target = Join-Path $resolvedStagingRoot ([string]$relativePath)
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
      throw "missing_staging_file: $relativePath"
    }
  }

  foreach ($relativePath in @($bundleManifest.empty_directories)) {
    $target = Join-Path $resolvedStagingRoot ([string]$relativePath)
    if (-not (Test-Path -LiteralPath $target -PathType Container)) {
      throw "missing_staging_empty_directory: $relativePath"
    }
  }

  foreach ($relativePath in @($bundleManifest.forbidden_local_config_paths)) {
    $target = Join-Path $resolvedStagingRoot ([string]$relativePath)
    if (Test-Path -LiteralPath $target) {
      throw "forbidden_local_config_path_present: $relativePath"
    }
  }

  foreach ($glob in @($bundleManifest.forbidden_globs)) {
    $matches = @(Get-ChildItem -Path (Join-Path $resolvedStagingRoot ([string]$glob)) -File -ErrorAction SilentlyContinue)
    if ($matches.Count -gt 0) {
      throw "forbidden_staging_glob_present: $glob"
    }
  }

  $pluginIds = @(
    Get-ChildItem -Path (Join-Path $resolvedStagingRoot "plugins") -Recurse -Filter "plugin.json" -File |
      ForEach-Object {
        try {
          $payload = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
          [string]$payload.id
        } catch {
          ""
        }
      } |
      Where-Object { $_ } |
      Sort-Object -Unique
  )

  $expectedPluginIds = @($bundleManifest.expected_plugin_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
  $actualJoined = ($pluginIds -join "|")
  $expectedJoined = ($expectedPluginIds -join "|")
  if ($actualJoined -ne $expectedJoined) {
    throw "staging_plugin_manifest_mismatch: expected=$expectedJoined actual=$actualJoined"
  }

  $stagingReleasePluginSettingsDir = Join-Path $resolvedStagingRoot "releases\core_free\config\settings\plugins"
  $stagingReleasePluginSettings = @()
  if (Test-Path -LiteralPath $stagingReleasePluginSettingsDir) {
    $stagingReleasePluginSettings = @(
      Get-ChildItem -LiteralPath $stagingReleasePluginSettingsDir -File -Filter "*.json" |
        Select-Object -ExpandProperty Name |
        Sort-Object -Unique
    )
  }
  $stagingReleasePluginSettingsJoined = ($stagingReleasePluginSettings | Sort-Object -Unique) -join "|"
  if ($stagingReleasePluginSettingsJoined -ne $expectedReleasePluginSettingsJoined) {
    throw "staging_release_plugin_settings_mismatch: expected=$expectedReleasePluginSettingsJoined actual=$stagingReleasePluginSettingsJoined"
  }

  foreach ($forbiddenReleasePath in @(
    "releases/core_free/BACKLOG.md",
    "releases/core_free/INSTALLER_READINESS.md",
    "releases/core_free/README.md",
    "releases/core_free/packaging",
    "releases/core_free/tests"
  )) {
    $target = Join-Path $resolvedStagingRoot $forbiddenReleasePath
    if (Test-Path -LiteralPath $target) {
      throw "forbidden_staging_release_path_present: $forbiddenReleasePath"
    }
  }
}

Write-Host "Core Free profile validation passed."
