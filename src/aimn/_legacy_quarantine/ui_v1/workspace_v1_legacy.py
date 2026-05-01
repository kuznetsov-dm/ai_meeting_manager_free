from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QInputDialog,
    QLabel,
    QMessageBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import (
    AppPaths,
    ContentService,
    OFFLINE_PRESET_ID,
    PipelinePresetService,
    PluginCatalogService,
    PluginModelsService,
    SettingsService,
)
from aimn.ui.services.artifact_service import ArtifactService
from aimn.ui.services.log_service import LogService
from aimn.ui.services.settings_service import PipelineSettingsUiService
from aimn.ui.stage_inspector_tabs import StageInspectorPanel
from aimn.ui.tabs.contracts import SettingField, SettingOption, StageViewModel
from aimn.ui.widgets.pipeline_chain import PipelineChainBarWidget
from aimn.ui.widgets.stage_settings_panels import (
    EditAlgorithmsPanel,
    EmbeddingsExtrasPanel,
    LlmProviderPanel,
    TranscriptionExtrasPanel,
)
from aimn.ui.widgets.workspace_panels import ArtifactsPanel, FileSelectionPanel, JobsPanel, LogsPanel
from aimn.ui.widgets.activity_panel import ActivityPanel


PIPELINE_STAGE_ORDER = [
    "input",
    "media_convert",
    "transcription",
    "llm_processing",
]

_WHISPER_LOCAL_PLUGIN_IDS = {
    "transcription.whisperadvanced",
}


@dataclass
class StageRuntimeState:
    status: str = "idle"
    progress: Optional[int] = None
    error: str = ""
    warnings: List[str] = None
    dirty: bool = False

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


