from __future__ import annotations

import copy
import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import (
    OFFLINE_PRESET_ID,
    AppPaths,
    ManagementStore,
    MeetingService,
    PipelinePresetService,
    PluginActionService,
    PluginCatalogService,
    PluginHealthIssue,
    PluginHealthQuickFix,
    PluginHealthReport,
    PluginHealthService,
    PluginModelsService,
    SettingsService,
)
from aimn.core.app_paths import get_default_input_dir, is_input_monitoring_enabled
from aimn.ui.controllers.artifact_action_flow_controller import ArtifactActionFlowController
from aimn.ui.controllers.artifact_lineage_controller import ArtifactLineageController
from aimn.ui.controllers.global_search_controller import GlobalSearchController
from aimn.ui.controllers.global_search_request_controller import GlobalSearchRequestController
from aimn.ui.controllers.inspection_render_controller import InspectionRenderController
from aimn.ui.controllers.llm_prompt_context_controller import LlmPromptContextController
from aimn.ui.controllers.management_cleanup_controller import ManagementCleanupController
from aimn.ui.controllers.management_navigation_controller import ManagementNavigationController
from aimn.ui.controllers.meeting_action_flow_controller import (
    MeetingActionFlowController,
    MeetingDeleteFlowCallbacks,
    MeetingExportFlowCallbacks,
    MeetingRenameFlowCallbacks,
    MeetingRerunFlowCallbacks,
)
from aimn.ui.controllers.meeting_actions_controller import MeetingActionsController
from aimn.ui.controllers.meeting_context_menu_controller import (
    MeetingContextMenuActionSpec,
    MeetingContextMenuController,
)
from aimn.ui.controllers.meeting_export_controller import MeetingExportController
from aimn.ui.controllers.meeting_history_controller import MeetingHistoryController
from aimn.ui.controllers.meeting_history_refresh_controller import MeetingHistoryRefreshController
from aimn.ui.controllers.meeting_inspection_controller import MeetingInspectionController
from aimn.ui.controllers.meeting_selection_controller import MeetingSelectionController
from aimn.ui.controllers.meeting_version_controller import MeetingVersionController
from aimn.ui.controllers.model_catalog_controller import ModelCatalogController
from aimn.ui.controllers.pipeline_input_controller import PipelineInputController
from aimn.ui.controllers.pipeline_run_controller import PipelineRunController
from aimn.ui.controllers.pipeline_runtime_config_controller import PipelineRuntimeConfigController
from aimn.ui.controllers.pipeline_ui_state_controller import PipelineUiStateController
from aimn.ui.controllers.plugin_capabilities_controller import PluginCapabilitiesController
from aimn.ui.controllers.plugin_health_interaction_controller import (
    PluginHealthInteractionController,
)
from aimn.ui.controllers.stage_action_flow_controller import StageActionFlowController
from aimn.ui.controllers.stage_artifact_navigation_controller import (
    StageArtifactNavigationController,
)
from aimn.ui.controllers.stage_plugin_config_controller import StagePluginConfigController
from aimn.ui.controllers.stage_runtime_controller import StageRuntimeController, StageRuntimeState
from aimn.ui.controllers.stage_schema_controller import StageSchemaController
from aimn.ui.controllers.stage_settings_controller import StageSettingsController
from aimn.ui.controllers.stage_view_model_composer import StageViewModelComposer
from aimn.ui.controllers.transcript_management_flow_controller import (
    TranscriptManagementCreateOutcome,
    TranscriptManagementFlowController,
)
from aimn.ui.i18n import UiI18n
from aimn.ui.services.artifact_service import ArtifactItem, ArtifactService
from aimn.ui.services.async_worker import run_async
from aimn.ui.services.log_service import LogService
from aimn.ui.services.settings_service import PipelineSettingsUiService
from aimn.ui.tabs.contracts import SettingField, SettingOption, StageViewModel
from aimn.ui.widgets.meetings_workspace_v2 import (
    HistoryPanelV2,
    MainTextPanelV2,
    MeetingsWorkspaceV2,
    PipelinePanelV2,
    TextInspectionPanelV2,
)
from aimn.ui.widgets.variants_panels import (
    AiProcessingPanel,
    TextProcessingGroupedPanel,
    TranscriptionPanel,
)

PIPELINE_STAGE_ORDER = [
    "media_convert",
    "transcription",
    "llm_processing",
    "management",
    "service",
]

_RUNTIME_PIPELINE_STAGE_ORDER = [
    "media_convert",
    "transcription",
    "text_processing",
    "llm_processing",
    "management",
    "service",
]

