from __future__ import annotations

from typing import Iterable

from aimn.core.app_paths import AppPaths
from aimn.core.builtin_search import BuiltinSearchService
from aimn.core.content_service import ContentService
from aimn.core.management_store import ManagementStore
from aimn.core.meeting_service import MeetingService
from aimn.core.pipeline_presets import OFFLINE_PRESET_ID
from aimn.core.plugin_action_service import PluginActionService
from aimn.core.plugin_catalog_service import PluginCatalogService
from aimn.core.plugin_health_service import (
    PluginHealthIssue,
    PluginHealthQuickFix,
    PluginHealthReport,
    PluginHealthService,
)
from aimn.core.plugin_manifest import load_plugin_manifest
from aimn.core.plugin_models_service import PluginModelsService
from aimn.core.plugin_package_service import (
    PluginInstallResult,
    PluginPackageService,
    PluginRemoveResult,
)
from aimn.core.plugin_sync_service import (
    PluginCatalogSyncResult,
    PluginEntitlementImportResult,
    PluginSyncService,
)
from aimn.core.search_query import query_variants
from aimn.core.services.artifact_store_service import ArtifactStoreService
from aimn.core.services.embeddings_availability import embeddings_available
from aimn.core.services.pipeline_service import PipelineService
from aimn.core.settings_services import PipelinePresetService, SettingsService
from aimn.core.ui_settings_store import UiSettingsStore

__all__: Iterable[str] = [
    "AppPaths",
    "ArtifactStoreService",
    "BuiltinSearchService",
    "ContentService",
    "embeddings_available",
    "load_plugin_manifest",
    "MeetingService",
    "ManagementStore",
    "OFFLINE_PRESET_ID",
    "PipelinePresetService",
    "PipelineService",
    "PluginActionService",
    "PluginCatalogService",
    "PluginHealthService",
    "PluginHealthIssue",
    "PluginHealthQuickFix",
    "PluginHealthReport",
    "PluginInstallResult",
    "PluginModelsService",
    "PluginPackageService",
    "PluginRemoveResult",
    "PluginCatalogSyncResult",
    "PluginEntitlementImportResult",
    "PluginSyncService",
    "query_variants",
    "SettingsService",
    "UiSettingsStore",
]