class PipelineWorkspace(QObject):
    request_pipeline_run = Signal(bool)

    def __init__(self, app_root: Path) -> None:
        super().__init__()
        self._app_root = app_root
        self._paths = AppPaths.resolve(app_root)
        config_dir = self._paths.config_dir / "settings"
        self._pipeline_settings = PipelinePresetService(config_dir, repo_root=self._app_root)
        self._settings_store = SettingsService(config_dir, repo_root=self._app_root)
        self._artifact_service = ArtifactService(app_root)
        self._log_service = LogService()
        self._catalog_service = PluginCatalogService(app_root)
        self._catalog = self._catalog_service.load().catalog
        self._content = ContentService(app_root)
        self._models_service = PluginModelsService(app_root)
        self._pipeline_preset = self._pipeline_settings.active_preset()
        self._offline_mode = self._pipeline_preset == OFFLINE_PRESET_ID
        self._config_data = self._load_pipeline_config(self._pipeline_preset)
        self._stage_states: Dict[str, StageRuntimeState] = {
            stage_id: StageRuntimeState() for stage_id in PIPELINE_STAGE_ORDER
        }
        self._current_meeting = None

        self.pipeline_chain = PipelineChainBarWidget()
        self.stage_inspector = StageInspectorPanel(
            self._build_settings_service(),
            self._artifact_service,
            self._log_service,
        )
        self.artifacts_panel = ArtifactsPanel(self._artifact_service)
        self.logs_panel = LogsPanel(self._log_service)
        self.files_panel = FileSelectionPanel()
        self.jobs_panel = JobsPanel()
        self.files_panel.filesChanged.connect(self._on_files_changed)

        self.pipeline_chain.stageSelected.connect(self._select_stage)
        self.pipeline_chain.stageSettingsChanged.connect(self._inline_settings_changed)
        self.pipeline_chain.runFromStageRequested.connect(self._request_run_from)
        self.pipeline_chain.rerunStageRequested.connect(self._request_rerun)
        self.pipeline_chain.openOutputRequested.connect(self._open_output_folder)
        self.pipeline_chain.stageDisabledChanged.connect(self._stage_disabled_changed)
        self.pipeline_chain.run_all_button().clicked.connect(self._request_run_all)
        self.pipeline_chain.customize_button().clicked.connect(self._open_customize_dialog)
        self.pipeline_chain.presetChanged.connect(self._preset_changed)
        self.pipeline_chain.inputFilesChanged.connect(self.files_panel.set_files)

        self.stage_inspector.settingsChanged.connect(self._stage_settings_changed)
        self.stage_inspector.runRequested.connect(self._request_run_all)
        self.stage_inspector.runFromRequested.connect(self._request_run_from)
        self.stage_inspector.rerunRequested.connect(self._request_rerun)

        self.artifacts_panel.meetingSelected.connect(self._on_meeting_selected)
        self.artifacts_panel.retryFailedRequested.connect(self._retry_failed_stages)

        self._active_stage_id = PIPELINE_STAGE_ORDER[0]
        self._refresh_stage_view_models()
        self._select_stage(self._active_stage_id)
        self.pipeline_chain.set_preset(self._pipeline_preset)

        self._download_thread = None

    def build_pipeline_chain_dock(self) -> QDockWidget:
        dock = QDockWidget("Pipeline")
        dock.setWidget(self.pipeline_chain)
        dock.setObjectName("dock_pipeline_chain")
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        dock.setAllowedAreas(Qt.TopDockWidgetArea | Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # Pipeline panel has its own toolbar; keep the dock chrome from consuming vertical space.
        dock.setTitleBarWidget(QWidget())
        dock.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return dock

    def build_stage_inspector_dock(self) -> QDockWidget:
        dock = QDockWidget("Stage Inspector")
        dock.setWidget(self.stage_inspector)
        dock.setObjectName("dock_stage_inspector")
        return dock

    def build_artifacts_dock(self) -> QDockWidget:
        dock = QDockWidget("Artifacts")
        dock.setWidget(self.artifacts_panel)
        dock.setObjectName("dock_artifacts")
        return dock

    def build_logs_dock(self) -> QDockWidget:
        dock = QDockWidget("Activity")
        dock.setWidget(ActivityPanel(self.logs_panel, self.jobs_panel))
        dock.setObjectName("dock_activity")
        return dock

    def build_inputs_dock(self) -> QDockWidget:
        dock = QDockWidget("Inputs")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.jobs_panel, 1)
        dock.setWidget(container)
        dock.setObjectName("dock_inputs")
        return dock

    def selected_files(self) -> list[str]:
        return self.files_panel.files()

    def validate_pipeline_selection(self) -> bool:
        stages = self._config_data.get("stages", {})
        transcription = stages.get("transcription", {})
        plugin_id = str(transcription.get("plugin_id", "")).strip()
        if not plugin_id:
            QMessageBox.warning(None, "Missing Plugin", "Select a transcription plugin before running.")
            return False
        plugin = self._catalog.plugin_by_id(plugin_id)
        if not plugin:
            QMessageBox.warning(None, "Missing Plugin", f"Plugin '{plugin_id}' is not available.")
            return False
        if not plugin.installed:
            QMessageBox.warning(None, "Plugin Not Installed", f"Install plugin '{plugin_id}' before running.")
            return False
        if not plugin.enabled:
            QMessageBox.warning(None, "Plugin Disabled", f"Enable plugin '{plugin_id}' before running.")
            return False
        return True

    def build_runtime_config(self) -> Dict[str, object]:
        payload = dict(self._config_data)
        pipeline = payload.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
        # Management/Service are run separately from the main pipeline in the current UX.
        disabled = pipeline.get("disabled_stages", [])
        if not isinstance(disabled, list):
            disabled = []
        for stage_id in ("management", "service"):
            if stage_id not in disabled:
                disabled.append(stage_id)
        pipeline["disabled_stages"] = disabled
        pipeline["preset"] = self._pipeline_preset
        payload["pipeline"] = pipeline
        stages = payload.get("stages", {})
        if isinstance(stages, dict):
            edit_variants, edit_params = self._build_edit_variants()
            if edit_variants:
                stages.setdefault("text_processing", {})
                stages["text_processing"]["variants"] = edit_variants
                stages["text_processing"]["params"] = edit_params
                stages["text_processing"]["plugin_id"] = edit_variants[0]["plugin_id"]
            summary_variants, summary_params = self._build_summary_variants()
            if summary_variants:
                stages.setdefault("llm_processing", {})
                stages["llm_processing"]["variants"] = summary_variants
                stages["llm_processing"]["params"] = summary_params
                stages["llm_processing"]["plugin_id"] = summary_variants[0]["plugin_id"]
        payload["stages"] = stages
        return payload

    def set_stage_status(
        self,
        stage_id: str,
        status: str,
        duration_ms: int = 0,
        error: str = "",
        skip_reason: str = "",
        progress: int | None = None,
    ) -> None:
        state = self._stage_states.get(stage_id)
        if not state:
            return
        mapping = {
            "pending": "idle",
            "running": "running",
            "finished": "completed",
            "failed": "failed",
            "skipped": "skipped",
        }
        state.status = mapping.get(status, status)
        state.error = error or skip_reason or ""
        state.progress = progress
        if state.status in {"completed", "failed", "skipped"}:
            state.dirty = False
        self._refresh_stage_view_models()

    def set_stage_results(self, meeting) -> None:
        if not meeting.pipeline_runs:
            return
        run = meeting.pipeline_runs[-1]
        for stage in run.stages:
            self.set_stage_status(
                stage.stage_id,
                stage.status,
                duration_ms=stage.duration_ms or 0,
                error=stage.error or "",
                skip_reason=stage.skip_reason or "",
                progress=100 if stage.status == "finished" else 0,
            )

    def add_job_entry(self, job_id: str, label: str, *, status: str = "queued") -> None:
        self.jobs_panel.add_job_entry(job_id, label, status=status)

    def update_job_status(self, job_id: str, status: str) -> None:
        self.jobs_panel.update_job_status(job_id, status)

    def load_history(self) -> None:
        self.artifacts_panel.load_history()

    def shutdown(self) -> None:
        if self._download_thread and self._download_thread.isRunning():
            if hasattr(self._download_thread, "request_cancel"):
                self._download_thread.request_cancel()
            self._download_thread.wait()
        self._artifact_service.close()

    def append_log(self, message: str) -> None:
        self._log_service.append_message(message)

    def on_pipeline_event(self, event) -> None:
        self._log_service.append_event(event)
        self.stage_inspector.on_pipeline_event(event)

    def _load_pipeline_config(self, preset: str) -> Dict[str, object]:
        return self._pipeline_settings.load(preset).config_data

    def _refresh_stage_view_models(self) -> None:
        stages = [self._build_stage_view_model(stage_id) for stage_id in PIPELINE_STAGE_ORDER]
        self.pipeline_chain.set_stages(stages)
        if self._active_stage_id:
            stage = next((item for item in stages if item.stage_id == self._active_stage_id), None)
            if stage:
                self.stage_inspector.set_stage(stage)

    def _build_stage_view_model(self, stage_id: str) -> StageViewModel:
        stage_state = self._stage_states.get(stage_id, StageRuntimeState())
        is_enabled = not self._is_stage_disabled(stage_id)
        status = stage_state.status
        if not is_enabled:
            status = "disabled"
        if stage_id == "input":
            files = self.files_panel.files()
            can_run = bool(files)
            status = "completed" if files else "idle"
            input_settings = {}
            ui_block = self._config_data.get("ui", {})
            if isinstance(ui_block, dict):
                raw = ui_block.get("input", {})
                if isinstance(raw, dict):
                    input_settings = dict(raw)
            current_settings = dict(input_settings)
            current_settings["files"] = list(files)
            return StageViewModel(
                stage_id=stage_id,
                display_name=_stage_display_name(stage_id),
                short_name=_stage_short_name(stage_id),
                status=status,
                progress=None,
                is_enabled=True,
                is_dirty=stage_state.dirty,
                is_blocked=False,
                warnings=list(stage_state.warnings),
                error=stage_state.error,
                plugin_id="",
                plugin_options=[],
                inline_settings_keys=[],
                settings_schema=[],
                current_settings=current_settings,
                effective_settings=current_settings,
                ui_metadata={
                    "formats_hint": "wav, mp3, m4a, mp4, mkv, webm, flac, ogg",
                },
                artifacts=[],
                can_run=can_run,
                can_rerun=can_run,
            )
        stage_config = self._config_data.get("stages", {}).get(stage_id, {})
        plugin_id = str(stage_config.get("plugin_id", "")).strip()
        schema = self._schema_for(plugin_id)
        inline_keys = self._inline_settings_keys(stage_config, schema)
        current_settings = stage_config.get("params", {}) if isinstance(stage_config, dict) else {}
        defaults = self._schema_defaults(plugin_id)
        effective = dict(defaults)
        effective.update(current_settings)
        artifacts = self._stage_artifacts(stage_id)
        plugin_options = [
            SettingOption(label=label, value=pid) for pid, label in self._stage_plugin_options(stage_id)
        ]
        ui_metadata: Dict[str, object] = {}
        if stage_id == "llm_processing":
            providers = self._llm_providers()
            selected_providers = current_settings.get("selected_providers", [])
            if isinstance(selected_providers, list):
                selected_provider = str(selected_providers[0]) if selected_providers else ""
            else:
                selected_provider = ""
            if not selected_provider and providers:
                selected_provider = providers[0][0]
            ui_metadata = {
                "providers": providers,
                "selected_provider": selected_provider,
                "models": self._models_for_provider(selected_provider) if selected_provider else [],
                "prompt_presets": self._prompt_presets(),
            }
        return StageViewModel(
            stage_id=stage_id,
            display_name=_stage_display_name(stage_id),
            short_name=_stage_short_name(stage_id),
            status=status,
            progress=stage_state.progress,
            is_enabled=is_enabled,
            is_dirty=stage_state.dirty,
            is_blocked=False,
            warnings=list(stage_state.warnings),
            error=stage_state.error,
            plugin_id=plugin_id,
            plugin_options=plugin_options,
            inline_settings_keys=inline_keys,
            settings_schema=schema,
            current_settings=current_settings,
            effective_settings=effective,
            ui_metadata=ui_metadata,
            artifacts=artifacts,
            can_run=is_enabled,
            can_rerun=is_enabled,
        )

    def _schema_for(self, plugin_id: str) -> List[SettingField]:
        schema = self._catalog.schema_for(plugin_id)
        if not schema:
            return []
        fields = []
        for setting in schema.settings:
            options = [
                SettingOption(label=opt.label, value=opt.value) for opt in (setting.options or [])
            ]
            fields.append(
                SettingField(
                    key=setting.key,
                    label=setting.label,
                    value=setting.value,
                    options=options,
                    editable=setting.editable,
                )
            )
        if plugin_id in _WHISPER_LOCAL_PLUGIN_IDS:
            installed = self._installed_whisper_models()
            fields = [
                SettingField(
                    key=field.key,
                    label=field.label,
                    value=field.value,
                    options=[SettingOption(label=item, value=item) for item in installed]
                    if field.key == "model"
                    else (
                        [
                            SettingOption(label="auto", value="auto"),
                            SettingOption(label="forced", value="forced"),
                            SettingOption(label="none", value="none"),
                        ]
                        if field.key == "language_mode"
                        else field.options
                    ),
                    editable=True if field.key == "model" else field.editable,
                )
                for field in fields
            ]
        return fields

    def _schema_defaults(self, plugin_id: str) -> Dict[str, object]:
        schema = self._catalog.schema_for(plugin_id)
        if not schema:
            return {}
        defaults: Dict[str, object] = {}
        for setting in schema.settings:
            value = _coerce_setting_value(setting.value)
            if _is_secret_field_name(setting.key) and (value is None or value == ""):
                continue
            defaults[setting.key] = value
        return defaults

    def _inline_settings_keys(self, stage_config: dict, schema: List[SettingField]) -> List[str]:
        ui = stage_config.get("ui", {}) if isinstance(stage_config, dict) else {}
        inline = ui.get("inline_settings")
        if isinstance(inline, list):
            return [str(item) for item in inline if str(item)]
        preferred = [
            "model",
            "model_id",
            "language_mode",
            "language_code",
            "auth_mode",
            "temperature",
        ]
        available = [field.key for field in schema]
        keys = [key for key in preferred if key in available]
        if not keys:
            keys = available[:2]
        return keys[:4]

    def _build_settings_service(self) -> PipelineSettingsUiService:
        return PipelineSettingsUiService(
            selected_plugin_provider=self._selected_plugin_id,
            plugin_options_provider=self._stage_plugin_options,
            defaults_provider=self._stage_defaults,
            custom_panel_factory=self._build_custom_panel,
        )

    def _selected_plugin_id(self, stage_id: str) -> str:
        stage = self._config_data.get("stages", {}).get(stage_id, {})
        return str(stage.get("plugin_id", "") or "")

    def _stage_plugin_options(self, stage_id: str) -> List[tuple[str, str]]:
        if stage_id in {"text_processing", "llm_processing", "media_convert"}:
            return []
        plugins = [
            plugin
            for plugin in self._catalog.plugins_for_stage(stage_id)
            if plugin.installed and (plugin.enabled or self._offline_mode)
        ]
        return [(plugin.plugin_id, self._catalog.display_name(plugin.plugin_id)) for plugin in plugins]

    def _stage_defaults(self, stage_id: str) -> Dict[str, object]:
        plugin_id = self._selected_plugin_id(stage_id)
        defaults = self._schema_defaults(plugin_id)
        if stage_id == "text_processing":
            defaults.setdefault("selected_models", [])
        if stage_id == "llm_processing":
            defaults.setdefault("selected_providers", [])
            defaults.setdefault("selected_models", {})
            prompt_settings = self._settings_store.get_settings(self._prompt_manager_plugin_id())
            if isinstance(prompt_settings, dict):
                profile_id = str(prompt_settings.get("active_profile", "")).strip()
                if profile_id:
                    defaults.setdefault("prompt_profile", profile_id)
            defaults.setdefault(
                "prompt_max_words", int(self._content.get("prompt_manager.max_words", default=600) or 600)
            )
        return defaults

    def _build_custom_panel(self, stage_id: str, parent: QWidget | None) -> QWidget | None:
        if stage_id == "input":
            return self.files_panel
        if stage_id == "text_processing":
            return _CompositeStagePanel(
                [
                    EditAlgorithmsPanel(self._edit_algorithms, parent=parent),
                    EmbeddingsExtrasPanel(
                        self._embeddings_status,
                        self._download_embeddings,
                        self._remove_embeddings,
                        parent=parent,
                    ),
                ],
                parent=parent,
            )
        if stage_id == "llm_processing":
            return LlmProviderPanel(
                self._llm_providers,
                self._models_for_provider,
                self._prompt_presets,
                parent=parent,
            )
        if stage_id == "transcription":
            return TranscriptionExtrasPanel(
                self._transcription_status,
                self._download_transcription_model,
                self._remove_transcription_model,
                parent=parent,
            )
        return None

    def _select_stage(self, stage_id: str) -> None:
        self._active_stage_id = stage_id
        self._refresh_stage_view_models()

    def _stage_settings_changed(self, stage_id: str, payload: dict) -> None:
        stage_config = self._config_data.setdefault("stages", {}).setdefault(stage_id, {})
        plugin_id = payload.get("plugin_id")
        if plugin_id:
            stage_config["plugin_id"] = plugin_id
            plugin = self._catalog.plugin_by_id(str(plugin_id))
            if plugin:
                stage_config["module"] = plugin.module
                stage_config["class"] = plugin.class_name
        params = payload.get("params")
        if isinstance(params, dict):
            effective_plugin_id = str(plugin_id or stage_config.get("plugin_id", "") or "").strip()
            if effective_plugin_id:
                stage_config["params"] = self._sanitize_params_for_plugin(effective_plugin_id, params)
            else:
                stage_config["params"] = dict(params)
        self._pipeline_settings.save(self._pipeline_preset, self._config_data)
        self._mark_dirty(stage_id)
        self._refresh_stage_view_models()

    def _inline_settings_changed(self, stage_id: str, settings: dict) -> None:
        if stage_id == "input":
            ui_block = self._config_data.setdefault("ui", {})
            input_settings = ui_block.get("input")
            if not isinstance(input_settings, dict):
                input_settings = {}
            input_settings.update(settings)
            ui_block["input"] = input_settings
            self._pipeline_settings.save(self._pipeline_preset, self._config_data)
            self._mark_dirty(stage_id)
            self._refresh_stage_view_models()
            return
        stage_config = self._config_data.setdefault("stages", {}).setdefault(stage_id, {})
        plugin_id = settings.pop("plugin_id", None)
        if plugin_id:
            stage_config["plugin_id"] = plugin_id
            plugin = self._catalog.plugin_by_id(str(plugin_id))
            if plugin:
                stage_config["module"] = plugin.module
                stage_config["class"] = plugin.class_name
        params = stage_config.get("params")
        if not isinstance(params, dict):
            params = {}
        params.update(settings)
        effective_plugin_id = str(stage_config.get("plugin_id", "") or "").strip()
        if effective_plugin_id:
            params = self._sanitize_params_for_plugin(effective_plugin_id, params)
        stage_config["params"] = params
        self._pipeline_settings.save(self._pipeline_preset, self._config_data)
        self._mark_dirty(stage_id)
        self._refresh_stage_view_models()

    def _stage_disabled_changed(self, stage_id: str, disabled: bool) -> None:
        pipeline = self._config_data.setdefault("pipeline", {})
        disabled_stages = pipeline.get("disabled_stages", [])
        if not isinstance(disabled_stages, list):
            disabled_stages = []
        if disabled and stage_id not in disabled_stages:
            disabled_stages.append(stage_id)
        if not disabled and stage_id in disabled_stages:
            disabled_stages.remove(stage_id)
        pipeline["disabled_stages"] = disabled_stages
        self._pipeline_settings.save(self._pipeline_preset, self._config_data)
        self._refresh_stage_view_models()

    def _preset_changed(self, preset_id: str) -> None:
        self._pipeline_preset = preset_id
        self._offline_mode = preset_id == OFFLINE_PRESET_ID
        self._pipeline_settings.save_active_preset(preset_id)
        self._config_data = self._load_pipeline_config(preset_id)
        self._refresh_stage_view_models()

    def _mark_dirty(self, stage_id: str) -> None:
        if stage_id not in PIPELINE_STAGE_ORDER:
            return
        stage_index = PIPELINE_STAGE_ORDER.index(stage_id)
        for idx in range(stage_index, len(PIPELINE_STAGE_ORDER)):
            self._stage_states[PIPELINE_STAGE_ORDER[idx]].dirty = True

    def _request_run_all(self) -> None:
        self.request_pipeline_run.emit(False)

    def _request_run_from(self, _stage_id: str) -> None:
        self.request_pipeline_run.emit(False)

    def _request_rerun(self, _stage_id: str) -> None:
        self.request_pipeline_run.emit(True)

    def _open_output_folder(self, stage_id: str) -> None:
        if stage_id != "service":
            return
        if not self._artifact_service.open_output_folder():
            QMessageBox.warning(None, "Output Folder Missing", "Output folder is not available yet.")

    def _open_customize_dialog(self) -> None:
        dialog = _StageCustomizeDialog(
            self.pipeline_chain.capture_presentation(),
            disabled_stages=set(self._config_data.get("pipeline", {}).get("disabled_stages", [])),
            parent=None,
        )
        if dialog.exec():
            presentation, disabled = dialog.presentation()
            for stage_id, state in presentation.items():
                self.pipeline_chain.set_stage_presentation(
                    stage_id, state.get("visible", True), state.get("density", "mini")
                )
            for stage_id in PIPELINE_STAGE_ORDER:
                self._stage_disabled_changed(stage_id, stage_id in disabled)

    def show_customize_dialog(self) -> None:
        self._open_customize_dialog()

    def _on_meeting_selected(self, meeting) -> None:
        self._current_meeting = meeting
        self.set_stage_results(meeting)
        self._refresh_stage_view_models()

    def _on_files_changed(self) -> None:
        self._stage_states["input"].dirty = False
        self._mark_dirty("input")
        self._refresh_stage_view_models()

    def _retry_failed_stages(self, meeting) -> None:
        if not meeting.pipeline_runs:
            return
        last_run = meeting.pipeline_runs[-1]
        failed = [stage.stage_id for stage in last_run.stages if stage.status == "failed"]
        if not failed:
            return
        files = [item.input_path for item in meeting.source.items if item.input_path]
        if files:
            self.files_panel.set_files(files)
        self._log_service.append_message(f"Retrying failed stages: {', '.join(failed)}")
        self.request_pipeline_run.emit(True)

    def _stage_artifacts(self, stage_id: str) -> List[dict]:
        if not self._current_meeting:
            return []
        artifacts = self._artifact_service.list_artifacts(self._current_meeting)
        entries = []
        for item in artifacts:
            if item.stage_id != stage_id:
                continue
            entries.append(
                {
                    "relpath": item.relpath,
                    "label": f"{item.kind} ({item.alias or 'default'})",
                }
            )
        return entries

    def _build_edit_variants(self) -> tuple[List[Dict[str, object]], Dict[str, object]]:
        stage = self._config_data.get("stages", {}).get("text_processing", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        selected = params.get("selected_models", [])
        selected_models = [str(item) for item in selected if str(item)]
        if not selected_models:
            defaults = self._edit_algorithms()
            if defaults:
                selected_models = [defaults[0][1]]
        variants: List[Dict[str, object]] = []
        for plugin_id in selected_models:
            plugin = self._catalog.plugin_by_id(plugin_id)
            if not plugin:
                continue
            base_params = self._schema_defaults(plugin_id)
            for key, value in params.items():
                if key == "selected_models":
                    continue
                base_params[key] = value
            variants.append(
                {
                    "plugin_id": plugin.plugin_id,
                    "module": plugin.module,
                    "class": plugin.class_name,
                    "params": base_params,
                }
            )
        return variants, {"selected_models": selected_models}

    def _build_summary_variants(self) -> tuple[List[Dict[str, object]], Dict[str, object]]:
        stage = self._config_data.get("stages", {}).get("llm_processing", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        selected_providers = [
            str(provider_id)
            for provider_id in params.get("selected_providers", [])
            if str(provider_id)
        ]
        selected_models = params.get("selected_models", {})
        if not isinstance(selected_models, dict):
            selected_models = {}
        variants: List[Dict[str, object]] = []
        for provider_id in selected_providers:
            plugin = self._catalog.plugin_by_id(provider_id)
            if not plugin:
                continue
            base_params = self._schema_defaults(provider_id)
            for key, value in params.items():
                if key in {"selected_providers", "selected_models", "prompt_profile", "prompt_custom", "prompt_language", "prompt_max_words"}:
                    continue
                base_params[key] = value
            prompt_profile = str(params.get("prompt_profile", "")).strip()
            if prompt_profile:
                base_params["prompt_profile"] = prompt_profile
                base_params["prompt_custom"] = str(params.get("prompt_custom", "")).strip()
                base_params["prompt_language"] = str(params.get("prompt_language", "")).strip()
                max_words = params.get("prompt_max_words", 0)
                try:
                    base_params["prompt_max_words"] = int(max_words)
                except Exception:
                    base_params["prompt_max_words"] = 0
            models = selected_models.get(provider_id, [])
            if not models:
                models = [self._models_for_provider(provider_id)[0][1]] if self._models_for_provider(provider_id) else []
            if not models:
                variants.append(
                    {
                        "plugin_id": plugin.plugin_id,
                        "module": plugin.module,
                        "class": plugin.class_name,
                        "params": base_params,
                    }
                )
                continue
            for model_id in models:
                params = dict(base_params)
                if model_id != "default":
                    params["model_id"] = model_id
                variants.append(
                    {
                        "plugin_id": plugin.plugin_id,
                        "module": plugin.module,
                        "class": plugin.class_name,
                        "params": params,
                    }
                )
        summary_params = {
            "selected_providers": selected_providers,
            "selected_models": selected_models,
            "prompt_profile": params.get("prompt_profile", ""),
            "prompt_custom": params.get("prompt_custom", ""),
            "prompt_language": params.get("prompt_language", ""),
            "prompt_max_words": params.get("prompt_max_words", 0),
        }
        return variants, summary_params

    def _edit_algorithms(self) -> List[tuple[str, str]]:
        plugins = [
            plugin
            for plugin in self._catalog.plugins_for_stage("text_processing")
            if plugin.installed and (plugin.enabled or self._offline_mode)
        ]
        return [(self._catalog.display_name(plugin.plugin_id), plugin.plugin_id) for plugin in plugins]

    def _llm_providers(self) -> List[tuple[str, str]]:
        plugins = [
            plugin
            for plugin in self._catalog.plugins_for_stage("llm_processing")
            if plugin.installed and (plugin.enabled or self._offline_mode)
        ]
        return [(plugin.plugin_id, self._catalog.display_name(plugin.plugin_id)) for plugin in plugins]

    def _models_for_provider(self, provider_id: str) -> List[tuple[str, str]]:
        defaults = [("Default", "default")]
        if not provider_id:
            return defaults
        settings = self._settings_store.get_settings(provider_id)
        raw_models = settings.get("models", []) if isinstance(settings, dict) else []
        models: List[tuple[str, str]] = []
        if isinstance(raw_models, list):
            for entry in raw_models:
                if not isinstance(entry, dict):
                    continue
                if not entry.get("enabled", True):
                    continue
                model_id = str(entry.get("model_id", "")).strip()
                if not model_id:
                    continue
                label = str(entry.get("product_name", "")).strip() or model_id
                models.append((label, model_id))
        return models or defaults

    def _prompt_presets(self) -> List[dict]:
        presets = []
        raw = self._content.get("prompt_manager.presets", default=[])
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                preset_id = str(entry.get("id", "")).strip()
                if not preset_id:
                    continue
                label = str(entry.get("label", preset_id)).strip() or preset_id
                prompt = str(entry.get("prompt", "")).strip()
                if not prompt:
                    continue
                    presets.append({"id": preset_id, "label": label, "prompt": prompt})
        settings = self._settings_store.get_settings(self._prompt_manager_plugin_id())
        if isinstance(settings, dict):
            raw_presets = settings.get("presets", [])
            if isinstance(raw_presets, list):
                presets = []
                for entry in raw_presets:
                    if not isinstance(entry, dict):
                        continue
                    preset_id = str(entry.get("id", "")).strip()
                    if not preset_id:
                        continue
                    label = str(entry.get("label", preset_id)).strip() or preset_id
                    prompt = str(entry.get("prompt", "")).strip()
                    if not prompt:
                        continue
                    presets.append({"id": preset_id, "label": label, "prompt": prompt})
        return presets

    def _prompt_manager_plugin_id(self) -> str:
        """
        Discover prompt manager plugin via declared capabilities.

        Isolated architecture rule: UI must not know specific plugin_id values.
        """
        for plugin in self._catalog.all_plugins():
            caps = plugin.capabilities if isinstance(getattr(plugin, "capabilities", None), dict) else {}
            if isinstance(caps, dict) and bool(caps.get("prompt_manager", False)):
                return str(plugin.plugin_id or "").strip()
        return ""

    def _transcription_status(self) -> str:
        stage = self._config_data.get("stages", {}).get("transcription", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        plugin_id = str(stage.get("plugin_id", "")).strip()
        if plugin_id and plugin_id not in _WHISPER_LOCAL_PLUGIN_IDS:
            return "n/a"
        model = str(params.get("model", "")).strip()
        installed = model in self._installed_whisper_models()
        return "installed" if installed else "missing"

    def _download_transcription_model(self) -> None:
        stage = self._config_data.get("stages", {}).get("transcription", {})
        plugin_id = str(stage.get("plugin_id", "")).strip()
        if plugin_id and plugin_id not in _WHISPER_LOCAL_PLUGIN_IDS:
            return
        models = list(self._whisper_model_files().keys())
        if not models:
            QMessageBox.warning(None, "Missing models", "No models are available for download.")
            return
        current = models[0]
        model, ok = QInputDialog.getItem(
            None,
            "Download Model",
            "Model",
            models,
            models.index(current),
            False,
        )
        if not ok or not model:
            return
        url = self._default_model_url(model)
        if not url:
            QMessageBox.warning(None, "Missing URL", f"No URL for model: {model}")
            return
        if self._download_thread and self._download_thread.isRunning():
            QMessageBox.information(None, "Download running", "Model download already in progress.")
            return
        from aimn.ui.model_downloads import ModelDownloadThread

        models_dir = self._transcription_models_dir()
        root = Path(models_dir) if models_dir else (self._app_root / "models" / "whisper")
        target_name = self._whisper_model_files().get(model, "")
        if not target_name:
            QMessageBox.warning(None, "Missing file mapping", f"No file mapping for model: {model}")
            return
        target_path = root / target_name
        self._download_thread = ModelDownloadThread(model, url, target_path=target_path)
        self._download_thread.log.connect(self._log_service.append_message)
        self._download_thread.progress.connect(lambda value: self._log_service.append_message(f"Download {value}%"))
        self._download_thread.failed.connect(lambda message: QMessageBox.warning(None, "Download failed", message))
        self._download_thread.finished_ok.connect(lambda _m: self._refresh_stage_view_models())
        self._download_thread.start()

    def _remove_transcription_model(self) -> None:
        stage = self._config_data.get("stages", {}).get("transcription", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        model = str(params.get("model", "")).strip()
        if not model:
            return
        models_dir = self._transcription_models_dir()
        root = Path(models_dir) if models_dir else (self._app_root / "models" / "whisper")
        filename = self._whisper_model_files().get(model, "")
        if not filename:
            return
        target = root / filename
        if target.exists():
            target.unlink()

    def _embeddings_status(self) -> str:
        stage = self._config_data.get("stages", {}).get("text_processing", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        plugin_id = str(stage.get("plugin_id", "")).strip()
        if plugin_id not in {
            "text_processing.minutes_heuristic_v2",
        }:
            return "n/a"
        model_id = str(params.get("model_id") or params.get("embeddings_model_id") or "").strip()
        models_dir = self._app_root / "models" / "embeddings"
        try:
            from aimn.core.api import embeddings_available
        except Exception:
            return "missing"
        return "installed" if embeddings_available(model_id=model_id or None, model_path=None, app_root=self._app_root) else "missing"

    def _download_embeddings(self) -> None:
        stage = self._config_data.get("stages", {}).get("text_processing", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        plugin_id = str(stage.get("plugin_id", "")).strip()
        if plugin_id not in {
            "text_processing.minutes_heuristic_v2",
        }:
            return
        model_id = str(params.get("model_id") or params.get("embeddings_model_id") or "").strip()
        if not model_id:
            QMessageBox.warning(None, "Missing Model ID", "No embeddings model id configured.")
            return
        from aimn.ui.model_downloads import TextModelDownloadThread

        self._download_thread = TextModelDownloadThread(
            model_kind="embeddings",
            target_path=str(self._app_root / "models" / "embeddings"),
            url=model_id,
        )
        self._download_thread.log.connect(self._log_service.append_message)
        self._download_thread.failed.connect(lambda message: QMessageBox.warning(None, "Download failed", message))
        self._download_thread.finished_ok.connect(lambda _m: self._refresh_stage_view_models())
        self._download_thread.start()

    def _remove_embeddings(self) -> None:
        stage = self._config_data.get("stages", {}).get("text_processing", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        plugin_id = str(stage.get("plugin_id", "")).strip()
        if plugin_id not in {
            "text_processing.minutes_heuristic_v2",
        }:
            return
        model_id = str(params.get("model_id") or params.get("embeddings_model_id") or "").strip()
        models_dir = self._app_root / "models" / "embeddings"
        if not model_id:
            return
        slug = model_id.replace("/", "_")
        direct = models_dir / slug
        if direct.exists():
            for path in direct.rglob("*"):
                if path.is_file():
                    path.unlink()
            for path in sorted(direct.rglob("*"), reverse=True):
                if path.is_dir():
                    path.rmdir()
            if direct.exists():
                direct.rmdir()

    def _is_stage_disabled(self, stage_id: str) -> bool:
        pipeline = self._config_data.get("pipeline", {})
        disabled = pipeline.get("disabled_stages", []) if isinstance(pipeline, dict) else []
        return stage_id in disabled

    def _whisper_model_files(self) -> Dict[str, str]:
        active = self._active_whisper_plugin_id()
        for plugin_id in (
            active,
            "transcription.whisperadvanced",
        ):
            mapping = self._models_service.model_files(plugin_id)
            if mapping:
                return mapping
        return {
            "tiny": "ggml-tiny.bin",
            "base": "ggml-base.bin",
            "small": "ggml-small.bin",
            "medium": "ggml-medium.bin",
            "large": "ggml-large.bin",
        }

    def _active_whisper_plugin_id(self) -> str:
        stage = self._config_data.get("stages", {}).get("transcription", {})
        plugin_id = str(stage.get("plugin_id", "")).strip()
        if plugin_id in _WHISPER_LOCAL_PLUGIN_IDS:
            return plugin_id
        return "transcription.whisperadvanced"

    def _transcription_models_dir(self) -> str | None:
        stage = self._config_data.get("stages", {}).get("transcription", {})
        params = stage.get("params", {}) if isinstance(stage, dict) else {}
        raw = str(params.get("models_dir", "")).strip()
        return raw or None

    def _installed_whisper_models(self) -> List[str]:
        model_files = self._whisper_model_files()
        models_dir = self._transcription_models_dir()
        root = Path(models_dir) if models_dir else (self._app_root / "models" / "whisper")
        return [
            model_id
            for model_id, filename in model_files.items()
            if (root / filename).exists()
        ]

    def _default_model_url(self, model: str) -> str:
        return {
            "tiny": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
            "base": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
            "small": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
            "medium": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
            "large": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large.bin",
        }.get(model, "")

    def _sanitize_params_for_plugin(self, plugin_id: str, params: dict) -> Dict[str, object]:
        if not isinstance(params, dict):
            return {}
        plugin_key = str(plugin_id or "").strip()
        if not plugin_key:
            return dict(params)
        schema = self._catalog.schema_for(plugin_key)
        if not schema:
            return dict(params)
        allowed = {
            str(setting.key).strip()
            for setting in schema.settings
            if str(setting.key).strip()
        }
        if not allowed:
            return {}
        return {
            str(key): value
            for key, value in params.items()
            if str(key).strip() in allowed
        }


def _stage_display_name(stage_id: str) -> str:
    names = {
        "input": "Input",
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
    except Exception:
        return value


def _is_mock_plugin(plugin_id: str) -> bool:
    lowered = plugin_id.lower()
    return ".fake" in lowered or ".mock" in lowered


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
    return lowered.startswith("key_") or lowered.endswith("_key") or lowered.endswith("_keys")


class _StageCustomizeDialog(QDialog):
    def __init__(
        self,
        presentation: Dict[str, dict],
        *,
        disabled_stages: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Stage Chain")
        self._presentation = {key: dict(value) for key, value in presentation.items()}
        self._rows: Dict[str, tuple[QComboBox, QComboBox, QComboBox]] = {}
        self._disabled = set(disabled_stages)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        for stage_id in PIPELINE_STAGE_ORDER:
            state = self._presentation.get(stage_id, {"visible": True, "density": "mini"})
            visible = QComboBox()
            visible.addItem("Visible", True)
            visible.addItem("Hidden", False)
            visible_index = 0 if state.get("visible", True) else 1
            visible.setCurrentIndex(visible_index)

            density = QComboBox()
            density.addItem("Collapsed", "collapsed")
            density.addItem("Mini", "mini")
            density.addItem("Full", "full")
            density_key = str(state.get("density", "mini"))
            density_index = density.findData(density_key)
            if density_index >= 0:
                density.setCurrentIndex(density_index)

            disabled = QComboBox()
            disabled.addItem("Enabled", False)
            disabled.addItem("Disabled", True)
            disabled.setCurrentIndex(1 if stage_id in self._disabled else 0)

            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(visible)
            row_layout.addWidget(density)
            row_layout.addWidget(disabled)
            form.addRow(QLabel(stage_id), row)
            self._rows[stage_id] = (visible, density, disabled)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def presentation(self) -> tuple[Dict[str, dict], set[str]]:
        disabled = set()
        for stage_id, (visible, density, disabled_combo) in self._rows.items():
            self._presentation[stage_id] = {
                "visible": bool(visible.currentData()),
                "density": str(density.currentData()),
            }
            if disabled_combo.currentData():
                disabled.add(stage_id)
        return dict(self._presentation), disabled


class _CompositeStagePanel(QWidget):
    def __init__(self, panels: List[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._panels = panels
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for panel in panels:
            layout.addWidget(panel)

    def apply_stage(self, stage) -> None:
        for panel in self._panels:
            if hasattr(panel, "apply_stage"):
                panel.apply_stage(stage)

    def collect_settings(self) -> dict:
        merged: dict = {}
        for panel in self._panels:
            if hasattr(panel, "collect_settings"):
                data = panel.collect_settings()
                if isinstance(data, dict):
                    merged.update(data)
        return merged

    def set_density(self, density: str) -> None:
        for panel in self._panels:
            level = str(panel.property("density_level") or "")
            if density == "collapsed":
                panel.setVisible(False)
            elif density == "mini":
                panel.setVisible(level != "advanced")
            else:
                panel.setVisible(True)
            if hasattr(panel, "set_density"):
                panel.set_density(density)