_UI_MEETINGS_PROMPT_SETTINGS_ID = "ui.meetings_prompt"
_UI_MEETING_RENAME_SETTINGS_ID = "ui.meeting_rename"
_UI_PATH_PREFERENCES_SETTINGS_ID = "ui.path_preferences"
_RENAME_MODES = {"metadata_only", "artifacts_and_manifest", "full_with_source"}
_PERF_WARN_REFRESH_HISTORY_MS = 250
_PERF_WARN_REFRESH_PIPELINE_MS = 200
_PERF_WARN_MEETING_SELECT_MS = 220
_MONITORED_MEDIA_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".flac",
    ".ogg",
    ".webm",
}
_LOG = logging.getLogger(__name__)
_EXPECTED_PLUGIN_RUNTIME_ERRORS = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class _MeetingRenameDialog(QDialog):
    def __init__(
        self,
        *,
        current_title: str,
        suggestions: list[str],
        parent: QWidget | None = None,
        title: str = "Rename meeting",
        intro_text: str = "Pick a suggested topic or enter a custom title.",
        title_placeholder: str = "Meeting title",
        suggestions_placeholder: str = "Select suggested topic",
        note_text: str = "The title can be edited before saving.",
        save_label: str = "Save",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(str(title or "Rename meeting"))
        self.resize(560, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro_label = QLabel(str(intro_text or "Pick a suggested topic or enter a custom title."))
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        self._title_edit = QLineEdit(self)
        self._title_edit.setPlaceholderText(str(title_placeholder or "Meeting title"))
        self._title_edit.setText(str(current_title or "").strip())
        layout.addWidget(self._title_edit)

        clean_suggestions = [str(item or "").strip() for item in (suggestions or []) if str(item or "").strip()]
        self._suggestions = clean_suggestions
        self._suggestions_combo = QComboBox(self)
        self._suggestions_combo.addItem(str(suggestions_placeholder or "Select suggested topic"), "")
        for item in clean_suggestions:
            self._suggestions_combo.addItem(item, item)
        self._suggestions_combo.currentIndexChanged.connect(self._on_suggestion_changed)
        self._suggestions_combo.setVisible(bool(clean_suggestions))
        layout.addWidget(self._suggestions_combo)

        self._note = QLabel(str(note_text or "The title can be edited before saving."))
        self._note.setObjectName("pipelineMetaLabel")
        self._note.setWordWrap(True)
        self._note.setVisible(bool(clean_suggestions))
        layout.addWidget(self._note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        if ok_btn:
            ok_btn.setText(str(save_label or "Save"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_suggestion_changed(self, index: int) -> None:
        if index <= 0:
            return
        picked = str(self._suggestions_combo.currentData() or "").strip()
        if picked:
            self._title_edit.setText(picked)
            self._title_edit.setFocus()
            self._title_edit.selectAll()

    def title_text(self) -> str:
        return str(self._title_edit.text() or "").strip()


def _stage_display_name(stage_id: str) -> str:
    names = {
        "media_convert": "Convert",
        "transcription": "Transcription",
        "text_processing": "Semantic Processing",
        "llm_processing": "AI Processing",
        "management": "Management",
        "service": "Service",
    }
    return names.get(stage_id, stage_id)


def _stage_short_name(stage_id: str) -> str:
    return _stage_display_name(stage_id).split()[0]


def _is_secret_field_name(key: str) -> bool:
    lowered = key.lower().strip()
    if lowered in {
        "key",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
    }:
        return True
    if lowered.startswith("api_key_") or lowered.endswith("_api_key") or lowered.endswith("apikey"):
        return True
    if lowered.endswith("_token") or lowered.endswith("_secret") or lowered.endswith("_password"):
        return True
    if lowered.endswith("_key") or lowered.endswith("_keys"):
        return True
    return lowered.startswith("key_")


def _coerce_setting_value(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in text:
            return float(text)
        return int(text)
    except (TypeError, ValueError):
        return value


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return False


def _cap_get(payload: object, *keys: str, default: object = None) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(str(key))
    return current if current is not None else default


def _ui_status_for_configured_stage(
    status: str,
    *,
    has_input: bool,
    is_enabled: bool,
    plugin_id: str,
    plugin_available: bool,
) -> tuple[str, str | None]:
    """
    UI-only stage status normalization.

    The pipeline tiles show "ready" when input is present and the stage is configured
    (plugin selected + available), even if the runtime state is still "idle".
    """
    status = str(status or "").strip().lower() or "idle"
    if status == "finished":
        status = "completed"
    if status in {"running", "completed", "failed", "skipped", "disabled"}:
        return status, None
    if not has_input:
        return ("idle" if is_enabled else "disabled"), None
    if not is_enabled:
        return "disabled", None
    plugin_id = str(plugin_id or "").strip()
    if not plugin_id:
        return "idle", None
    if plugin_available:
        return "ready", None
    return "idle", f"Plugin '{plugin_id}' is not available/enabled"


class MeetingsTabV2(QWidget):
    """
    Implements docs/UI.txt: pipeline panel + main workspace inside the Meetings tab.
    Owns the pipeline worker thread so MainWindow can stay thin.
    """
    runtimeInfoChanged = Signal(dict)

    def __init__(self, app_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_root = app_root
        self._i18n = UiI18n(app_root, namespace="meetings")
        self._catalog_service = PluginCatalogService(app_root)
        self._paths = AppPaths.resolve(app_root)
        self._meeting_service = MeetingService(app_root)
        self._models_service = PluginModelsService(app_root)
        self._action_service = PluginActionService(app_root, catalog_service=self._catalog_service)
        self._health_service = PluginHealthService(
            app_root,
            catalog_service=self._catalog_service,
            action_service=self._action_service,
        )

        config_dir = self._paths.config_dir / "settings"
        self._pipeline_settings = PipelinePresetService(config_dir, repo_root=self._app_root)
        self._settings_store = SettingsService(config_dir, repo_root=self._app_root)
        self._pipeline_preset = self._pipeline_settings.active_preset()
        preset_snapshot = self._pipeline_settings.load(self._pipeline_preset)
        self._config_data = preset_snapshot.config_data
        self._config_source = preset_snapshot.source
        self._config_path = preset_snapshot.path
        self._overrides = preset_snapshot.overrides
        self._offline_mode = self._pipeline_preset == OFFLINE_PRESET_ID
        try:
            self._registry_stamp = str(self._catalog_service.load().stamp or "")
        except (AttributeError, OSError, RuntimeError, ValueError):
            self._registry_stamp = ""

        self._artifact_service = ArtifactService(self._app_root)
        self._log_service = LogService()
        self._input_files: list[str] = []
        self._ad_hoc_input_files: list[str] = []
        self._all_meetings: list[object] = []
        self._pipeline_paused: bool = False
        self._monitor_input_dir: str = ""
        self._monitor_input_enabled: bool = False
        self._monitored_file_signatures: set[str] = set()
        self._meeting_history = MeetingHistoryController()
        self._meeting_actions_controller = MeetingActionsController(
            paths=self._paths,
            meeting_service=self._meeting_service,
            artifact_service=self._artifact_service,
            settings_store=self._settings_store,
            catalog_service=self._catalog_service,
            action_service=self._action_service,
            rename_settings_id=_UI_MEETING_RENAME_SETTINGS_ID,
            rename_modes=set(_RENAME_MODES),
        )
        self._meeting_selection_controller = MeetingSelectionController()
        self._meeting_version_controller = MeetingVersionController(
            artifact_service=self._artifact_service,
            meeting_service=self._meeting_service,
        )
        self._meeting_export_controller = MeetingExportController(
            action_service=self._action_service,
            meeting_service=self._meeting_service,
            plugin_display_name=self._plugin_display_name,
            plugin_capabilities=self._plugin_capabilities,
            tr=self._tr,
            fmt=self._fmt,
        )
        self._transcript_management_flow_controller = TranscriptManagementFlowController(
            store_factory=lambda: ManagementStore(self._app_root),
            tr=self._tr,
            fmt=self._fmt,
        )
        self._llm_prompt_context_controller = LlmPromptContextController(
            paths=self._paths,
            settings_store=self._settings_store,
            prompt_settings_id=_UI_MEETINGS_PROMPT_SETTINGS_ID,
        )
        self._plugin_capabilities_controller = PluginCapabilitiesController(
            get_catalog=self._get_catalog,
            list_actions=self._action_service.list_actions,
        )
        self._stage_plugin_config_controller = StagePluginConfigController(
            get_catalog=self._get_catalog,
            config_data_provider=lambda: self._config_data if isinstance(self._config_data, dict) else {},
            offline_mode=lambda: bool(self._offline_mode),
            coerce_setting_value=_coerce_setting_value,
            is_secret_field_name=_is_secret_field_name,
            plugin_capabilities=self._plugin_capabilities,
            capability_bool=self._capability_bool,
            capability_int=self._capability_int,
        )
        self._model_catalog_controller = ModelCatalogController(
            app_root=self._app_root,
            config_data_provider=lambda: self._config_data if isinstance(self._config_data, dict) else {},
            settings_store=self._settings_store,
            models_service=self._models_service,
            action_service=self._action_service,
            get_catalog=self._get_catalog,
            plugin_capabilities=self._plugin_capabilities,
            is_transcription_local_plugin=self._is_transcription_local_plugin,
            first_transcription_local_plugin_id=self._first_transcription_local_plugin_id,
            is_secret_field_name=_is_secret_field_name,
        )
        self._stage_schema_controller = StageSchemaController(
            get_catalog=self._get_catalog,
            config_data_provider=lambda: self._config_data if isinstance(self._config_data, dict) else {},
            is_transcription_local_plugin=self._is_transcription_local_plugin,
            whisper_models_state=self._model_catalog_controller.whisper_models_state,
            model_options_for=self._model_catalog_controller.model_options_for,
            is_local_models_plugin=self._model_catalog_controller.is_local_models_plugin,
            load_agenda_catalog=self._llm_prompt_context_controller.load_agenda_catalog,
            load_project_catalog=self._llm_prompt_context_controller.load_project_catalog,
            coerce_setting_value=_coerce_setting_value,
            is_secret_field_name=_is_secret_field_name,
        )
        self._stage_settings_controller = StageSettingsController()
        self._pipeline_runtime_config_controller = PipelineRuntimeConfigController()
        self._sync_pipeline_config_plugins(save_if_changed=True)
        self._pipeline_ui_state_controller = PipelineUiStateController()
        self._stage_view_model_composer = StageViewModelComposer(
            current_stage_states=self._current_stage_states,
            is_stage_disabled=self._is_stage_disabled,
            stage_display_name=self._stage_display_name,
            stage_short_name=self._stage_short_name,
            config_data_provider=lambda: self._config_data if isinstance(self._config_data, dict) else {},
            input_files_provider=lambda: list(self._input_files),
            active_meeting_base_name_provider=lambda: str(self._active_meeting_base_name or ""),
            active_meeting_source_path_provider=lambda: str(self._active_meeting_source_path or ""),
            stage_plugin_options=self._stage_plugin_options,
            stage_defaults=self._stage_defaults,
            schema_for=lambda plugin_id, stage_id: self._schema_for(plugin_id, stage_id=stage_id),
            inline_settings_keys=self._inline_settings_keys,
            supports_transcription_quality_presets=self._supports_transcription_quality_presets,
            order_transcription_providers=self._order_transcription_providers,
            whisper_models_state=self._whisper_models_state,
            text_processing_provider_group=self._text_processing_provider_group,
            plugin_available=self._plugin_available,
            llm_enabled_models_from_stage=self._llm_enabled_models_from_stage,
            llm_provider_models_payload=self._llm_provider_models_payload,
            get_catalog=self._get_catalog,
            current_meeting_provider=self._current_meeting_manifest_for_ui,
            normalize_ui_status=_ui_status_for_configured_stage,
        )

        self._stage_runtime = StageRuntimeController(
            stage_order=_RUNTIME_PIPELINE_STAGE_ORDER,
            stage_title=lambda stage_id: self._stage_display_name(
                StageArtifactNavigationController.ui_stage_id(stage_id)
            ),
        )
        self._plugin_health_interaction = PluginHealthInteractionController(
            parent=self,
            stage_order=list(_RUNTIME_PIPELINE_STAGE_ORDER),
            stage_display_name=lambda stage_id: self._stage_display_name(
                StageArtifactNavigationController.ui_stage_id(stage_id)
            ),
            plugin_display_name=lambda plugin_id: self._get_catalog().display_name(str(plugin_id or "").strip()),
            plugin_available=self._plugin_available,
            plugin_capabilities=self._plugin_capabilities,
            health_service=self._health_service,
            log_message=lambda message, stage_id="ui": self._log_service.append_message(message, stage_id=stage_id),
            open_stage_settings=lambda stage_id: self._pipeline_panel.open_settings(
                self._build_stage_view_model(StageArtifactNavigationController.ui_stage_id(stage_id))
            ),
            apply_skip_once=self._apply_skip_once,
            apply_disable_preset=self._apply_disable_preset,
            offline_mode=lambda: bool(self._offline_mode),
            report_progress=self._on_preflight_health_progress,
            tr=self._tr,
            fmt=self._fmt,
        )
        self._last_stage_base_name: str = ""
        self._preflight_health_state: dict[str, object] = {
            "running": False,
            "summary": "",
            "stage_name": "",
            "plugin_name": "",
            "log_lines": [],
        }
        self._startup_prewarm_lock = threading.Lock()
        self._startup_prewarm_job: dict[str, object] = {
            "running": False,
            "done": False,
            "results": [],
            "error": "",
            "thread": None,
        }
        self._startup_prewarm_started = False

        self._settings_service = PipelineSettingsUiService(
            selected_plugin_provider=self._selected_plugin_id,
            plugin_options_provider=self._stage_plugin_options,
            defaults_provider=self._stage_defaults,
            custom_panel_factory=self._build_custom_panel,
        )

        self._pipeline_panel = PipelinePanelV2(
            self._settings_service, experimental_artifacts_click=False
        )
        self._pipeline_panel.set_default_input_dir(str(get_default_input_dir(self._app_root) or ""))
        self._history_panel = HistoryPanelV2()
        self._inspection_panel = TextInspectionPanelV2()
        self._text_panel = MainTextPanelV2(self._artifact_service.read_artifact_text)
        self._global_search_controller = GlobalSearchController(
            catalog_service=self._catalog_service,
            action_service=self._action_service,
            text_panel=self._text_panel,
            history_panel=self._history_panel,
            all_meetings_provider=lambda: list(self._all_meetings),
            refresh_history=lambda select_base_name="": self._refresh_history(select_base_name=select_base_name),
            active_meeting_base_name_provider=lambda: str(self._active_meeting_base_name or ""),
        )
        self._inspection_render_controller = InspectionRenderController(app_root=self._app_root)
        self._workspace = MeetingsWorkspaceV2(
            self._pipeline_panel,
            self._history_panel,
            self._inspection_panel,
            self._text_panel,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._workspace, 1)

        self._pipeline_panel.stageClicked.connect(self._on_stage_clicked)
        self._pipeline_panel.stageContextRequested.connect(self._on_stage_context_requested)
        self._pipeline_panel.stageSettingsChanged.connect(self._on_stage_settings_changed)
        self._pipeline_panel.stageEnabledChanged.connect(self._on_stage_enabled_changed)
        self._pipeline_panel.stageActionRequested.connect(self._on_stage_action_requested)
        self._pipeline_panel.runClicked.connect(self._start_pipeline)
        self._pipeline_panel.filesAdded.connect(self._on_files_added)
        self._pipeline_panel.pauseToggled.connect(self._on_pause_toggled)
        self._pipeline_panel.stopClicked.connect(self._on_stop_clicked)

        self._history_panel.meetingSelected.connect(self._on_meeting_selected)
        self._history_panel.meetingRenameRequested.connect(self._on_meeting_rename_requested)
        self._history_panel.meetingDeleteRequested.connect(self._on_meeting_delete_requested)
        self._history_panel.meetingRerunRequested.connect(self._on_meeting_rerun_requested)
        self._history_panel.meetingExportRequested.connect(self._on_meeting_export_requested)
        self._text_panel.globalSearchOpenRequested.connect(self._on_global_search_open)
        self._text_panel.globalSearchRequested.connect(self._on_global_search_requested)
        self._text_panel.globalSearchCleared.connect(self._clear_global_search)
        self._text_panel.pinRequested.connect(self._on_pin_requested)
        self._text_panel.unpinRequested.connect(self._on_unpin_requested)
        self._text_panel.activeVersionChanged.connect(self._on_active_version_changed)
        self._text_panel.artifactSelectionChanged.connect(self._on_text_selection_changed)
        self._text_panel.artifactKindContextRequested.connect(self._on_artifact_kind_context_requested)
        self._text_panel.artifactVersionContextRequested.connect(self._on_artifact_version_context_requested)
        self._text_panel.artifactTextExportRequested.connect(self._on_artifact_text_export_requested)
        self._text_panel.transcriptManagementCreateRequested.connect(self._on_transcript_management_create_requested)
        self._text_panel.transcriptManagementSuggestionActionRequested.connect(
            self._on_transcript_management_suggestion_action_requested
        )

        self._log_service.log_appended.connect(self._on_log_appended)
        self._logs_flush_timer = QTimer(self)
        self._logs_flush_timer.setSingleShot(True)
        self._logs_flush_timer.timeout.connect(self._flush_logs_to_text_panel)
        self._pipeline_refresh_timer = QTimer(self)
        self._pipeline_refresh_timer.setSingleShot(True)
        self._pipeline_refresh_timer.setInterval(80)
        self._pipeline_refresh_timer.timeout.connect(self._flush_deferred_pipeline_refresh)
        self._pipeline_refresh_pending = False
        self._runtime_refresh_timer = QTimer(self)
        self._runtime_refresh_timer.setSingleShot(True)
        self._runtime_refresh_timer.setInterval(120)
        self._runtime_refresh_timer.timeout.connect(self._flush_deferred_runtime_refresh)
        self._runtime_refresh_pending = False
        self._startup_prewarm_timer = QTimer(self)
        self._startup_prewarm_timer.setSingleShot(False)
        self._startup_prewarm_timer.setInterval(250)
        self._startup_prewarm_timer.timeout.connect(self._poll_startup_provider_prewarm)

        self._pipeline_runner = PipelineRunController(self._app_root, self)
        self._pipeline_runner.log.connect(lambda msg: self._log_service.append_message(str(msg)))
        self._pipeline_runner.stageStatus.connect(self._on_stage_status)
        self._pipeline_runner.pipelineEvent.connect(self._on_pipeline_event)
        self._pipeline_runner.fileStarted.connect(self._on_file_started)
        self._pipeline_runner.fileCompleted.connect(self._on_file_completed)
        self._pipeline_runner.fileFailed.connect(self._on_file_failed)
        self._pipeline_runner.finished.connect(self._on_pipeline_finished)
        self._pipeline_runner.failed.connect(self._on_pipeline_failed)

        self._active_meeting_base_name: str = ""
        self._active_meeting_source_path: str = ""
        self._active_artifacts: list[ArtifactItem] = []
        self._active_meeting_manifest: object | None = None
        self._segments_relpaths_by_alias: dict[str, str] = {}
        self._meeting_payload_cache: dict[str, dict] = {}
        self._pending_management_navigation: dict[str, object] | None = None
        self._history_refresh_request_id: int = 0
        self._active_meeting_refresh_request_id: int = 0
        self._meeting_select_request_id: int = 0
        self._global_search_request_id: int = 0
        self._registry_poll_request_id: int = 0
        self._registry_poll_running: bool = False
        self._registry_poll_pending: bool = False
        self._history_refresh_pending_select_base: str = ""
        self._active_meeting_refresh_pending_base: str = ""
        self._history_refresh_timer = QTimer(self)
        self._history_refresh_timer.setSingleShot(True)
        self._history_refresh_timer.setInterval(40)
        self._history_refresh_timer.timeout.connect(self._flush_deferred_history_refresh)
        self._active_meeting_refresh_timer = QTimer(self)
        self._active_meeting_refresh_timer.setSingleShot(True)
        self._active_meeting_refresh_timer.setInterval(120)
        self._active_meeting_refresh_timer.timeout.connect(self._flush_deferred_active_meeting_refresh)
        self._input_monitor_timer = QTimer(self)
        self._input_monitor_timer.setSingleShot(False)
        self._input_monitor_timer.setInterval(1500)
        self._input_monitor_timer.timeout.connect(self._poll_monitored_input_dir)
        self._selected_artifact_stage_id: str = ""
        self._selected_artifact_alias: str = ""
        self._selected_artifact_kind: str = ""

        self._rerender_timer = QTimer(self)
        self._rerender_timer.setSingleShot(True)
        self._rerender_timer.timeout.connect(self._rerender_open_drawer)
        self._refresh_history()
        self._refresh_global_search_ui()
        self._refresh_pipeline_ui()
        self._apply_workspace_labels()
        self._refresh_artifact_export_targets()

        self._registry_watch = QTimer(self)
        self._registry_watch.setInterval(1200)
        self._registry_watch.timeout.connect(self._poll_registry)
        self._registry_watch.start()

        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(1500)
        self._activity_timer.timeout.connect(self._tick_activity)
        self._activity_timer.start()
        self.apply_path_preferences()
        QTimer.singleShot(0, self._maybe_run_startup_provider_prewarm)

    def _tr(self, key: str, default: str) -> str:
        return self._i18n.t(key, default)

    def _fmt(self, key: str, default: str, **kwargs: object) -> str:
        template = self._tr(key, default)
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template

    def _emit_slow_path_log(
        self,
        *,
        name: str,
        started_at: float,
        threshold_ms: int,
        details: dict[str, object] | None = None,
    ) -> None:
        elapsed_ms = int(max(0.0, (time.perf_counter() - float(started_at)) * 1000.0))
        if elapsed_ms < max(1, int(threshold_ms)):
            return
        info = dict(details or {})
        info["elapsed_ms"] = elapsed_ms
        kv = ", ".join(f"{key}={value}" for key, value in sorted(info.items()))
        message = f"slow_ui_path {name}: {kv}" if kv else f"slow_ui_path {name}: {elapsed_ms}ms"
        _LOG.warning(message)
        try:
            self._log_service.append_message(f"[perf] {message}", stage_id="perf")
        except RuntimeError as exc:
            _LOG.debug("perf_log_append_failed error=%s", exc)

    def _stage_display_name(self, stage_id: str) -> str:
        sid = str(stage_id or "").strip()
        defaults = {
            "input": "Input",
            "media_convert": "Convert",
            "transcription": "Transcription",
            "text_processing": "Semantic Processing",
            "llm_processing": "AI Processing",
            "management": "Management",
            "service": "Service",
            "other": "Other",
        }
        return self._tr(f"stage.{sid}", defaults.get(sid, sid))

    def _stage_short_name(self, stage_id: str) -> str:
        return self._stage_display_name(stage_id).split()[0]

    def _apply_workspace_labels(self) -> None:
        labels = {
            "tile.settings": self._tr("workspace.tile.settings", "Settings"),
            "tile.artifacts": self._tr("workspace.tile.artifacts", "Artifacts"),
            "status.idle": self._tr("workspace.status.idle", "Idle"),
            "status.ready": self._tr("workspace.status.ready", "Ready"),
            "status.running": self._tr("workspace.status.running", "Running"),
            "status.completed": self._tr("workspace.status.completed", "Completed"),
            "status.skipped": self._tr("workspace.status.skipped", "Skipped"),
            "status.failed": self._tr("workspace.status.failed", "Failed"),
            "status.disabled": self._tr("workspace.status.disabled", "Disabled"),
            "status.mock_suffix": self._tr("workspace.status.mock_suffix", "Mock"),
            "pipeline.add": self._tr("workspace.pipeline.add", "ADD"),
            "pipeline.run": self._tr("workspace.pipeline.run", "RUN"),
            "pipeline.pause": self._tr("workspace.pipeline.pause", "PAUSE"),
            "pipeline.resume": self._tr("workspace.pipeline.resume", "RESUME"),
            "pipeline.stop": self._tr("workspace.pipeline.stop", "STOP"),
            "pipeline.pick_files_title": self._tr("workspace.pipeline.pick_files_title", "Select audio/video files"),
            "pipeline.pick_files_filter": self._tr(
                "workspace.pipeline.pick_files_filter",
                "Media Files (*.wav *.mp3 *.m4a *.mp4 *.mkv *.mov *.avi *.flac *.ogg *.webm);;All Files (*.*)",
            ),
            "pipeline.drawer.settings_suffix": self._tr("workspace.pipeline.drawer.settings_suffix", "settings"),
            "pipeline.drawer.enabled": self._tr("workspace.pipeline.drawer.enabled", "Enabled"),
            "pipeline.activity.title": self._tr("workspace.pipeline.activity.title", "Runtime"),
            "pipeline.activity.idle": self._tr("workspace.pipeline.activity.idle", "Idle"),
            "pipeline.activity.plugin_prefix": self._tr(
                "workspace.pipeline.activity.plugin_prefix",
                "Plugin:",
            ),
            "history.title": self._tr("workspace.history.title", "History"),
            "history.rename": self._tr("workspace.history.rename", "Rename"),
            "history.rerun": self._tr("workspace.history.rerun", "Rerun"),
            "history.export": self._tr("workspace.history.export", "Export"),
            "history.delete": self._tr("workspace.history.delete", "Delete"),
            "history.rename_tip": self._tr("workspace.history.rename_tip", "Rename meeting"),
            "history.rerun_tip": self._tr("workspace.history.rerun_tip", "Run again from a selected stage"),
            "history.export_tip": self._tr("workspace.history.export_tip", "Export meeting artifacts"),
            "history.rerun_disabled_no_source": self._tr(
                "workspace.history.rerun_disabled_no_source",
                "No source file to rerun",
            ),
            "history.actions_disabled": self._tr("workspace.history.actions_disabled", "Meeting key is missing"),
            "history.status.raw": self._tr("workspace.history.status.raw", "New"),
            "history.status.processing": self._tr("workspace.history.status.processing", "Processing"),
            "history.status.failed": self._tr("workspace.history.status.failed", "Failed"),
            "history.status.cancelled": self._tr("workspace.history.status.cancelled", "Cancelled"),
            "history.status.completed": self._tr("workspace.history.status.completed", "Completed"),
            "artifacts.title": self._tr("workspace.artifacts.title", "Artifacts"),
            "inspection.title": self._tr("workspace.inspection.title", "Text Inspection"),
            "inspection.empty": self._tr("workspace.inspection.empty", "Select a text version to inspect lineage."),
            "search.button": self._tr("workspace.search.button", "Search"),
            "search.prev": self._tr("workspace.search.prev", "Prev"),
            "search.next": self._tr("workspace.search.next", "Next"),
            "search.clear": self._tr("workspace.search.clear", "Clear"),
            "search.logs": self._tr("workspace.search.logs", "Logs"),
            "search.copy": self._tr("workspace.search.copy", "Copy"),
            "search.export": self._tr("workspace.search.export", "Export"),
            "search.export_target": self._tr("workspace.search.export_target", "Target"),
            "search.placeholder.local": self._tr("workspace.search.placeholder.local", "Search in text..."),
            "search.placeholder.global": self._tr("workspace.search.placeholder.global", "Search across meetings..."),
            "search.mode.local": self._tr("workspace.search.mode.local", "In document"),
            "search.mode.global": self._tr("workspace.search.mode.global", "Everywhere"),
            "search.tab.results": self._tr("workspace.search.tab.results", "Search Results"),
            "search.tab.text": self._tr("workspace.search.tab.text", "Text"),
            "search.matches.none": self._tr("workspace.search.matches.none", "0 matches"),
            "audio.play": self._tr("workspace.audio.play", "Play"),
            "audio.pause": self._tr("workspace.audio.pause", "Pause"),
            "audio.stop": self._tr("workspace.audio.stop", "Stop"),
            "dialog.logs.title": self._tr("workspace.dialog.logs.title", "Logs"),
            "dialog.logs.copy": self._tr("workspace.dialog.logs.copy", "Copy"),
            "kind.transcript": self._tr("workspace.kind.transcript", "Transcript"),
            "kind.edited": self._tr("workspace.kind.edited", "Edited"),
            "kind.summary": self._tr("workspace.kind.summary", "Summary"),
            "transcript.menu.create_task": self._tr(
                "workspace.transcript.menu.create_task", "Create task from selection"
            ),
            "transcript.menu.create_project": self._tr(
                "workspace.transcript.menu.create_project", "Create project from selection"
            ),
            "transcript.menu.create_agenda": self._tr(
                "workspace.transcript.menu.create_agenda", "Create agenda from selection"
            ),
            "transcript.menu.approve_suggestion": self._tr(
                "workspace.transcript.menu.approve_suggestion", "Approve highlighted suggestion"
            ),
            "transcript.menu.hide_suggestion": self._tr(
                "workspace.transcript.menu.hide_suggestion", "Hide highlighted suggestion"
            ),
            "transcript.menu.create_task_highlight": self._tr(
                "workspace.transcript.menu.create_task_highlight", "Create task from highlight"
            ),
            "transcript.menu.create_project_highlight": self._tr(
                "workspace.transcript.menu.create_project_highlight", "Create project from highlight"
            ),
            "transcript.menu.create_agenda_highlight": self._tr(
                "workspace.transcript.menu.create_agenda_highlight", "Create agenda from highlight"
            ),
        }
        self._workspace.set_ui_labels(labels)

    def refresh_locale(self) -> None:
        # Re-resolve active locale and repaint workspace labels without app restart.
        self._i18n = UiI18n(self._app_root, namespace="meetings")
        self._apply_workspace_labels()
        self._refresh_pipeline_ui()
        self._refresh_history(select_base_name=self._active_meeting_base_name)
        self._refresh_global_search_ui()

    def shutdown(self) -> None:
        self._pipeline_runner.shutdown()
        self._safe_stop_component("_startup_prewarm_timer")
        self._safe_stop_component("_history_refresh_timer")
        self._safe_stop_component("_registry_watch")
        self._action_service.shutdown()
        self._artifact_service.close()

    def _safe_stop_component(self, attr_name: str) -> None:
        if not hasattr(self, attr_name):
            return
        component = getattr(self, attr_name, None)
        if component is None:
            return
        try:
            component.stop()
        except RuntimeError as exc:
            _LOG.debug("meetings_tab_shutdown_stop_failed attr=%s error=%s", attr_name, exc)

    def _pipeline_configured_plugin_ids(self) -> list[str]:
        stages = self._config_data.get("stages", {})
        pipeline = self._config_data.get("pipeline", {})
        disabled_stages = pipeline.get("disabled_stages", []) if isinstance(pipeline, dict) else []
        disabled = {str(item or "").strip() for item in (disabled_stages or []) if str(item or "").strip()}
        if not isinstance(stages, dict):
            return []

        selected: list[str] = []
        seen: set[str] = set()

        def _push(plugin_id: str) -> None:
            pid = str(plugin_id or "").strip()
            if not pid or pid in seen:
                return
            if not self._plugin_enabled_for_config(pid):
                return
            seen.add(pid)
            selected.append(pid)

        for stage_id, payload in stages.items():
            sid = str(stage_id or "").strip()
            if not sid or sid in disabled or not isinstance(payload, dict):
                continue
            _push(str(payload.get("plugin_id", "") or ""))

            plugin_ids = payload.get("plugin_ids")
            if isinstance(plugin_ids, list):
                for item in plugin_ids:
                    _push(str(item or ""))

            variants = payload.get("variants")
            if isinstance(variants, list):
                for entry in variants:
                    if not isinstance(entry, dict):
                        continue
                    _push(str(entry.get("plugin_id", "") or ""))
        return selected

    def _startup_prewarm_plugin_ids(self) -> list[str]:
        selected = list(self._pipeline_configured_plugin_ids())
        seen = {str(item or "").strip() for item in selected if str(item or "").strip()}
        try:
            enabled_plugins = list(self._get_catalog().enabled_plugins())
        except (AttributeError, OSError, RuntimeError, ValueError):
            enabled_plugins = []
        for plugin in enabled_plugins:
            pid = str(getattr(plugin, "plugin_id", "") or "").strip()
            if not pid or pid in seen:
                continue
            if not self._plugin_enabled_for_config(pid):
                continue
            caps = self._plugin_capabilities(pid)
            start_action = str(
                _cap_get(caps, "health", "server", "auto_start_action", default="") or ""
            ).strip()
            if not start_action:
                continue
            settings = self._settings_store.get_settings(pid, include_secrets=True)
            if not _coerce_bool(settings.get("auto_start_server", True)):
                continue
            seen.add(pid)
            selected.append(pid)
        return selected

    @staticmethod
    def _action_result_status_message(result: object) -> tuple[str, str]:
        if isinstance(result, dict):
            status = str(result.get("status", "") or "").strip().lower()
            message = str(result.get("message", "") or "").strip()
            return status, message
        status = str(getattr(result, "status", "") or "").strip().lower()
        message = str(getattr(result, "message", "") or "").strip()
        return status, message

    @staticmethod
    def _run_with_timeout(
        fn,
        *,
        timeout_seconds: int,
        thread_name: str,
    ) -> tuple[bool, object | None, str, bool]:
        done = threading.Event()
        holder: dict[str, object] = {"result": None, "error": None}

        def _target() -> None:
            try:
                holder["result"] = fn()
            except _EXPECTED_PLUGIN_RUNTIME_ERRORS as exc:
                _LOG.debug("run_with_timeout_worker_failed thread_name=%s error=%s", thread_name, exc)
                holder["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(target=_target, name=thread_name, daemon=True)
        worker.start()
        if not done.wait(max(1, int(timeout_seconds))):
            return False, None, f"timeout_after_{int(timeout_seconds)}s", True
        error = holder.get("error")
        if error is not None:
            return False, None, str(error), False
        return True, holder.get("result"), "", False

    @staticmethod
    def _append_note(existing: str, extra: str) -> str:
        base = str(existing or "").strip()
        addon = str(extra or "").strip()
        if not addon:
            return base
        if not base:
            return addon
        if addon in base:
            return base
        return f"{base}; {addon}"

    def _maybe_run_startup_provider_prewarm(self) -> None:
        if self._startup_prewarm_started:
            return
        self._startup_prewarm_started = True
        self._start_startup_provider_prewarm()

    def _start_startup_provider_prewarm(self) -> None:
        targets = self._startup_prewarm_plugin_ids()
        if not targets:
            return
        with self._startup_prewarm_lock:
            if bool(self._startup_prewarm_job.get("running", False)):
                return
            self._startup_prewarm_job = {
                "running": True,
                "done": False,
                "results": [],
                "error": "",
                "thread": None,
            }

        def _run() -> None:
            results: list[dict[str, object]] = []
            error_text = ""
            try:
                for plugin_id in targets:
                    plugin_started = time.perf_counter()
                    row: dict[str, object] = {
                        "plugin_id": plugin_id,
                        "server": "skip",
                        "models": "skip",
                        "health": "skip",
                        "note": "",
                        "timed_out_steps": [],
                        "elapsed_ms": 0,
                    }
                    settings = self._settings_store.get_settings(plugin_id, include_secrets=True)
                    caps = self._plugin_capabilities(plugin_id)
                    models_caps = _cap_get(caps, "models", default={})
                    model_list_action = str(
                        _cap_get(caps, "model_management", "list_models_action", default="") or ""
                    ).strip()
                    supports_model_refresh = bool(model_list_action) or (
                        isinstance(models_caps, dict) and bool(models_caps)
                    )
                    health_caps = _cap_get(caps, "health", default={})
                    supports_health_check = isinstance(health_caps, dict) and bool(health_caps)
                    start_action = str(
                        _cap_get(caps, "health", "server", "auto_start_action", default="") or ""
                    ).strip()
                    auto_start_enabled = _coerce_bool(settings.get("auto_start_server", True))
                    timeout_raw = settings.get("startup_timeout_seconds", settings.get("timeout_seconds", 45))
                    try:
                        timeout_seconds = int(timeout_raw)
                    except (TypeError, ValueError):
                        timeout_seconds = 45
                    timeout_seconds = max(5, min(timeout_seconds, 180))
                    server_timeout_seconds = max(8, min(timeout_seconds + 10, 210))
                    models_timeout_seconds = max(15, min(timeout_seconds, 90))
                    health_timeout_seconds = max(15, min(timeout_seconds, 90))

                    if start_action and auto_start_enabled:
                        ok_call, result, call_error, timed_out = self._run_with_timeout(
                            lambda _pid=plugin_id, _aid=start_action, _timeout=timeout_seconds: self._action_service.invoke_action(
                                _pid,
                                _aid,
                                {"timeout_seconds": _timeout},
                            ),
                            timeout_seconds=server_timeout_seconds,
                            thread_name=f"aimn.prewarm.server.{plugin_id}",
                        )
                        if timed_out:
                            row["server"] = "timeout"
                            row["timed_out_steps"] = list(row.get("timed_out_steps", []) or []) + ["server"]
                            row["note"] = self._append_note(
                                str(row.get("note", "") or ""),
                                f"server_start_timeout({server_timeout_seconds}s)",
                            )
                        elif ok_call:
                            status, message = self._action_result_status_message(result)
                            if status in {"ok", "success", "accepted"}:
                                row["server"] = "ok"
                            else:
                                row["server"] = "error"
                                row["note"] = message or "server_start_failed"
                        else:
                            row["server"] = "error"
                            row["note"] = self._append_note(
                                str(row.get("note", "") or ""),
                                str(call_error or "server_start_failed"),
                            )
                    elif start_action:
                        row["server"] = "disabled"

                    if supports_model_refresh:
                        ok_call, models_result, models_error, models_timed_out = self._run_with_timeout(
                            lambda _pid=plugin_id: self._model_catalog_controller.refresh_models_from_provider(_pid),
                            timeout_seconds=models_timeout_seconds,
                            thread_name=f"aimn.prewarm.models.{plugin_id}",
                        )
                        if models_timed_out:
                            row["models"] = "timeout"
                            row["timed_out_steps"] = list(row.get("timed_out_steps", []) or []) + ["models"]
                            row["note"] = self._append_note(
                                str(row.get("note", "") or ""),
                                f"models_refresh_timeout({models_timeout_seconds}s)",
                            )
                        elif ok_call:
                            ok_models = False
                            models_message = ""
                            if isinstance(models_result, tuple) and len(models_result) >= 2:
                                ok_models = bool(models_result[0])
                                models_message = str(models_result[1] or "")
                            row["models"] = "ok" if ok_models else "skip"
                            if not ok_models and not str(row.get("note", "")).strip():
                                if models_message and models_message not in {"provider_list_models_failed"}:
                                    row["note"] = models_message
                        else:
                            row["models"] = "error"
                            row["note"] = self._append_note(
                                str(row.get("note", "") or ""),
                                str(models_error or "models_refresh_failed"),
                            )
                    else:
                        row["models"] = "skip"

                    if supports_health_check:
                        ok_call, health_result, health_error, health_timed_out = self._run_with_timeout(
                            lambda _pid=plugin_id: self._health_service.check_plugin(
                                _pid,
                                full_check=False,
                                force=False,
                                max_age_seconds=300.0,
                                allow_disabled=False,
                                allow_stale_on_error=True,
                            ),
                            timeout_seconds=health_timeout_seconds,
                            thread_name=f"aimn.prewarm.health.{plugin_id}",
                        )
                        if health_timed_out:
                            row["health"] = "timeout"
                            row["timed_out_steps"] = list(row.get("timed_out_steps", []) or []) + ["health"]
                            row["note"] = self._append_note(
                                str(row.get("note", "") or ""),
                                f"health_check_timeout({health_timeout_seconds}s)",
                            )
                        elif ok_call:
                            report = health_result
                            if isinstance(report, PluginHealthReport) and report.healthy:
                                row["health"] = "ok"
                            elif isinstance(report, PluginHealthReport):
                                row["health"] = "issues"
                                if not str(row.get("note", "")).strip() and report.issues:
                                    row["note"] = str(report.issues[0].summary or "").strip()
                            else:
                                row["health"] = "error"
                                row["note"] = self._append_note(
                                    str(row.get("note", "") or ""),
                                    "invalid_health_report",
                                )
                        else:
                            row["health"] = "error"
                            row["note"] = self._append_note(
                                str(row.get("note", "") or ""),
                                str(health_error or "health_check_failed"),
                            )
                    else:
                        row["health"] = "skip"

                    row["elapsed_ms"] = int(max(0.0, (time.perf_counter() - plugin_started) * 1000.0))
                    if int(row.get("elapsed_ms", 0) or 0) >= 1200:
                        _LOG.warning(
                            "slow_ui_path startup_prewarm.plugin: plugin_id=%s, elapsed_ms=%s, server=%s, models=%s, health=%s",
                            plugin_id,
                            row.get("elapsed_ms", 0),
                            row.get("server", "skip"),
                            row.get("models", "skip"),
                            row.get("health", "skip"),
                        )

                    results.append(row)
            except _EXPECTED_PLUGIN_RUNTIME_ERRORS as exc:
                _LOG.warning("startup_prewarm_failed plugin_count=%s error=%s", len(targets), exc)
                error_text = str(exc)
            with self._startup_prewarm_lock:
                self._startup_prewarm_job["results"] = list(results)
                self._startup_prewarm_job["error"] = error_text
                self._startup_prewarm_job["done"] = True

        thread = threading.Thread(target=_run, name="aimn.startup_prewarm", daemon=True)
        with self._startup_prewarm_lock:
            self._startup_prewarm_job["thread"] = thread
        if not self._startup_prewarm_timer.isActive():
            self._startup_prewarm_timer.start()
        thread.start()

    def _poll_startup_provider_prewarm(self) -> None:
        with self._startup_prewarm_lock:
            running = bool(self._startup_prewarm_job.get("running", False))
            done = bool(self._startup_prewarm_job.get("done", False))
            rows = list(self._startup_prewarm_job.get("results", []) or [])
            error_text = str(self._startup_prewarm_job.get("error", "") or "").strip()
        if not running:
            if self._startup_prewarm_timer.isActive():
                self._startup_prewarm_timer.stop()
            return
        if not done:
            return

        with self._startup_prewarm_lock:
            self._startup_prewarm_job["running"] = False
        if self._startup_prewarm_timer.isActive():
            self._startup_prewarm_timer.stop()

        if error_text:
            self._log_service.append_message(
                self._fmt(
                    "log.startup_prewarm_failed",
                    "Startup provider prewarm failed: {error}",
                    error=error_text,
                ),
                stage_id="ui",
            )
        elif rows:
            self._log_service.append_message(
                self._fmt(
                    "log.startup_prewarm_done",
                    "Startup provider prewarm completed for {count} plugin(s).",
                    count=len(rows),
                ),
                stage_id="ui",
            )
        for row in rows:
            pid = str(row.get("plugin_id", "") or "").strip()
            if not pid:
                continue
            timed_out_steps = [
                str(step or "").strip()
                for step in list(row.get("timed_out_steps", []) or [])
                if str(step or "").strip()
            ]
            timeouts_tail = f", timeouts={','.join(timed_out_steps)}" if timed_out_steps else ""
            elapsed_ms = int(row.get("elapsed_ms", 0) or 0)
            self._log_service.append_message(
                self._fmt(
                    "log.startup_prewarm_row",
                    "Prewarm {plugin}: server={server}, models={models}, health={health}, elapsed={elapsed_ms}ms{timeouts}{note}",
                    plugin=self._plugin_display_name(pid),
                    server=str(row.get("server", "skip") or "skip"),
                    models=str(row.get("models", "skip") or "skip"),
                    health=str(row.get("health", "skip") or "skip"),
                    elapsed_ms=elapsed_ms,
                    timeouts=timeouts_tail,
                    note=(f", note={str(row.get('note', '') or '').strip()}" if str(row.get("note", "") or "").strip() else ""),
                ),
                stage_id="ui",
            )
            if timed_out_steps:
                _LOG.warning(
                    "startup_prewarm_timeout plugin_id=%s timed_out_steps=%s elapsed_ms=%s",
                    pid,
                    ",".join(timed_out_steps),
                    elapsed_ms,
                )

        self._request_pipeline_ui_refresh(immediate=True)

    # ---- Pipeline settings service hooks ----

    def _selected_plugin_id(self, stage_id: str) -> str:
        return self._stage_plugin_config_controller.selected_plugin_id(stage_id)

    def _get_catalog(self):
        return self._catalog_service.load().catalog

    def _plugin_capabilities(self, plugin_id: str) -> dict:
        return self._plugin_capabilities_controller.plugin_capabilities(plugin_id)

    def _refresh_artifact_export_targets(self) -> None:
        self._text_panel.set_artifact_export_targets(self._artifact_export_targets())

    def _artifact_export_targets(self) -> list[dict[str, str]]:
        return self._integration_export_targets(action_keys=("manual_text_action", "manual_action"))

    def _meeting_export_targets(self) -> list[dict[str, str]]:
        return self._integration_export_targets(action_keys=("meeting_action",))

    def _integration_export_targets(self, *, action_keys: tuple[str, ...]) -> list[dict[str, str]]:
        return self._plugin_capabilities_controller.integration_export_targets(action_keys=action_keys)

    def _capability_bool(self, plugin_id: str, *keys: str, default: bool = False) -> bool:
        return self._plugin_capabilities_controller.capability_bool(
            plugin_id, *keys, default=default
        )

    def _capability_int(self, plugin_id: str, *keys: str, default: int = 100) -> int:
        return self._plugin_capabilities_controller.capability_int(
            plugin_id, *keys, default=default
        )

    def _is_transcription_local_plugin(self, plugin_id: str) -> bool:
        return self._stage_plugin_config_controller.is_transcription_local_plugin(plugin_id)

    def _supports_transcription_quality_presets(self, plugin_id: str) -> bool:
        return self._stage_plugin_config_controller.supports_transcription_quality_presets(plugin_id)

    def _transcription_provider_order(self, plugin_id: str) -> int:
        return self._stage_plugin_config_controller.transcription_provider_order(plugin_id)

    def _order_transcription_providers(
        self, providers: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        return self._stage_plugin_config_controller.order_transcription_providers(providers)

    def _text_processing_provider_group(self, plugin_id: str) -> str:
        return self._stage_plugin_config_controller.text_processing_provider_group(plugin_id)

    def _first_transcription_local_plugin_id(self) -> str:
        return self._stage_plugin_config_controller.first_transcription_local_plugin_id()

    def _stage_plugin_options(self, stage_id: str) -> list[tuple[str, str]]:
        return self._stage_plugin_config_controller.stage_plugin_options(stage_id)

    def _stage_defaults(self, stage_id: str) -> dict[str, object]:
        return self._stage_plugin_config_controller.stage_defaults(stage_id)

    def _build_custom_panel(self, stage_id: str, parent: QWidget | None) -> QWidget | None:
        if stage_id == "transcription":
            return TranscriptionPanel(parent=parent)
        if stage_id == "text_processing":
            return TextProcessingGroupedPanel(parent=parent)
        if stage_id == "llm_processing":
            return AiProcessingPanel(parent=parent)
        return None

    # ---- UI wiring ----

    def _refresh_history(self, *, select_base_name: str = "", immediate: bool = False) -> None:
        base = str(select_base_name or "").strip()
        if base:
            self._history_refresh_pending_select_base = base
        if bool(immediate):
            if self._history_refresh_timer.isActive():
                self._history_refresh_timer.stop()
            self._flush_deferred_history_refresh()
            return
        if not self._history_refresh_timer.isActive():
            self._history_refresh_timer.start()

    def _flush_deferred_history_refresh(self) -> None:
        pending = str(self._history_refresh_pending_select_base or "").strip()
        self._history_refresh_pending_select_base = ""
        self._refresh_history_async(select_base_name=pending)

    def _refresh_active_meeting(self, *, base_name: str = "", immediate: bool = False) -> None:
        base = str(base_name or self._active_meeting_base_name or "").strip()
        if not base:
            return
        self._active_meeting_refresh_pending_base = base
        if bool(immediate):
            if self._active_meeting_refresh_timer.isActive():
                self._active_meeting_refresh_timer.stop()
            self._flush_deferred_active_meeting_refresh()
            return
        if not self._active_meeting_refresh_timer.isActive():
            self._active_meeting_refresh_timer.start()

    def _flush_deferred_active_meeting_refresh(self) -> None:
        base = str(self._active_meeting_refresh_pending_base or "").strip()
        self._active_meeting_refresh_pending_base = ""
        if not base:
            return
        self._refresh_active_meeting_async(base_name=base)

    def _refresh_active_meeting_async(self, *, base_name: str) -> None:
        base = str(base_name or "").strip()
        if not base:
            return
        perf_started = time.perf_counter()
        request_id = int(self._active_meeting_refresh_request_id + 1)
        self._active_meeting_refresh_request_id = request_id
        all_meetings_snapshot = list(self._all_meetings)

        def _worker() -> dict[str, object]:
            return self._meeting_selection_controller.load_selection_payload(
                base_name=base,
                load_meeting=lambda item: self._artifact_service.load_meeting(item),
                list_artifacts=lambda meeting, include_internal: self._artifact_service.list_artifacts(
                    meeting,
                    include_internal=include_internal,
                ),
                load_management_suggestions=self._load_management_suggestions_for_meeting,
                all_meetings=all_meetings_snapshot,
                stage_order=list(PIPELINE_STAGE_ORDER),
            )

        def _on_finished(done_request_id: int, payload_data: object) -> None:
            if int(done_request_id) != int(self._active_meeting_refresh_request_id):
                return
            if str(self._active_meeting_base_name or "").strip() != base:
                return
            data = payload_data if isinstance(payload_data, dict) else {}
            if data.get("meeting") is not None:
                self._meeting_payload_cache[base] = dict(data)
            self._apply_meeting_selection_payload(
                base,
                data,
                perf_started=perf_started,
                metric_name="_refresh_active_meeting",
            )
            self._restore_selected_artifact()

        def _on_error(done_request_id: int, error: Exception) -> None:
            if int(done_request_id) != int(self._active_meeting_refresh_request_id):
                return
            if str(self._active_meeting_base_name or "").strip() != base:
                return
            _LOG.warning("active_meeting_refresh_async_failed base=%s error=%s", base, error)

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _refresh_history_async(self, *, select_base_name: str = "") -> None:
        perf_started = time.perf_counter()
        current_selection = ""
        if not select_base_name:
            try:
                current_selection = self._history_panel.selected_base_name()
            except RuntimeError:
                current_selection = ""
        request_id = int(self._history_refresh_request_id + 1)
        self._history_refresh_request_id = request_id
        global_query = str(self._global_search_controller.query or "").strip()
        global_meeting_ids = set(self._global_search_controller.meeting_ids)
        meta_cache_snapshot = self._meeting_history.meta_cache_snapshot()

        def _worker() -> dict[str, object]:
            meetings = list(self._artifact_service.list_meetings())
            payload = MeetingHistoryRefreshController.build_payload(
                meetings=meetings,
                output_dir=self._paths.output_dir,
                meta_cache_snapshot=meta_cache_snapshot,
                global_query=global_query,
                global_meeting_ids=global_meeting_ids,
                select_base_name=select_base_name,
                current_selection=current_selection,
            )
            return {
                "meetings": payload.meetings,
                "visible_meetings": payload.visible_meetings,
                "known_bases": payload.known_bases,
                "pending_files": payload.pending_files,
                "desired_base": payload.desired_base,
                "fallback_first_base": payload.fallback_first_base,
                "meta_cache": payload.meta_cache,
            }

        def _on_finished(done_request_id: int, payload: object) -> None:
            if int(done_request_id) != int(self._history_refresh_request_id):
                return
            data = payload if isinstance(payload, dict) else {}
            self._apply_history_refresh_payload(data, perf_started=perf_started)

        def _on_error(done_request_id: int, error: Exception) -> None:
            if int(done_request_id) != int(self._history_refresh_request_id):
                return
            _LOG.exception("history_refresh_async_failed")
            self._log_service.append_message(f"History refresh failed: {error}", stage_id="ui")
            self._emit_slow_path_log(
                name="_refresh_history.error",
                started_at=perf_started,
                threshold_ms=_PERF_WARN_REFRESH_HISTORY_MS,
                details={},
            )

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _apply_history_refresh_payload(self, payload: dict[str, object], *, perf_started: float) -> None:
        applied = MeetingHistoryRefreshController.apply_payload(
            payload,
            meeting_history=self._meeting_history,
            meeting_payload_cache=self._meeting_payload_cache,
            ad_hoc_input_files=self._ad_hoc_input_files,
        )
        self._all_meetings = list(applied.all_meetings)
        self._meeting_payload_cache = dict(applied.meeting_payload_cache)
        self._ad_hoc_input_files = list(applied.ad_hoc_input_files)
        self._input_files = list(applied.input_files)
        self._history_panel.set_meetings(list(applied.visible_meetings))
        if applied.select_base_name:
            self._history_panel.select_by_base_name(applied.select_base_name)

        self._emit_slow_path_log(
            name="_refresh_history",
            started_at=perf_started,
            threshold_ms=_PERF_WARN_REFRESH_HISTORY_MS,
            details={"meetings": len(applied.visible_meetings)},
        )


    @staticmethod
    def _meeting_primary_path(meeting: object) -> str:
        return MeetingHistoryController.meeting_primary_path(meeting)

    def _active_meeting_path(self) -> str:
        return self._meeting_history.active_meeting_path(
            base_name=self._active_meeting_base_name,
            loader=lambda base: self._artifact_service.load_meeting(base),
        )

    def _invalidate_meeting_payload_cache(self, base_name: str = "") -> None:
        base = str(base_name or "").strip()
        if not base:
            self._meeting_payload_cache.clear()
            return
        self._meeting_payload_cache.pop(base, None)

    def _active_meeting_status(self) -> str:
        return self._meeting_history.active_meeting_status(
            base_name=self._active_meeting_base_name,
            loader=lambda base: self._artifact_service.load_meeting(base),
        )

    def _pending_files_from_meetings(self, meetings: list[object]) -> list[str]:
        return self._meeting_history.pending_files_from_meetings(meetings)

    def _enrich_history_meta(self, meeting: object) -> None:
        self._meeting_history.enrich_history_meta(meeting, output_dir=self._paths.output_dir)

    def _set_meeting_status(self, meeting: object, status: str, *, error: str = "") -> None:
        self._meeting_history.set_meeting_status(
            meeting,
            status,
            error=error,
            touch_updated=self._meeting_service.touch_updated,
        )

    def _default_rerun_stage(self) -> str:
        return self._meeting_actions_controller.default_rerun_stage(
            list(PIPELINE_STAGE_ORDER),
            self._is_stage_disabled,
        )

    def apply_path_preferences(self, payload: dict[str, object] | None = None) -> None:
        settings = payload if isinstance(payload, dict) else self._settings_store.get_settings(
            _UI_PATH_PREFERENCES_SETTINGS_ID,
            include_secrets=False,
        )
        if not isinstance(settings, dict):
            settings = {}
        input_dir = str(settings.get("default_input_dir", "") or "").strip()
        if not input_dir:
            input_dir = str(get_default_input_dir(self._app_root) or "")
        monitor_enabled = bool(settings.get("monitor_input_dir", False))
        if not settings:
            monitor_enabled = bool(is_input_monitoring_enabled(self._app_root))

        self._pipeline_panel.set_default_input_dir(input_dir)
        self._monitor_input_dir = input_dir
        self._monitor_input_enabled = bool(monitor_enabled and input_dir)
        self._monitored_file_signatures = set()
        if self._monitor_input_enabled:
            self._input_monitor_timer.start()
            self._poll_monitored_input_dir()
            return
        if self._input_monitor_timer.isActive():
            self._input_monitor_timer.stop()

    def _poll_monitored_input_dir(self) -> None:
        if not self._monitor_input_enabled:
            return
        root = Path(self._monitor_input_dir)
        discovered, current_signatures = PipelineInputController.discover_monitored_files(
            root,
            previous_signatures=self._monitored_file_signatures,
            monitored_extensions=_MONITORED_MEDIA_EXTENSIONS,
        )
        self._monitored_file_signatures = current_signatures
        if discovered:
            self._on_files_added(discovered)
            if not self._pipeline_runner.is_running():
                self._start_pipeline(files_override=discovered)
        self._start_monitored_pending_files_if_idle(root)

    def _start_monitored_pending_files_if_idle(self, monitored_root: Path) -> None:
        if self._pipeline_runner.is_running():
            return
        unique_files = PipelineInputController.pending_monitored_files(
            list(self._all_meetings),
            monitored_root=monitored_root,
            resolve_meeting_primary_path=self._meeting_primary_path,
        )
        if not unique_files:
            return
        self._start_pipeline(files_override=unique_files)

    def _on_files_added(self, files: list[str]) -> None:
        paths = PipelineInputController.normalize_input_paths(files)
        self._ad_hoc_input_files = list(paths)
        if not paths:
            self._input_files = []
            self._active_meeting_base_name = ""
            return
        # Release any audio handle before meeting discovery to avoid WinError 32 on rename.
        try:
            self._text_panel.set_audio_path("")
        except RuntimeError as exc:
            _LOG.debug("clear_audio_path_before_meeting_discovery_failed error=%s", exc)
        result = PipelineInputController.ingest_files(
            paths,
            load_or_create_meeting=self._meeting_service.load_or_create,
            save_meeting=self._meeting_service.save,
            set_meeting_status=lambda meeting, status: self._set_meeting_status(meeting, status, error=""),
        )
        for failure in result.load_failures:
            self._log_service.append_message(
                self._fmt(
                    "log.meeting_load_failed",
                    "Meeting load failed for {path}: {error}",
                    path=failure.path,
                    error=failure.error,
                )
            )
        for base_name in result.reset_runtime_base_names:
            try:
                self._stage_runtime.clear_meeting_states(str(base_name or ""))
            except RuntimeError as exc:
                _LOG.debug("clear_runtime_state_for_ingested_meeting_failed base=%s error=%s", base_name, exc)
        if result.added_base_names:
            self._refresh_history(select_base_name=result.added_base_names[-1])
            self._refresh_pipeline_ui()
        else:
            # Nothing valid was added; avoid accidentally re-running
            # a previously selected meeting.
            self._active_meeting_base_name = ""
            self._input_files = list(self._ad_hoc_input_files)
            self._refresh_history()
            self._refresh_pipeline_ui()

    def _on_file_started(self, _file_path: str, base_name: str) -> None:
        self._last_stage_base_name = str(base_name or "")
        if self._last_stage_base_name:
            self._stage_states_for(self._last_stage_base_name)
            self._invalidate_meeting_payload_cache(self._last_stage_base_name)
        self._refresh_history()
        self._refresh_pipeline_ui()

    def _on_file_completed(self, _file_path: str, base_name: str) -> None:
        self._invalidate_meeting_payload_cache(base_name)
        self._finalize_meeting_status(base_name)
        self._reload_active_meeting_manifest(base_name)
        # A completed meeting must not keep "running" stage tiles even if the pipeline
        # didn't emit a final stage_finished event (or it arrives later).
        if str(base_name or "").strip():
            self._stage_runtime.mark_running_completed(base_name=str(base_name))
        self._refresh_history()
        self._refresh_pipeline_ui()

    def _on_file_failed(self, _file_path: str, error: str) -> None:
        if error:
            self._log_service.append_message(str(error))
        self._invalidate_meeting_payload_cache(self._active_meeting_base_name)
        self._refresh_history()
        self._refresh_pipeline_ui()

    def _on_pause_toggled(self, paused: bool) -> None:
        if not self._pipeline_runner.is_running():
            return
        self._pipeline_paused = bool(paused)
        self._pipeline_runner.request_pause(self._pipeline_paused)
        if self._pipeline_paused:
            self._log_service.append_message(
                self._tr(
                    "log.pipeline_paused",
                    "Pipeline paused (will stop after current file).",
                )
            )
        else:
            self._log_service.append_message(self._tr("log.pipeline_resumed", "Pipeline resumed."))
        self._refresh_pipeline_ui()

    def _on_stop_clicked(self) -> None:
        if not self._pipeline_runner.is_running():
            return
        self._pipeline_paused = False
        self._pipeline_runner.request_cancel()
        self._log_service.append_message(self._tr("log.pipeline_stop_requested", "Pipeline stop requested."))
        self._refresh_pipeline_ui()

    def _resolve_meeting_base(self, meeting_key: str) -> str:
        return self._meeting_history.resolve_meeting_base(meeting_key)

    def _on_meeting_delete_requested(self, meeting_key: str) -> None:
        base = self._resolve_meeting_base(meeting_key)
        if not base:
            return

        def _clear_active_meeting() -> None:
            self._active_meeting_base_name = ""

        MeetingActionFlowController.delete_meeting(
            base,
            callbacks=MeetingDeleteFlowCallbacks(
                load_meeting=self._meeting_service.load_by_base_name,
                is_active_base=lambda candidate: self._active_meeting_base_name == candidate,
                clear_audio_path=lambda: self._text_panel.set_audio_path(""),
                confirm_delete=lambda: QMessageBox.question(
                    self,
                    self._tr("delete.title", "Delete meeting?"),
                    self._tr("delete.message", "Delete this meeting and all related files?"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                == QMessageBox.Yes,
                cleanup_meeting_for_delete=lambda meeting_id: self._management_cleanup_controller().cleanup_meeting_for_delete(
                    meeting_id
                ),
                delete_meeting_files=self._meeting_actions_controller.delete_meeting_files,
                clear_meeting_states=self._stage_runtime.clear_meeting_states,
                invalidate_payload_cache=self._invalidate_meeting_payload_cache,
                clear_active_meeting=_clear_active_meeting,
                refresh_history=self._refresh_history,
                refresh_pipeline_ui=self._refresh_pipeline_ui,
                log_delete_preview_error=lambda meeting_base, exc: _LOG.warning(
                    "load_meeting_for_delete_preview_failed base=%s error=%s",
                    meeting_base,
                    exc,
                ),
                log_clear_audio_error=lambda meeting_base, exc: _LOG.debug(
                    "clear_audio_path_before_delete_failed base=%s error=%s",
                    meeting_base,
                    exc,
                ),
            ),
        )

    def _on_meeting_rename_requested(self, meeting_key: str) -> None:
        base = self._resolve_meeting_base(meeting_key)
        if not base:
            return

        def _set_active_meeting_base(new_base: str) -> None:
            self._active_meeting_base_name = str(new_base or "")

        def _set_last_stage_base(new_base: str) -> None:
            self._last_stage_base_name = str(new_base or "")

        MeetingActionFlowController.rename_meeting(
            base,
            callbacks=MeetingRenameFlowCallbacks(
                load_meeting=self._meeting_service.load_by_base_name,
                meeting_display_title=lambda meeting: self._meeting_actions_controller.meeting_display_title(meeting),
                meeting_topic_suggestions=lambda meeting_base, meeting: self._meeting_actions_controller.meeting_topic_suggestions(
                    meeting_base,
                    meeting=meeting,
                ),
                prompt_new_title=lambda current_title, suggestions: MeetingsTabV2._prompt_meeting_rename(
                    self,
                    current_title,
                    suggestions,
                ),
                rename_policy=lambda: self._meeting_actions_controller.meeting_rename_policy(),
                confirm_source_rename=lambda: self._meeting_actions_controller.confirm_source_rename(
                    self,
                    title=self._tr("rename.source_title", "Rename source file?"),
                    message=self._tr(
                        "rename.source_message",
                        "Rename original source file too?\n\n"
                        "This works only for files in app-managed import folders.\n"
                        "External files stay unchanged for safety.",
                    ),
                ),
                is_active_base=lambda candidate: self._active_meeting_base_name == candidate,
                is_last_stage_base=lambda candidate: self._last_stage_base_name == candidate,
                clear_audio_path=lambda: self._text_panel.set_audio_path(""),
                rename_meeting=lambda meeting_base, new_title, rename_mode, rename_source: self._meeting_service.rename_meeting(
                    meeting_base,
                    title=new_title,
                    rename_mode=rename_mode,
                    rename_source=rename_source,
                ),
                set_active_meeting_base=_set_active_meeting_base,
                set_last_stage_base=_set_last_stage_base,
                invalidate_payload_cache=lambda candidate: self._invalidate_meeting_payload_cache(candidate),
                refresh_history=lambda new_base: self._refresh_history(select_base_name=new_base),
                refresh_pipeline_ui=lambda: self._refresh_pipeline_ui(),
                warn_load_failed=lambda exc: QMessageBox.warning(
                    self,
                    self._tr("rename.error_title", "Rename failed"),
                    self._fmt("rename.error_load", "Unable to load meeting:\n{error}", error=exc),
                ),
                warn_target_exists=lambda exc: QMessageBox.warning(
                    self,
                    self._tr("rename.error_title", "Rename failed"),
                    self._fmt("rename.error_exists", "Target already exists:\n{error}", error=exc),
                ),
                warn_source_not_allowed=lambda exc: QMessageBox.warning(
                    self,
                    self._tr("rename.error_title", "Rename failed"),
                    self._fmt("rename.error_source", "Source rename is not allowed:\n{error}", error=exc),
                ),
                warn_generic=lambda exc: QMessageBox.warning(
                    self,
                    self._tr("rename.error_title", "Rename failed"),
                    str(exc),
                ),
            ),
        )

    def _prompt_meeting_rename(self, current_title: str, suggestions: list[str]) -> str:
        dialog = _MeetingRenameDialog(
            current_title=current_title,
            suggestions=suggestions,
            parent=self,
            title=self._tr("rename.dialog.title", "Rename meeting"),
            intro_text=self._tr(
                "rename.dialog.intro",
                "Pick a suggested topic or enter a custom title.",
            ),
            title_placeholder=self._tr("rename.dialog.title_placeholder", "Meeting title"),
            suggestions_placeholder=self._tr(
                "rename.dialog.suggestions_placeholder",
                "Select suggested topic",
            ),
            note_text=self._tr(
                "rename.dialog.note",
                "The title can be edited before saving.",
            ),
            save_label=self._tr("rename.dialog.save", "Save"),
        )
        if dialog.exec() != QDialog.Accepted:
            return ""
        return str(dialog.title_text() or "").strip()

    def _refresh_pipeline_ui(self) -> None:
        perf_started = time.perf_counter()
        self._active_meeting_source_path = self._active_meeting_path()
        stages = [self._build_stage_view_model(stage_id) for stage_id in PIPELINE_STAGE_ORDER]
        running = self._pipeline_runner.is_running()
        refresh_state = self._pipeline_ui_state_controller.build_refresh_state(
            stages=stages,
            pipeline_running=running,
            pipeline_paused=self._pipeline_paused,
            selected_stage_id=self._pipeline_panel.selected_stage_id(),
            config_source=str(self._config_source or ""),
            config_path=str(self._config_path or ""),
            overrides=list(self._overrides or []),
            pipeline_preset=self._pipeline_preset,
            plugin_registry=MeetingsTabV2._pipeline_registry_snapshot(self),
            active_meeting_base_name=self._active_meeting_base_name,
            active_meeting_source_path=self._active_meeting_source_path,
            active_meeting_status=self._active_meeting_status(),
            input_files=list(self._input_files),
            default_rerun_stage=self._default_rerun_stage(),
        )
        self._pipeline_panel.set_meta(refresh_state.meta)
        self._pipeline_panel.set_stages(list(refresh_state.stages))
        self._pipeline_panel.set_run_enabled(refresh_state.run_enabled)
        self._pipeline_panel.set_pause_enabled(refresh_state.pause_enabled)
        self._pipeline_panel.set_stop_enabled(refresh_state.stop_enabled)
        self._pipeline_panel.set_paused(refresh_state.paused)
        self._refresh_runtime_tile()
        # Do not re-open the drawer on every refresh: it recreates controls, causes
        # duplicated signal connections, and may trigger feedback loops.
        self._emit_slow_path_log(
            name="_refresh_pipeline_ui",
            started_at=perf_started,
            threshold_ms=_PERF_WARN_REFRESH_PIPELINE_MS,
            details={"stages": len(stages)},
        )

    def _request_pipeline_ui_refresh(self, *, immediate: bool = False) -> None:
        if bool(immediate) or not self._pipeline_runner.is_running():
            self._pipeline_refresh_pending = False
            if self._pipeline_refresh_timer.isActive():
                self._pipeline_refresh_timer.stop()
            self._refresh_pipeline_ui()
            return
        self._pipeline_refresh_pending = True
        if not self._pipeline_refresh_timer.isActive():
            self._pipeline_refresh_timer.start()

    def _flush_deferred_pipeline_refresh(self) -> None:
        if not self._pipeline_refresh_pending:
            return
        self._pipeline_refresh_pending = False
        self._refresh_pipeline_ui()

    def _pipeline_meta(self) -> str:
        return self._pipeline_ui_state_controller.pipeline_meta(
            selected_stage_id=self._pipeline_panel.selected_stage_id(),
            config_source=str(self._config_source or ""),
            config_path=str(self._config_path or ""),
            overrides=list(self._overrides or []),
            pipeline_preset=self._pipeline_preset,
            plugin_registry=MeetingsTabV2._pipeline_registry_snapshot(self),
            active_meeting_base_name=self._active_meeting_base_name,
            active_meeting_source_path=self._active_meeting_source_path,
            active_meeting_status=self._active_meeting_status(),
            input_files=list(self._input_files),
            default_rerun_stage=self._default_rerun_stage(),
        )

    def _pipeline_registry_snapshot(self) -> dict[str, str]:
        try:
            snap = self._catalog_service.load()
            return {
                "source": str(getattr(snap.registry, "source", "") or ""),
                "path": str(getattr(snap.registry, "path", "") or ""),
            }
        except (AttributeError, OSError, RuntimeError, ValueError):
            return {}

    def _can_run_pipeline(self, stages: list[StageViewModel]) -> bool:
        return self._pipeline_ui_state_controller.can_run_pipeline(
            stages=list(stages or []),
            pipeline_running=self._pipeline_runner.is_running(),
            selected_stage_id=self._pipeline_panel.selected_stage_id(),
            active_meeting_base_name=self._active_meeting_base_name,
            active_meeting_source_path=self._active_meeting_source_path,
            input_files=list(self._input_files),
        )

    def _on_stage_clicked(self, stage_id: str) -> None:
        stage = self._build_stage_view_model(stage_id)
        self._pipeline_panel.open_settings(stage)

    def _on_stage_context_requested(self, stage_id: str, global_pos) -> None:
        self._show_stage_context_menu(str(stage_id or "").strip(), global_pos)

    def _on_artifact_kind_context_requested(self, kind: str, global_pos) -> None:
        stage_id = StageArtifactNavigationController.stage_id_for_artifact_kind(kind)
        if not stage_id:
            return
        self._show_stage_context_menu(stage_id, global_pos)

    def _on_artifact_version_context_requested(
        self, stage_id: str, alias: str, kind: str, global_pos
    ) -> None:
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        artifact_kind = str(kind or "").strip()
        if not sid or not al:
            return
        meeting_id = self._active_meeting_id()
        action = self._exec_context_menu(
            MeetingContextMenuController.build_artifact_actions(
                rerun_same_label=self._tr(
                    "meetings.context.artifact.rerun_same",
                    "Regenerate this artifact (same provider/model/settings)",
                ),
                rerun_stage_label=self._tr(
                    "meetings.context.artifact.rerun_stage",
                    "Generate new artifact with current stage settings",
                ),
                cleanup_management_label=self._tr(
                    "meetings.context.artifact.cleanup_management",
                    "Clean Management suggestions/links for this artifact",
                ),
                pipeline_running=self._pipeline_runner.is_running(),
                has_active_meeting=bool(self._active_meeting_base_name),
                has_meeting_id=bool(meeting_id),
            ),
            global_pos,
        )
        if action == "rerun_same":
            self._rerun_artifact_same_settings(sid, al)
            return
        if action == "rerun_stage":
            self._rerun_stage_with_current_settings(sid)
            return
        if action == "cleanup_management":
            self._cleanup_management_for_artifact(artifact_kind, al)
            return

    def _exec_context_menu(
        self,
        specs: list[MeetingContextMenuActionSpec],
        global_pos,
    ) -> str:
        payload = [spec for spec in list(specs or []) if isinstance(spec, MeetingContextMenuActionSpec)]
        if not payload:
            return ""
        menu = QMenu(self)
        actions: dict[object, str] = {}
        for spec in payload:
            action = menu.addAction(spec.label)
            action.setEnabled(bool(spec.enabled))
            actions[action] = spec.action
        picked = menu.exec(global_pos)
        return str(actions.get(picked, "") or "")

    def _cleanup_management_for_artifact(self, artifact_kind: str, source_alias: str) -> None:
        plan = ArtifactActionFlowController.cleanup_management_for_artifact(
            artifact_kind,
            source_alias,
            meeting_id=self._active_meeting_id(),
            run_artifact_alias_cleanup=lambda meeting_id, artifact_kind, source_alias: self._management_cleanup_controller().run_artifact_alias_cleanup(
                meeting_id=meeting_id,
                artifact_kind=artifact_kind,
                source_alias=source_alias,
            ),
            fmt=self._fmt,
        )
        if not plan.should_log:
            return
        self._log_service.append_message(plan.log_message, stage_id=plan.log_stage_id)

    def _management_cleanup_controller(self) -> ManagementCleanupController:
        return ManagementCleanupController(
            app_root=self._app_root,
            parent=self,
            tr=self._tr,
            fmt=self._fmt,
        )

    def _on_artifact_text_export_requested(
        self,
        plugin_id: str,
        action_id: str,
        stage_id: str,
        alias: str,
        kind: str,
        text: str,
    ) -> None:
        outcome = self._meeting_export_controller.run_manual_artifact_export(
            plugin_id=plugin_id,
            action_id=action_id,
            stage_id=stage_id,
            alias=alias,
            artifact_kind=kind,
            text=text,
            active_meeting_base_name=self._active_meeting_base_name,
            active_meeting_id=self._active_meeting_id(),
        )
        if outcome is None:
            return
        if outcome.level == "info":
            QMessageBox.information(self, outcome.title, outcome.message)
            return
        QMessageBox.warning(self, outcome.title, outcome.message)

    def _on_transcript_management_create_requested(self, entity_type: str, payload: dict) -> bool:
        outcome = self._transcript_management_flow_controller.run_create_request(
            entity_type=entity_type,
            payload=payload,
            meeting_id=self._active_meeting_id(),
            prompt_text=self._prompt_transcript_management_text,
        )
        return self._apply_transcript_management_create_outcome(outcome)

    def _on_transcript_management_suggestion_action_requested(self, action: str, payload: dict) -> None:
        outcome = self._transcript_management_flow_controller.run_suggestion_action(
            action=action,
            payload=payload,
            meeting_id=self._active_meeting_id(),
            prompt_text=self._prompt_transcript_management_text,
        )
        create_outcome = outcome.create_outcome
        if create_outcome is not None:
            self._apply_transcript_management_create_outcome(
                create_outcome,
                refresh_suggestions=not outcome.refresh_suggestions,
            )
        if outcome.refresh_suggestions:
            self._refresh_active_management_suggestions()

    def _prompt_transcript_management_text(
        self,
        title: str,
        prompt: str,
        default_text: str,
    ) -> tuple[str, bool]:
        return QInputDialog.getText(
            self,
            str(title or ""),
            str(prompt or ""),
            text=str(default_text or ""),
        )

    def _apply_transcript_management_create_outcome(
        self,
        outcome: TranscriptManagementCreateOutcome,
        *,
        refresh_suggestions: bool = True,
    ) -> bool:
        if outcome.warning_title or outcome.warning_message:
            QMessageBox.warning(self, outcome.warning_title, outcome.warning_message)
            return False
        if not outcome.created:
            return False
        if outcome.log_message:
            self._log_service.append_message(outcome.log_message, stage_id="management")
            self._flush_logs_to_text_panel()
        if refresh_suggestions and outcome.refresh_suggestions:
            self._refresh_active_management_suggestions()
        return True

    def _show_stage_context_menu(self, stage_id: str, global_pos) -> None:
        sid = str(stage_id or "").strip()
        if not sid:
            return
        action = self._exec_context_menu(
            MeetingContextMenuController.build_stage_actions(
                rerun_label=self._tr(
                    "meetings.context.stage.rerun",
                    "Regenerate artifacts for this stage",
                ),
                pipeline_running=self._pipeline_runner.is_running(),
                has_active_meeting=bool(self._active_meeting_base_name),
            ),
            global_pos,
        )
        if action == "rerun_stage":
            self._rerun_stage_with_current_settings(sid)
            return

    def _rerun_stage_with_current_settings(self, stage_id: str) -> None:
        plan = ArtifactActionFlowController.rerun_stage_with_current_settings(
            stage_id,
            active_meeting_base_name=self._active_meeting_base_name,
            runtime_config_with_stage_enabled=self._runtime_config_with_stage_enabled,
            runtime_stage_id_for_ui=self._runtime_stage_id_for_ui,
        )
        if not plan.should_start:
            return
        self._start_pipeline(
            force_run=False,
            force_run_from=plan.force_run_from,
            base_name=plan.base_name,
            runtime_config_override=plan.runtime_config_override,
        )

    def _rerun_artifact_same_settings(self, stage_id: str, alias: str) -> None:
        plan = ArtifactActionFlowController.rerun_artifact_same_settings(
            stage_id,
            alias,
            active_meeting_base_name=self._active_meeting_base_name,
            runtime_config_for_artifact_alias=self._runtime_config_for_artifact_alias,
            fmt=self._fmt,
        )
        if not plan.should_start:
            if plan.log_message:
                self._log_service.append_message(plan.log_message, stage_id=plan.log_stage_id)
                self._flush_logs_to_text_panel()
            return
        self._start_pipeline(
            force_run=False,
            force_run_from=plan.force_run_from,
            base_name=plan.base_name,
            runtime_config_override=plan.runtime_config_override,
        )

    def _runtime_config_with_stage_enabled(self, stage_id: str) -> dict[str, object]:
        runtime = self._build_runtime_config()
        ArtifactLineageController.enable_stage_in_runtime_config(runtime, stage_id)
        return runtime

    def _runtime_config_for_artifact_alias(self, stage_id: str, alias: str) -> dict[str, object] | None:
        node = self._artifact_lineage_node(stage_id, alias)
        if node is None:
            return None
        return ArtifactLineageController.build_runtime_config_for_node(
            runtime_config=self._build_runtime_config(),
            stage_id=stage_id,
            node=node,
            sanitize_params_for_plugin=self._sanitize_params_for_plugin,
        )

    def _runtime_stage_id_for_ui(self, stage_id: str) -> str:
        return StageArtifactNavigationController.runtime_stage_id_for_ui(stage_id)

    def _artifact_lineage_node(self, stage_id: str, alias: str) -> object | None:
        resolution = ArtifactLineageController.resolve_lineage_node(
            stage_id=stage_id,
            alias=alias,
            active_meeting_manifest=self._active_meeting_manifest,
            active_meeting_base_name=self._active_meeting_base_name,
            load_meeting=self._artifact_service.load_meeting,
            log_load_error=lambda base, exc: _LOG.warning(
                "load_active_meeting_for_artifact_lookup_failed base=%s error=%s",
                base,
                exc,
            ),
        )
        if resolution.meeting is not None:
            self._active_meeting_manifest = resolution.meeting
        return resolution.node

    def _artifact_provider_id(self, stage_id: str, alias: str) -> str:
        return ArtifactLineageController.provider_id_for_node(
            self._artifact_lineage_node(stage_id, alias)
        )

    def _on_stage_artifacts_clicked(self, stage_id: str) -> None:
        plan = StageArtifactNavigationController.open_stage_artifact_plan(
            stage_id=stage_id,
            active_meeting_base_name=self._active_meeting_base_name,
            active_artifacts=self._active_artifacts,
            fmt=self._fmt,
        )
        if plan.log_message:
            self._log_service.append_message(plan.log_message)
            self._flush_logs_to_text_panel()
            return
        if not plan.select_kind:
            return
        self._text_panel.select_artifact_kind(plan.select_kind)
        self._flush_logs_to_text_panel()

    def _on_stage_settings_changed(self, stage_id: str, payload: dict) -> None:
        extra_stage_payloads = (payload or {}).get("__extra_stage_payloads__")
        normalized_payload = dict(payload or {})
        normalized_payload.pop("__extra_stage_payloads__", None)
        prev_plugin_id, plugin_id = self._stage_settings_controller.apply_stage_settings(
            self._config_data,
            stage_id=stage_id,
            payload=normalized_payload,
            supports_transcription_quality_presets=self._supports_transcription_quality_presets,
            sanitize_params_for_plugin=self._sanitize_params_for_plugin,
            get_plugin_by_id=lambda plugin_id: self._get_catalog().plugin_by_id(plugin_id),
            coerce_bool=_coerce_bool,
        )
        if isinstance(extra_stage_payloads, dict):
            for extra_stage_id, extra_payload in extra_stage_payloads.items():
                if not isinstance(extra_payload, dict):
                    continue
                self._stage_settings_controller.apply_stage_settings(
                    self._config_data,
                    stage_id=str(extra_stage_id or "").strip(),
                    payload=extra_payload,
                    supports_transcription_quality_presets=self._supports_transcription_quality_presets,
                    sanitize_params_for_plugin=self._sanitize_params_for_plugin,
                    get_plugin_by_id=lambda plugin_id: self._get_catalog().plugin_by_id(plugin_id),
                    coerce_bool=_coerce_bool,
                )

        self._save_pipeline_config()
        self._mark_dirty(stage_id)
        self._refresh_pipeline_ui()
        # IMPORTANT: Do NOT re-render the drawer on every keystroke / selection change.
        # It causes re-entrant widget destruction during signal handling (Windows access violations).
        # Re-render only when the provider/plugin changes (schema can change), and do it asynchronously.
        if (
            prev_plugin_id != plugin_id
            and self._pipeline_panel.is_settings_open()
            and self._pipeline_panel.selected_stage_id() == stage_id
        ):
            self._rerender_timer.start(0)

    def _rerender_open_drawer(self) -> None:
        stage_id = self._pipeline_panel.selected_stage_id()
        if not stage_id or not self._pipeline_panel.is_settings_open():
            return
        self._pipeline_panel.open_settings(self._build_stage_view_model(stage_id))

    def _on_stage_enabled_changed(self, stage_id: str, enabled: bool) -> None:
        self._stage_settings_controller.set_stage_enabled(
            self._config_data,
            stage_id=stage_id,
            enabled=enabled,
        )
        if str(stage_id or "").strip() == "llm_processing":
            self._stage_settings_controller.set_stage_enabled(
                self._config_data,
                stage_id="text_processing",
                enabled=enabled,
            )
        self._save_pipeline_config()
        self._mark_dirty(stage_id)
        self._refresh_pipeline_ui()

    def _on_stage_action_requested(self, stage_id: str, payload: dict) -> None:
        request = StageActionFlowController.resolve_request(stage_id, payload)
        if request is None:
            return
        if request.action == "refresh_models":
            self._refresh_provider_models(request.stage_id, request.provider_id)
            return

    def _refresh_provider_models(self, stage_id: str, plugin_id: str) -> None:
        outcome = StageActionFlowController.refresh_provider_models(
            stage_id,
            plugin_id,
            invalidate_provider_cache=self._model_catalog_controller.invalidate_provider_cache,
            refresh_models_from_provider=self._model_catalog_controller.refresh_models_from_provider,
            is_settings_open_for_stage=lambda sid: (
                self._pipeline_panel.is_settings_open() and self._pipeline_panel.selected_stage_id() == sid
            ),
            tr=self._tr,
            fmt=self._fmt,
            log_failure=lambda sid, pid, exc: _LOG.warning(
                "refresh_provider_models_failed stage_id=%s plugin_id=%s error=%s",
                sid,
                pid,
                exc,
            ),
        )
        if outcome is None or not outcome.handled:
            return
        if outcome.level == "info":
            QMessageBox.information(self, outcome.title, outcome.message)
        elif outcome.level == "warning":
            QMessageBox.warning(self, outcome.title, outcome.message)
        if outcome.rerender_drawer:
            self._rerender_timer.start(0)
        if outcome.refresh_pipeline_ui:
            self._refresh_pipeline_ui()

    def _on_meeting_selected(self, base_name: str) -> None:
        perf_started = time.perf_counter()
        selected_base = str(base_name or "").strip()
        self._active_meeting_base_name = selected_base

        payload = self._meeting_payload_cache.get(selected_base)
        if isinstance(payload, dict):
            self._apply_meeting_selection_payload(
                selected_base,
                payload,
                perf_started=perf_started,
                metric_name="_on_meeting_selected.cache_hit",
            )
            return

        request_id = int(self._meeting_select_request_id + 1)
        self._meeting_select_request_id = request_id
        all_meetings_snapshot = list(self._all_meetings)

        def _worker() -> dict[str, object]:
            return self._meeting_selection_controller.load_selection_payload(
                base_name=selected_base,
                load_meeting=lambda base: self._artifact_service.load_meeting(base),
                list_artifacts=lambda meeting, include_internal: self._artifact_service.list_artifacts(
                    meeting,
                    include_internal=include_internal,
                ),
                load_management_suggestions=self._load_management_suggestions_for_meeting,
                all_meetings=all_meetings_snapshot,
                stage_order=list(PIPELINE_STAGE_ORDER),
            )

        def _on_finished(done_request_id: int, payload_data: object) -> None:
            if int(done_request_id) != int(self._meeting_select_request_id):
                return
            if self._active_meeting_base_name != selected_base:
                return
            data = payload_data if isinstance(payload_data, dict) else {}
            if data.get("meeting") is not None:
                self._meeting_payload_cache[selected_base] = dict(data)
            self._apply_meeting_selection_payload(
                selected_base,
                data,
                perf_started=perf_started,
                metric_name="_on_meeting_selected",
            )

        def _on_error(done_request_id: int, error: Exception) -> None:
            if int(done_request_id) != int(self._meeting_select_request_id):
                return
            if self._active_meeting_base_name != selected_base:
                return
            _LOG.exception("meeting_select_async_failed")
            self._log_service.append_message(f"Meeting load failed: {error}", stage_id="ui")
            self._apply_meeting_selection_payload(
                selected_base,
                {},
                perf_started=perf_started,
                metric_name="_on_meeting_selected.error",
            )

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _apply_meeting_selection_payload(
        self,
        selected_base: str,
        payload: dict[str, object],
        *,
        perf_started: float,
        metric_name: str,
    ) -> None:
        if self._active_meeting_base_name != str(selected_base or ""):
            return

        meeting = payload.get("meeting")
        if meeting is None:
            self._active_artifacts = []
            self._active_meeting_manifest = None
            self._segments_relpaths_by_alias = {}
            self._text_panel.set_meeting_context(
                artifacts=[],
                segments_relpaths={},
                management_suggestions=[],
                pinned_aliases={},
                active_aliases={},
                preferred_kind="",
            )
            self._text_panel.set_audio_path("")
            self._inspection_panel.clear()
            self._emit_slow_path_log(
                name=f"{metric_name}.empty",
                started_at=perf_started,
                threshold_ms=_PERF_WARN_MEETING_SELECT_MS,
                details={"base_name": self._active_meeting_base_name},
            )
            return

        processing_status = str(getattr(meeting, "processing_status", "") or "").strip().lower()
        if processing_status in {"completed", "failed", "cancelled"}:
            self._stage_runtime.mark_running_completed(base_name=self._active_meeting_base_name)

        self._active_artifacts = list(payload.get("active_artifacts", []) or [])
        self._segments_relpaths_by_alias = dict(payload.get("segments_relpaths", {}) or {})
        management_suggestions = list(payload.get("management_suggestions", []) or [])
        self._text_panel.set_meeting_context(
            artifacts=self._active_artifacts,
            segments_relpaths=self._segments_relpaths_by_alias,
            management_suggestions=management_suggestions,
            pinned_aliases=payload.get("pinned_aliases", {}) or {},
            active_aliases=payload.get("active_aliases", {}) or {},
            preferred_kind=str(payload.get("preferred_kind", "") or "").strip(),
        )
        self._set_audio_from_meeting(meeting)
        self._flush_logs_to_text_panel()
        self._active_meeting_manifest = meeting
        self._apply_pending_management_navigation_if_ready(selected_base)
        if not self._active_artifacts:
            self._inspection_panel.clear()
        self._refresh_pipeline_ui()
        self._emit_slow_path_log(
            name=metric_name,
            started_at=perf_started,
            threshold_ms=_PERF_WARN_MEETING_SELECT_MS,
            details={
                "base_name": self._active_meeting_base_name,
                "artifacts": len(self._active_artifacts),
            },
        )

    def _on_meeting_rerun_requested(self, meeting_key: str) -> None:
        base = self._resolve_meeting_base(meeting_key)
        if not base:
            return
        MeetingActionFlowController.rerun_meeting(
            base,
            callbacks=MeetingRerunFlowCallbacks(
                prompt_stage=lambda: self._meeting_actions_controller.prompt_rerun_stage(
                    parent=self,
                    stage_order=list(PIPELINE_STAGE_ORDER),
                    is_stage_disabled=self._is_stage_disabled,
                    default_stage_id=self._default_rerun_stage(),
                    stage_display_name=self._stage_display_name,
                    no_stages_title=self._tr("rerun.no_stages_title", "No Stages Enabled"),
                    no_stages_message=self._tr("rerun.no_stages_message", "Enable at least one stage to rerun."),
                    dialog_title=self._tr("rerun.dialog_title", "Run from stage"),
                    description=self._tr("rerun.description", "Choose the pipeline stage to start from:"),
                    run_label=self._tr("rerun.run_button", "Run"),
                    force_replace_label=self._tr(
                        "rerun.force_replace_label",
                        "Force replace downstream artifacts",
                    ),
                    force_replace_hint=self._tr(
                        "rerun.force_replace_hint",
                        "Use this when the selected stage produced a bad result and all downstream artifacts must be rebuilt from the new output.",
                    ),
                ),
                runtime_stage_id_for_ui=self._runtime_stage_id_for_ui,
                start_pipeline=lambda force_run_from, target_base, force_run: self._start_pipeline(
                    force_run=force_run,
                    force_run_from=force_run_from,
                    base_name=target_base,
                ),
            ),
        )

    def _on_meeting_export_requested(self, meeting_key: str) -> None:
        base = self._resolve_meeting_base(meeting_key)
        if not base:
            return
        targets = self._meeting_export_targets()
        mode_labels = {
            "full": self._tr("export.meeting.mode.full", "Full import (all artifacts)"),
            "selective": self._tr(
                "export.meeting.mode.selective",
                "Selective import (configured artifact kinds)",
            ),
        }
        MeetingActionFlowController.export_meeting(
            base,
            meeting_key,
            targets=targets,
            callbacks=MeetingExportFlowCallbacks(
                warn_no_targets=lambda: QMessageBox.warning(
                    self,
                    self._tr("export.meeting.no_targets.title", "Export unavailable"),
                    self._tr(
                        "export.meeting.no_targets.message",
                        "No enabled integration plugins support meeting export.",
                    ),
                ),
                choose_target=lambda available_targets: self._prompt_meeting_export_target(available_targets),
                choose_mode=lambda: self._prompt_meeting_export_mode(mode_labels),
                run_meeting_export=lambda plugin_id, action_id, meeting_base, current_meeting_key, mode: self._meeting_export_controller.run_meeting_export(
                    plugin_id=plugin_id,
                    action_id=action_id,
                    base_name=meeting_base,
                    meeting_key=current_meeting_key,
                    mode=mode,
                ),
                show_info=lambda title, message: QMessageBox.information(self, title, message),
                show_warning=lambda title, message: QMessageBox.warning(self, title, message),
            ),
        )

    def _prompt_meeting_export_target(self, targets: list[dict[str, object]]) -> dict[str, object] | None:
        target_labels = [str(item.get("label", "") or "").strip() for item in targets]
        picked_label, ok = QInputDialog.getItem(
            self,
            self._tr("export.meeting.target.title", "Export target"),
            self._tr("export.meeting.target.label", "Select export destination:"),
            target_labels,
            0,
            False,
        )
        if not ok:
            return None
        return next(
            (item for item in targets if str(item.get("label", "") or "").strip() == str(picked_label)),
            targets[0] if targets else None,
        )

    def _prompt_meeting_export_mode(self, mode_labels: dict[str, str]) -> str:
        labels = [
            str(mode_labels.get("full", "") or "").strip(),
            str(mode_labels.get("selective", "") or "").strip(),
        ]
        mode_label, ok = QInputDialog.getItem(
            self,
            self._tr("export.meeting.mode.title", "Export mode"),
            self._tr("export.meeting.mode.label", "Choose export mode:"),
            labels,
            0,
            False,
        )
        if not ok:
            return ""
        return "selective" if mode_label == labels[1] else "full"

    # ---- Global search ----

    def _refresh_global_search_ui(self) -> None:
        self._global_search_controller.refresh_global_search_ui()

    def _poll_registry(self) -> None:
        self._global_search_controller.poll_registry()
        MeetingsTabV2._start_registry_stamp_poll(self)

    def _start_registry_stamp_poll(self) -> None:
        if bool(getattr(self, "_registry_poll_running", False)):
            self._registry_poll_pending = True
            return
        request_id = int(getattr(self, "_registry_poll_request_id", 0) + 1)
        self._registry_poll_request_id = request_id
        self._registry_poll_running = True
        perf_started = time.perf_counter()

        def _worker() -> str:
            try:
                return str(self._catalog_service.load().stamp or "")
            except (AttributeError, OSError, RuntimeError, ValueError) as exc:
                _LOG.debug("registry_poll_stamp_load_failed error=%s", exc)
                return ""

        def _on_finished(done_request_id: int, payload: object) -> None:
            MeetingsTabV2._finish_registry_stamp_poll(
                self,
                done_request_id,
                payload,
                perf_started=perf_started,
            )

        def _on_error(done_request_id: int, error: Exception) -> None:
            MeetingsTabV2._fail_registry_stamp_poll(
                self,
                done_request_id,
                error,
                perf_started=perf_started,
            )

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _finish_registry_stamp_poll(
        self,
        done_request_id: int,
        payload: object,
        *,
        perf_started: float,
    ) -> None:
        if int(done_request_id) != int(getattr(self, "_registry_poll_request_id", 0)):
            return
        self._registry_poll_running = False
        stamp = str(payload or "")
        elapsed_ms = int(max(0.0, (time.perf_counter() - perf_started) * 1000.0))
        if elapsed_ms >= 50:
            _LOG.info("registry_poll_async_completed elapsed_ms=%s changed=%s", elapsed_ms, stamp != str(getattr(self, "_registry_stamp", "")))
        if stamp != str(getattr(self, "_registry_stamp", "")):
            self._registry_stamp = stamp
            self._refresh_artifact_export_targets()
            if self._sync_pipeline_config_plugins(save_if_changed=True):
                self._refresh_pipeline_ui()
        if bool(getattr(self, "_registry_poll_pending", False)):
            self._registry_poll_pending = False
            MeetingsTabV2._start_registry_stamp_poll(self)

    def _fail_registry_stamp_poll(
        self,
        done_request_id: int,
        error: Exception,
        *,
        perf_started: float,
    ) -> None:
        if int(done_request_id) != int(getattr(self, "_registry_poll_request_id", 0)):
            return
        self._registry_poll_running = False
        elapsed_ms = int(max(0.0, (time.perf_counter() - perf_started) * 1000.0))
        _LOG.debug("registry_poll_async_failed elapsed_ms=%s error=%s", elapsed_ms, error)
        if bool(getattr(self, "_registry_poll_pending", False)):
            self._registry_poll_pending = False
            MeetingsTabV2._start_registry_stamp_poll(self)

    def _is_plugin_enabled(self, plugin_id: str) -> bool:
        return self._global_search_controller.is_plugin_enabled(plugin_id)

    def _on_global_search_requested(self, query: str, mode: str) -> None:
        normalized_mode = self._global_search_controller.normalize_mode(mode)
        request = GlobalSearchRequestController.normalize_request(
            query=query,
            mode=mode,
            normalized_mode=normalized_mode,
        )
        request_id = GlobalSearchRequestController.next_request_id(self._global_search_request_id)
        self._global_search_request_id = request_id
        if bool(request.get("should_clear", False)):
            self._global_search_controller.clear_global_search()
            return
        all_meetings_snapshot = list(self._all_meetings)
        q = str(request.get("query", "") or "").strip()
        request_mode = str(request.get("normalized_mode", "") or "").strip()

        def _worker() -> dict[str, object]:
            return self._global_search_controller.build_global_search_payload(
                q,
                request_mode,
                all_meetings=all_meetings_snapshot,
            )

        def _on_finished(done_request_id: int, payload: object) -> None:
            if GlobalSearchRequestController.is_stale(
                done_request_id=done_request_id,
                current_request_id=self._global_search_request_id,
            ):
                return
            data = payload if isinstance(payload, dict) else {"clear": True}
            self._global_search_controller.apply_global_search_payload(data)

        def _on_error(done_request_id: int, error: Exception) -> None:
            if GlobalSearchRequestController.is_stale(
                done_request_id=done_request_id,
                current_request_id=self._global_search_request_id,
            ):
                return
            self._text_panel.set_global_search_status(f"Search failed: {error}")

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _clear_global_search(self) -> None:
        self._global_search_request_id = int(self._global_search_request_id + 1)
        self._global_search_controller.clear_global_search()

    def _on_global_search_open(
        self, meeting_id: str, stage_id: str, alias: str, kind: str, segment_index: int, start_ms: int
    ) -> None:
        self._global_search_controller.on_global_search_open(
            meeting_id, stage_id, alias, kind, segment_index, start_ms
        )

    def _set_audio_from_meeting(self, meeting) -> None:
        rel = str(getattr(meeting, "audio_relpath", "") or "").strip()
        if not rel:
            self._text_panel.set_audio_path("")
            return
        path = self._paths.output_dir / rel
        self._text_panel.set_audio_path(str(path) if path.exists() else "")

    def _on_text_selection_changed(self, stage_id: str, alias: str, kind: str) -> None:
        sid, al, k = MeetingInspectionController.normalize_selection(
            stage_id=stage_id,
            alias=alias,
            kind=kind,
        )
        self._selected_artifact_stage_id = sid
        self._selected_artifact_alias = al
        self._selected_artifact_kind = k
        if not MeetingInspectionController.should_render_selection(
            active_meeting_base_name=self._active_meeting_base_name,
            stage_id=sid,
            alias=al,
        ):
            return
        meeting = MeetingInspectionController.resolve_inspection_meeting(
            active_meeting_base_name=self._active_meeting_base_name,
            active_meeting_manifest=self._active_meeting_manifest,
            load_meeting=self._artifact_service.load_meeting,
        )
        if meeting is None:
            self._inspection_panel.clear()
            return
        self._inspection_panel.set_html(self._render_inspection_html(meeting, stage_id=sid, alias=al, kind=k))

    def navigate_to_management_evidence(self, payload: dict[str, object]) -> None:
        pending = ManagementNavigationController.route_navigation_request(
            payload,
            resolve_meeting_base=self._resolve_meeting_base,
            active_meeting_base_name=self._active_meeting_base_name,
            has_active_manifest=self._active_meeting_manifest is not None,
            select_history=lambda base: self._history_panel.select_by_base_name(base),
            apply_pending=self._apply_pending_management_navigation_if_ready,
            select_meeting=lambda base: self._select_management_navigation_base(base),
        )
        if not pending:
            return
        self._pending_management_navigation = pending

    def _select_management_navigation_base(self, base: str) -> None:
        normalized = str(base or "").strip()
        if not normalized:
            return
        self._active_meeting_base_name = normalized
        self._on_meeting_selected(normalized)

    def _apply_pending_management_navigation_if_ready(self, selected_base: str) -> None:
        payload = dict(self._pending_management_navigation or {})
        if not payload:
            return
        applied = ManagementNavigationController.apply_pending_navigation(
            payload,
            selected_base=selected_base,
            text_panel=self._text_panel,
        )
        if applied:
            self._pending_management_navigation = None

    def _render_inspection_html(self, meeting: object, *, stage_id: str, alias: str, kind: str) -> str:
        return self._inspection_render_controller.render_inspection_html(
            meeting,
            stage_id=stage_id,
            alias=alias,
            kind=kind,
        )

    def _on_pin_requested(self, stage_id: str, alias: str) -> None:
        if not self._active_meeting_base_name:
            return
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        if not sid or not al:
            return
        meeting = self._meeting_version_controller.pin_alias(
            base_name=self._active_meeting_base_name,
            stage_id=sid,
            alias=al,
        )
        if meeting is None:
            return
        self._active_meeting_manifest = meeting
        self._invalidate_meeting_payload_cache(self._active_meeting_base_name)
        self._text_panel.set_pinned_aliases(getattr(meeting, "pinned_aliases", {}) or {})
        self._log_service.append_message(
            self._fmt("log.pinned_alias", "Pinned {stage_id} -> {alias}", stage_id=sid, alias=al),
            stage_id="ui",
        )

    def _on_unpin_requested(self, stage_id: str) -> None:
        if not self._active_meeting_base_name:
            return
        sid = str(stage_id or "").strip()
        if not sid:
            return
        meeting = self._meeting_version_controller.unpin_alias(
            base_name=self._active_meeting_base_name,
            stage_id=sid,
        )
        if meeting is None:
            return
        self._active_meeting_manifest = meeting
        self._invalidate_meeting_payload_cache(self._active_meeting_base_name)
        self._text_panel.set_pinned_aliases(getattr(meeting, "pinned_aliases", {}) or {})
        self._log_service.append_message(
            self._fmt("log.unpinned_alias", "Unpinned {stage_id}", stage_id=sid),
            stage_id="ui",
        )

    def _on_active_version_changed(self, stage_id: str, alias: str) -> None:
        if not self._active_meeting_base_name:
            return
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        if not sid or not al:
            return
        meeting = self._meeting_version_controller.set_active_alias(
            base_name=self._active_meeting_base_name,
            stage_id=sid,
            alias=al,
        )
        if meeting is None:
            return
        self._active_meeting_manifest = meeting
        self._invalidate_meeting_payload_cache(self._active_meeting_base_name)
        # Avoid rebuilding artifact tabs on every click: it re-reads and re-parses all artifacts,
        # which can freeze the UI on large meetings. The current tab is already selected.
        self._text_panel.set_active_aliases(
            getattr(meeting, "active_aliases", {}) or {},
            rebuild_tabs=False,
            emit_selection=False,
        )

    def _on_log_appended(self, _stage_id: str, _message: str) -> None:
        if not self._logs_flush_timer.isActive():
            self._logs_flush_timer.start(120)

    def _flush_logs_to_text_panel(self) -> None:
        self._text_panel.set_logs(self._log_service)
        self._request_runtime_tile_refresh()

    def _start_pipeline(
        self,
        *,
        force_run: bool | None = None,
        force_run_from: str | None = None,
        base_name: str | None = None,
        runtime_config_override: dict[str, object] | None = None,
        files_override: list[str] | None = None,
    ) -> None:
        if self._pipeline_runner.is_running():
            return
        if self._sync_pipeline_config_plugins(save_if_changed=True):
            self._refresh_pipeline_ui()
        # Release any audio playback handle to avoid Windows file-lock issues during
        # media_convert artifact realignment (WinError 32 on rename/replace).
        try:
            self._text_panel.set_audio_path("")
        except RuntimeError:
            pass
        if base_name:
            base = str(base_name or "")
            if base:
                self._history_panel.select_by_base_name(base)
                if self._active_meeting_base_name != base:
                    self._on_meeting_selected(base)
        pending_files = self._pending_files_from_meetings(self._artifact_service.list_meetings())
        resolution = PipelineInputController.resolve_start_files(
            explicit_files=list(files_override or []),
            pending_files=pending_files,
            ad_hoc_files=self._ad_hoc_input_files,
            active_meeting_base_name=self._active_meeting_base_name,
            active_meeting_path=self._active_meeting_path(),
            active_meeting_status=self._active_meeting_status(),
            base_name=str(base_name or "").strip(),
            force_run=force_run,
            force_run_from=force_run_from,
        )
        files = list(resolution.files)
        if resolution.missing_selected_source:
            self._log_service.append_message(
                self._tr("log.selected_meeting_no_source", "Selected meeting has no source file")
            )
            self._refresh_pipeline_ui()
            return
        self._input_files = list(files)
        if not files:
            self._log_service.append_message(
                self._tr("log.no_files_selected", "No files selected"),
                stage_id="input",
            )
            self._refresh_pipeline_ui()
            return
        force_run_flag = bool(force_run) if force_run is not None else False
        effective_force_run_from = self._effective_force_run_from(
            files=files,
            requested_stage_id=force_run_from,
            force_run_flag=force_run_flag,
        )
        if effective_force_run_from and not str(force_run_from or "").strip():
            self._log_service.append_message(
                self._fmt(
                    "log.run_from_stage_auto",
                    "Running from stage: {stage_name}",
                    stage_name=self._stage_display_name(effective_force_run_from),
                ),
                stage_id="ui",
            )
        runtime_force_run_from = StageArtifactNavigationController.runtime_stage_id_for_ui(
            effective_force_run_from
        )
        if isinstance(runtime_config_override, dict):
            config_data = copy.deepcopy(runtime_config_override)
        else:
            config_data = self._build_runtime_config()
        if not self._prepare_llm_prompt_context(
            config_data,
            force_run_from=runtime_force_run_from,
        ):
            self._refresh_pipeline_ui()
            return
        self._clear_preflight_health_progress()
        self._pipeline_paused = False
        self._pipeline_runner.start(
            files=files,
            config_data=config_data,
            force_run=force_run_flag,
            force_run_from=runtime_force_run_from,
        )
        self._refresh_pipeline_ui()

    def _build_runtime_config(self) -> dict[str, object]:
        build_runtime_config = self._pipeline_runtime_config_controller.build_runtime_config
        kwargs: dict[str, object] = {
            "pipeline_preset": self._pipeline_preset,
            "sanitize_params_for_plugin": self._sanitize_params_for_plugin,
            "model_available_for_plugin": self._is_stage_model_available,
            "compute_llm_prompt_signature": self._compute_llm_prompt_signature,
        }
        try:
            return build_runtime_config(self._config_data, **kwargs)
        except TypeError as exc:
            message = str(exc)
            if (
                "unexpected keyword argument" not in message
                or "compute_llm_prompt_signature" not in message
            ):
                raise
            kwargs.pop("compute_llm_prompt_signature", None)
            return build_runtime_config(self._config_data, **kwargs)

    def _effective_force_run_from(
        self,
        *,
        files: list[str],
        requested_stage_id: str | None,
        force_run_flag: bool,
    ) -> str | None:
        requested = str(requested_stage_id or "").strip()
        if requested:
            return requested
        return None

    def _is_single_active_meeting_run(self, files: list[str]) -> bool:
        if not self._active_meeting_base_name:
            return False
        if len(files) != 1:
            return False
        active_path = str(self._active_meeting_path() or "").strip()
        if not active_path:
            return False
        file_path = str(files[0] or "").strip()
        if not file_path:
            return False
        try:
            return Path(file_path).resolve() == Path(active_path).resolve()
        except (OSError, RuntimeError, ValueError):
            return file_path == active_path

    def _first_dirty_stage_id(self) -> str:
        states = self._current_stage_states()
        for stage_id in PIPELINE_STAGE_ORDER:
            if self._is_stage_disabled(stage_id):
                continue
            state = states.get(stage_id)
            if state and bool(getattr(state, "dirty", False)):
                return stage_id
        return ""

    def _is_stage_dirty(self, stage_id: str) -> bool:
        sid = str(stage_id or "").strip()
        if not sid:
            return False
        state = self._current_stage_states().get(sid)
        return bool(state and bool(getattr(state, "dirty", False)))

    def _can_auto_rerun_from_stage(self, stage_id: str) -> bool:
        sid = str(stage_id or "").strip()
        if not sid:
            return False
        meeting = self._current_meeting_manifest_for_ui()
        if meeting is None:
            return False
        if sid == "media_convert":
            return bool(getattr(meeting, "source", None))
        transcript_relpath = str(getattr(meeting, "transcript_relpath", "") or "").strip()
        if sid in {"transcription", "text_processing", "llm_processing"}:
            return bool(transcript_relpath)
        if sid in {"management", "service"}:
            nodes = getattr(meeting, "nodes", None)
            if not isinstance(nodes, dict):
                return False
            for node in nodes.values():
                if str(getattr(node, "stage_id", "") or "").strip() != "llm_processing":
                    continue
                artifacts = getattr(node, "artifacts", None)
                if not isinstance(artifacts, list):
                    continue
                if any(str(getattr(item, "kind", "") or "").strip() == "summary" for item in artifacts):
                    return True
            return False
        return False

    def _prepare_llm_prompt_context(
        self, runtime_config: dict[str, object], *, force_run_from: str | None = None
    ) -> bool:
        if not self._llm_prompt_context_controller.llm_stage_will_run(
            runtime_config,
            force_run_from=force_run_from,
            stage_order=list(PIPELINE_STAGE_ORDER),
        ):
            return True
        selection = self._management_prompt_selection_for_runtime(runtime_config)
        self._llm_prompt_context_controller.apply_llm_prompt_selection(runtime_config, selection)
        return True

    @staticmethod
    def _management_prompt_selection_for_runtime(runtime_config: dict[str, object]) -> dict:
        stages = runtime_config.get("stages")
        if not isinstance(stages, dict):
            return {
                "agenda_id": "",
                "agenda_title": "",
                "agenda_text": "",
                "prompt_project_ids": "",
            }
        stage = stages.get("management")
        if not isinstance(stage, dict):
            return {
                "agenda_id": "",
                "agenda_title": "",
                "agenda_text": "",
                "prompt_project_ids": "",
            }
        params = stage.get("params")
        if not isinstance(params, dict):
            return {
                "agenda_id": "",
                "agenda_title": "",
                "agenda_text": "",
                "prompt_project_ids": "",
            }
        return {
            "agenda_id": str(params.get("prompt_agenda_id", "") or "").strip(),
            "agenda_title": str(params.get("prompt_agenda_title", "") or "").strip(),
            "agenda_text": str(params.get("prompt_agenda_text", "") or "").strip(),
            "prompt_project_ids": str(params.get("prompt_project_ids", "") or "").strip(),
        }

    def _preflight_plugin_health_checks(
        self, runtime_config: dict[str, object], *, force_run_from: str | None = None
    ) -> tuple[bool, dict[str, object]]:
        return self._plugin_health_interaction.preflight_plugin_health_checks(
            runtime_config, force_run_from=force_run_from
        )

    def _health_checks_for_runtime(
        self, runtime_config: dict[str, object], *, force_run_from: str | None = None
    ) -> list[dict]:
        return self._plugin_health_interaction.health_checks_for_runtime(
            runtime_config, force_run_from=force_run_from
        )

    def _prompt_health_decision(
        self,
        stage_id: str,
        plugin_id: str,
        report: PluginHealthReport,
        check: dict,
    ) -> str:
        return self._plugin_health_interaction.prompt_health_decision(stage_id, plugin_id, report, check)

    def _attempt_automatic_preflight_fix(
        self,
        *,
        stage_id: str,
        plugin_id: str,
        report: PluginHealthReport,
        check: dict,
    ) -> PluginHealthReport:
        return self._plugin_health_interaction.attempt_automatic_preflight_fix(
            stage_id=stage_id,
            plugin_id=plugin_id,
            report=report,
            check=check,
        )

    @staticmethod
    def _health_issues_text(issues: tuple[PluginHealthIssue, ...]) -> str:
        return PluginHealthInteractionController.health_issues_text(issues)

    def _run_plugin_quick_fix(self, plugin_id: str, quick_fix: PluginHealthQuickFix) -> None:
        self._plugin_health_interaction.run_plugin_quick_fix(plugin_id, quick_fix)

    def _apply_skip_once(self, runtime_config: dict[str, object], check: dict) -> None:
        self._pipeline_runtime_config_controller.apply_skip_once(runtime_config, check)

    def _apply_disable_preset(self, check: dict) -> None:
        stage_id = self._pipeline_runtime_config_controller.apply_disable_preset(
            self._config_data,
            check,
        )
        if not stage_id:
            return
        self._save_pipeline_config()
        self._mark_dirty(stage_id)
        self._refresh_pipeline_ui()

    def _stage_params_for_plugin(self, stage_id: str, plugin_id: str) -> dict:
        return PluginHealthInteractionController.stage_params_for_plugin(
            self._config_data, stage_id, plugin_id
        )

    def _plugin_display_name(self, plugin_id: str) -> str:
        return self._get_catalog().display_name(str(plugin_id or "").strip())

    def _active_meeting_id(self) -> str:
        meeting = self._current_meeting_manifest_for_ui()
        if meeting is None:
            return ""
        return str(getattr(meeting, "meeting_id", "") or "").strip()

    def _load_management_suggestions_for_meeting(self, meeting_id: str) -> list[dict]:
        mid = str(meeting_id or "").strip()
        if not mid:
            return []
        store = ManagementStore(self._app_root)
        try:
            return list(store.list_suggestions(meeting_id=mid))
        finally:
            store.close()

    def _refresh_active_management_suggestions(self) -> None:
        meeting_id = self._active_meeting_id()
        if not meeting_id:
            self._text_panel.set_management_suggestions([])
            return
        self._text_panel.set_management_suggestions(self._load_management_suggestions_for_meeting(meeting_id))

    def _current_meeting_manifest_for_ui(self) -> object | None:
        meeting = self._active_meeting_manifest
        active_base = str(self._active_meeting_base_name or "").strip()
        if meeting is not None:
            meeting_base = str(getattr(meeting, "base_name", "") or "").strip()
            if meeting_base == active_base:
                return meeting
        if not active_base:
            return None
        try:
            meeting = self._artifact_service.load_meeting(active_base)
            self._active_meeting_manifest = meeting
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            meeting = None
        return meeting

    def _reload_active_meeting_manifest(self, base_name: str) -> None:
        base = str(base_name or "").strip()
        if not base or base != str(self._active_meeting_base_name or "").strip():
            return
        try:
            self._active_meeting_manifest = self._artifact_service.load_meeting(base)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return

    def _restore_selected_artifact(self) -> None:
        kind = str(self._selected_artifact_kind or "").strip()
        stage_id = str(self._selected_artifact_stage_id or "").strip()
        alias = str(self._selected_artifact_alias or "").strip()
        if kind:
            self._text_panel.select_artifact_kind(kind)
        if stage_id and alias:
            self._text_panel.select_version(stage_id=stage_id, alias=alias, kind=kind)

    def _show_plugin_health_dialog(
        self, plugin_id: str, issues: tuple[PluginHealthIssue, ...]
    ) -> None:
        self._plugin_health_interaction.show_plugin_health_dialog(plugin_id, issues)

    def _on_pipeline_event(self, event) -> None:
        self._log_service.append_event(event)
        self._record_stage_activity(event)
        event_type = str(getattr(event, "event_type", "") or "").strip()
        base_name = str(getattr(event, "base_name", "") or "").strip()
        active_base = str(self._active_meeting_base_name or "").strip()
        if event_type in {"stage_finished", "stage_skipped", "stage_failed"}:
            self._refresh_history()
        if base_name and active_base and base_name == active_base:
            if event_type == "artifact_written":
                self._refresh_active_meeting(base_name=base_name, immediate=True)
            elif event_type in {"stage_finished", "stage_skipped", "stage_failed"}:
                self._refresh_active_meeting(base_name=base_name)

    def _record_stage_activity(self, event: object) -> None:
        self._stage_runtime.record_stage_activity(
            event,
            active_meeting_base_name=self._active_meeting_base_name,
            last_stage_base_name=self._last_stage_base_name,
        )

    def _stage_states_for(self, base_name: str) -> dict[str, StageRuntimeState]:
        return self._stage_runtime.stage_states_for(str(base_name or ""))

    def _current_stage_states(self) -> dict[str, StageRuntimeState]:
        return self._stage_runtime.current_stage_states(
            active_meeting_base_name=self._active_meeting_base_name,
            last_stage_base_name=self._last_stage_base_name,
        )

    def _tick_activity(self) -> None:
        self._request_runtime_tile_refresh()

    def _clear_preflight_health_progress(self) -> None:
        self._preflight_health_state = {
            "running": False,
            "summary": "",
            "stage_name": "",
            "plugin_name": "",
            "log_lines": [],
        }

    def _on_preflight_health_progress(self, payload: dict[str, object]) -> None:
        state = str((payload or {}).get("state", "") or "").strip().lower()
        running = state == "running"
        total_raw = payload.get("total")
        current_raw = payload.get("current")
        try:
            total = max(0, int(total_raw)) if total_raw is not None else 0
        except (TypeError, ValueError):
            total = 0
        try:
            current = max(0, int(current_raw)) if current_raw is not None else 0
        except (TypeError, ValueError):
            current = 0
        if total and current > total:
            current = total
        stage_id = str((payload or {}).get("stage_id", "") or "").strip()
        plugin_id = str((payload or {}).get("plugin_id", "") or "").strip()
        elapsed_raw = payload.get("elapsed_seconds")
        try:
            elapsed_seconds = max(0, int(elapsed_raw)) if elapsed_raw is not None else 0
        except (TypeError, ValueError):
            elapsed_seconds = 0
        plugin_name = self._plugin_display_name(plugin_id) if plugin_id else ""
        stage_label = self._stage_display_name(stage_id) if stage_id else ""

        if running:
            if stage_label:
                summary = self._fmt(
                    "runtime.health_progress_with_stage",
                    "Health checks {current}/{total}: {stage}",
                    current=current,
                    total=total,
                    stage=stage_label,
                )
            else:
                summary = self._fmt(
                    "runtime.health_progress",
                    "Health checks {current}/{total}",
                    current=current,
                    total=total,
                )
            if elapsed_seconds > 0:
                summary = self._fmt(
                    "runtime.health_progress_elapsed",
                    "{summary} ({seconds}s)",
                    summary=summary,
                    seconds=elapsed_seconds,
                )
            lines: list[str] = [summary]
            if plugin_name:
                lines.append(f"{self._tr('system.plugin_prefix', 'Plugin:')} {plugin_name}")
            self._preflight_health_state = {
                "running": True,
                "summary": summary,
                "stage_name": self._tr("runtime.health_stage", "Health checks"),
                "plugin_name": plugin_name,
                "log_lines": lines[:3],
            }
        else:
            self._clear_preflight_health_progress()

        self._request_runtime_tile_refresh()

    def _pipeline_activity_text(self) -> str:
        return self._stage_runtime.pipeline_activity_text(
            active_meeting_base_name=self._active_meeting_base_name,
            last_stage_base_name=self._last_stage_base_name,
        )

    def _refresh_runtime_tile(self) -> None:
        health_running = bool(self._preflight_health_state.get("running", False))
        if health_running and not self._pipeline_runner.is_running():
            running = True
            summary = str(self._preflight_health_state.get("summary", "") or "").strip()
            stage_name = str(self._preflight_health_state.get("stage_name", "") or "").strip()
            plugin_name = str(self._preflight_health_state.get("plugin_name", "") or "").strip()
            log_lines = [
                str(item or "").strip()
                for item in list(self._preflight_health_state.get("log_lines", []) or [])
                if str(item or "").strip()
            ][:3]
        else:
            running_stage_id = self._running_stage_id()
            running = bool(running_stage_id) and self._pipeline_runner.is_running()
            summary = self._pipeline_activity_text() if running else ""
            stage_name = self._stage_display_name(running_stage_id) if running_stage_id else ""
            plugin_name = ""
            if running_stage_id:
                plugin_id = self._runtime_active_plugin_id(running_stage_id)
                if plugin_id:
                    plugin_name = self._plugin_display_name(plugin_id)
            log_lines = self._runtime_log_lines(stage_id=running_stage_id, limit=3)
        self._pipeline_panel.set_activity(summary)
        self._pipeline_panel.set_activity_context(
            stage_name=stage_name,
            plugin_name=plugin_name,
            lines=log_lines,
        )
        self.runtimeInfoChanged.emit(
            {
                "summary": summary,
                "stage_name": stage_name,
                "plugin_name": plugin_name,
                "log_lines": list(log_lines),
                "running": bool(running),
            }
        )

    def _request_runtime_tile_refresh(self, *, immediate: bool = False) -> None:
        if bool(immediate) or not self._pipeline_runner.is_running():
            self._runtime_refresh_pending = False
            if self._runtime_refresh_timer.isActive():
                self._runtime_refresh_timer.stop()
            self._refresh_runtime_tile()
            return
        self._runtime_refresh_pending = True
        if not self._runtime_refresh_timer.isActive():
            self._runtime_refresh_timer.start()

    def _flush_deferred_runtime_refresh(self) -> None:
        if not self._runtime_refresh_pending:
            return
        self._runtime_refresh_pending = False
        self._refresh_runtime_tile()

    def _runtime_active_plugin_id(self, stage_id: str) -> str:
        sid = str(stage_id or "").strip()
        if not sid:
            return ""
        state = self._current_stage_states().get(sid)
        if state:
            from_message = self._plugin_id_from_runtime_message(getattr(state, "last_message", ""))
            if from_message:
                return from_message
        return str(self._selected_plugin_id(sid) or "").strip()

    def _plugin_id_from_runtime_message(self, message: str) -> str:
        text = str(message or "").strip()
        if not text:
            return ""
        prefix = text.split("(", 1)[0].strip()
        if ":" in prefix:
            prefix = prefix.split(":", 1)[0].strip()
        if "." not in prefix:
            return ""
        plugin_id = str(prefix or "").strip()
        if not plugin_id:
            return ""
        plugin = self._get_catalog().plugin_by_id(plugin_id)
        return plugin_id if plugin else ""

    def _running_stage_id(self) -> str:
        states = self._current_stage_states()
        if str(getattr(states.get("text_processing"), "status", "") or "").strip().lower() == "running":
            return "text_processing"
        if str(getattr(states.get("llm_processing"), "status", "") or "").strip().lower() == "running":
            return "llm_processing"
        for stage_id in PIPELINE_STAGE_ORDER:
            state = states.get(stage_id)
            if state and str(getattr(state, "status", "") or "").strip().lower() == "running":
                return stage_id
        return ""

    def _runtime_log_lines(self, *, stage_id: str, limit: int) -> list[str]:
        stage_key = str(stage_id or "").strip()
        if stage_key:
            entries = self._log_service.get_stage_logs(stage_key)
        else:
            entries = self._log_service.get_all_logs()
        out: list[str] = []
        for entry in reversed(entries):
            text = str(getattr(entry, "message", "") or "").strip()
            if not text:
                continue
            out.append(text if len(text) <= 96 else f"{text[:93].rstrip()}...")
            if len(out) >= max(1, int(limit)):
                break
        out.reverse()
        return out

    def _on_stage_status(
        self,
        stage_id: str,
        status: str,
        _duration_ms: int,
        error: str,
        _skip_reason: str,
        progress: int,
        base_name: str = "",
    ) -> None:
        affects_active = self._stage_runtime.apply_stage_status(
            stage_id=str(stage_id or ""),
            status=str(status or ""),
            error=str(error or ""),
            progress=progress,
            base_name=str(base_name or ""),
            active_meeting_base_name=self._active_meeting_base_name,
            last_stage_base_name=self._last_stage_base_name,
        )
        if affects_active:
            self._request_pipeline_ui_refresh()

    def _on_pipeline_finished(self, base_name: str) -> None:
        base_key = str(base_name or "") or self._active_meeting_base_name or self._last_stage_base_name
        self._invalidate_meeting_payload_cache(base_key)
        self._finalize_meeting_status(base_key)
        self._reload_active_meeting_manifest(base_key)
        if base_key:
            self._stage_runtime.mark_running_completed(base_name=base_key)
        self._ad_hoc_input_files = []
        self._pipeline_paused = False
        self._refresh_history(select_base_name=str(base_name or ""))
        self._refresh_pipeline_ui()

    def _finalize_meeting_status(self, base_name: str) -> None:
        base = str(base_name or "").strip()
        if not base:
            return
        try:
            meeting = self._artifact_service.load_meeting(base)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return
        status = str(getattr(meeting, "processing_status", "") or "").strip().lower()
        if status != "running":
            return
        self._set_meeting_status(meeting, "completed", error="")
        try:
            self._artifact_service.save_meeting(meeting)
        except (OSError, RuntimeError, ValueError):
            return

    def _on_pipeline_failed(self, reason: str) -> None:
        self._log_service.append_message(str(reason or self._tr("log.pipeline_failed", "Pipeline failed")))
        self._pipeline_paused = False
        self._refresh_pipeline_ui()

    def _build_stage_view_model(self, stage_id: str) -> StageViewModel:
        return self._stage_view_model_composer.build_stage_view_model(stage_id)

    def _schema_for(self, plugin_id: str, *, stage_id: str) -> list[SettingField]:
        return self._stage_schema_controller.schema_for(plugin_id, stage_id=stage_id)

    def _sanitize_params_for_plugin(self, plugin_id: str, params: dict) -> dict[str, object]:
        return self._stage_schema_controller.sanitize_params_for_plugin(plugin_id, params)

    @staticmethod
    def _compute_llm_prompt_signature(profile_id: str, custom_prompt: str) -> str:
        try:
            from aimn.plugins.prompt_manager import compute_prompt_signature

            return str(compute_prompt_signature(profile_id, custom_prompt) or "").strip()
        except (ImportError, AttributeError, TypeError, ValueError):
            return ""

    def _whisper_models_state(self) -> tuple[list[str], list[str]]:
        return self._model_catalog_controller.whisper_models_state()

    def _model_options_for(self, plugin_id: str) -> list[SettingOption]:
        return self._model_catalog_controller.model_options_for(plugin_id)

    def _load_plugin_models_config(self, plugin_id: str) -> list[dict]:
        return self._model_catalog_controller.load_plugin_models_config(plugin_id)

    @staticmethod
    def _models_from_action_result(result: object) -> list[dict]:
        return ModelCatalogController.models_from_action_result(result)

    def _llm_enabled_models_from_stage(
        self,
        *,
        plugin_id: str,
        stage_params: dict,
        variants: object,
        providers: list[str],
    ) -> tuple[dict[str, list[str]], str]:
        return self._model_catalog_controller.llm_enabled_models_from_stage(
            plugin_id=plugin_id,
            stage_params=stage_params,
            variants=variants,
            providers=providers,
        )

    def _llm_provider_models_payload(
        self,
        providers: list[str],
        *,
        enabled_models: dict[str, list[str]] | None = None,
        available_only: bool = False,
    ) -> dict[str, list[dict]]:
        return self._model_catalog_controller.llm_provider_models_payload(
            providers,
            enabled_models=enabled_models,
            available_only=available_only,
        )

    def _llm_installed_models_payload(self, plugin_id: str) -> list[dict]:
        return self._model_catalog_controller.llm_installed_models_payload(plugin_id)

    def _local_models_from_capabilities(self, plugin_id: str) -> list[dict]:
        return self._model_catalog_controller.local_models_from_capabilities(plugin_id)

    def _is_stage_model_available(self, plugin_id: str, params: dict) -> bool:
        return self._model_catalog_controller.is_model_selection_available(plugin_id, params)

    def _inline_settings_keys(self, stage_config: dict, schema: list[SettingField]) -> list[str]:
        return self._stage_schema_controller.inline_settings_keys(stage_config, schema)

    def _plugin_available(self, plugin_id: str) -> bool:
        plugin = self._get_catalog().plugin_by_id(plugin_id)
        if not plugin:
            return False
        if not plugin.installed:
            return False
        if plugin.enabled:
            return True
        return bool(self._offline_mode)

    def _plugin_enabled_for_config(self, plugin_id: str) -> bool:
        plugin = self._get_catalog().plugin_by_id(str(plugin_id or "").strip())
        return bool(plugin and plugin.installed and plugin.enabled)

    def _default_active_plugin_for_stage(self, stage_id: str) -> object | None:
        return self._get_catalog().default_plugin_for_stage(str(stage_id or "").strip())

    def _sync_pipeline_config_plugins(self, *, save_if_changed: bool) -> bool:
        changed = self._pipeline_runtime_config_controller.prune_unavailable_plugins(
            self._config_data,
            plugin_available=self._plugin_enabled_for_config,
        )
        changed = (
            self._pipeline_runtime_config_controller.restore_required_stage_plugins(
                self._config_data,
                default_plugin_for_stage=self._default_active_plugin_for_stage,
            )
            or changed
        )
        changed = self._sync_ai_stage_disabled_state() or changed
        if changed and save_if_changed:
            self._save_pipeline_config()
        return changed

    def _sync_ai_stage_disabled_state(self) -> bool:
        pipeline = self._config_data.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
            self._config_data["pipeline"] = pipeline
        raw_disabled = pipeline.get("disabled_stages")
        disabled = {str(item or "").strip() for item in raw_disabled if str(item or "").strip()} if isinstance(raw_disabled, list) else set()
        llm_disabled = "llm_processing" in disabled
        text_disabled = "text_processing" in disabled
        if llm_disabled == text_disabled:
            return False
        if llm_disabled:
            disabled.add("text_processing")
        else:
            disabled.discard("text_processing")
        pipeline["disabled_stages"] = sorted(disabled)
        return True

    def _is_stage_disabled(self, stage_id: str) -> bool:
        pipeline = self._config_data.get("pipeline", {})
        disabled = pipeline.get("disabled_stages", []) if isinstance(pipeline, dict) else []
        return stage_id in disabled

    def _mark_dirty(self, stage_id: str) -> None:
        self._stage_runtime.mark_dirty_from(
            stage_id=stage_id,
            active_meeting_base_name=self._active_meeting_base_name,
            last_stage_base_name=self._last_stage_base_name,
        )

    def _save_pipeline_config(self) -> None:
        self._pipeline_settings.save(self._pipeline_preset, self._config_data)

    def refresh_plugin_catalog_state(self) -> None:
        if self._sync_pipeline_config_plugins(save_if_changed=True):
            self._refresh_pipeline_ui()
            return
        self._refresh_pipeline_ui()

    def on_plugin_models_changed(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        self._model_catalog_controller.invalidate_provider_cache(pid)
        self.refresh_plugin_catalog_state()
        if self._pipeline_panel.is_settings_open():
            self._rerender_timer.start(0)
