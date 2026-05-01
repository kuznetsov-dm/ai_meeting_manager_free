from __future__ import annotations

from collections.abc import Callable
import re

from aimn.ui.controllers.stage_model_normalization import parse_variant_selection_state
from aimn.ui.controllers.stage_runtime_controller import StageRuntimeState
from aimn.ui.tabs.contracts import SettingOption, StageViewModel


class StageViewModelComposer:
    def __init__(
        self,
        *,
        current_stage_states: Callable[[], dict[str, StageRuntimeState]],
        is_stage_disabled: Callable[[str], bool],
        stage_display_name: Callable[[str], str],
        stage_short_name: Callable[[str], str],
        config_data_provider: Callable[[], dict],
        input_files_provider: Callable[[], list[str]],
        active_meeting_base_name_provider: Callable[[], str],
        active_meeting_source_path_provider: Callable[[], str],
        stage_plugin_options: Callable[[str], list[tuple[str, str]]],
        stage_defaults: Callable[[str], dict],
        schema_for: Callable[[str, str], list],
        inline_settings_keys: Callable[[dict, list], list[str]],
        supports_transcription_quality_presets: Callable[[str], bool],
        order_transcription_providers: Callable[[list[tuple[str, str]]], list[tuple[str, str]]],
        whisper_models_state: Callable[[], tuple[list[str], list[str]]],
        text_processing_provider_group: Callable[[str], str],
        plugin_available: Callable[[str], bool],
        llm_enabled_models_from_stage: Callable[..., tuple[dict[str, list[str]], str]],
        llm_provider_models_payload: Callable[..., dict[str, list[dict]]],
        get_catalog: Callable[[], object],
        current_meeting_provider: Callable[[], object | None],
        normalize_ui_status: Callable[..., tuple[str, str | None]],
    ) -> None:
        self._current_stage_states = current_stage_states
        self._is_stage_disabled = is_stage_disabled
        self._stage_display_name = stage_display_name
        self._stage_short_name = stage_short_name
        self._config_data_provider = config_data_provider
        self._input_files_provider = input_files_provider
        self._active_meeting_base_name_provider = active_meeting_base_name_provider
        self._active_meeting_source_path_provider = active_meeting_source_path_provider
        self._stage_plugin_options = stage_plugin_options
        self._stage_defaults = stage_defaults
        self._schema_for = schema_for
        self._inline_settings_keys = inline_settings_keys
        self._supports_transcription_quality_presets = supports_transcription_quality_presets
        self._order_transcription_providers = order_transcription_providers
        self._whisper_models_state = whisper_models_state
        self._text_processing_provider_group = text_processing_provider_group
        self._plugin_available = plugin_available
        self._llm_enabled_models_from_stage = llm_enabled_models_from_stage
        self._llm_provider_models_payload = llm_provider_models_payload
        self._get_catalog = get_catalog
        self._current_meeting_provider = current_meeting_provider
        self._normalize_ui_status = normalize_ui_status

    def build_stage_view_model(self, stage_id: str) -> StageViewModel:
        states = self._current_stage_states()
        state = states.get(stage_id, StageRuntimeState())
        is_enabled = not self._is_stage_disabled(stage_id)
        has_input = bool(self._input_files_provider())

        status = (state.status or "idle").lower()
        if status == "finished":
            status = "completed"
        if not is_enabled:
            status = "disabled"

        progress = state.progress
        error = state.error or None

        config_data = self._config_data_provider()

        if stage_id == "media_convert":
            if status not in {"running", "completed", "failed", "skipped", "disabled"}:
                if not is_enabled:
                    status = "disabled"
                else:
                    status = "ready" if has_input else "idle"
            stage_config = config_data.get("stages", {}).get(stage_id, {})
            if not isinstance(stage_config, dict):
                stage_config = {}
            current_settings = stage_config.get("params", {})
            if not isinstance(current_settings, dict):
                current_settings = {}
            defaults = {"channels": "1", "sample_rate_hz": "16000", "normalize": False}
            effective = dict(defaults)
            effective.update(current_settings)
            schema = [
                {
                    "key": "channels",
                    "label": "Channels",
                    "value": defaults["channels"],
                    "options": [
                        SettingOption(label="Mono (1)", value="1"),
                        SettingOption(label="Stereo (2)", value="2"),
                    ],
                    "editable": True,
                },
                {
                    "key": "sample_rate_hz",
                    "label": "Sample rate",
                    "value": defaults["sample_rate_hz"],
                    "options": [
                        SettingOption(label="16000", value="16000"),
                        SettingOption(label="44100", value="44100"),
                        SettingOption(label="48000", value="48000"),
                    ],
                    "editable": True,
                },
                {
                    "key": "normalize",
                    "label": "Normalize (loudnorm)",
                    "value": defaults["normalize"],
                    "options": [],
                    "editable": True,
                },
            ]
            ui_metadata: dict[str, object] = {}
            if (
                self._active_meeting_base_name_provider()
                and self._active_meeting_source_path_provider()
                and is_enabled
            ):
                ui_metadata["attention"] = True
            from aimn.ui.tabs.contracts import (
                SettingField,  # local import to avoid heavy top-level cycles
            )

            settings_schema = [
                SettingField(
                    key=item["key"],
                    label=item["label"],
                    value=item["value"],
                    options=item["options"],
                    editable=item["editable"],
                )
                for item in schema
            ]
            return StageViewModel(
                stage_id=stage_id,
                display_name=self._stage_display_name(stage_id),
                short_name=self._stage_short_name(stage_id),
                status=status,
                progress=progress,
                is_enabled=is_enabled,
                is_dirty=state.dirty,
                is_blocked=False,
                warnings=[],
                error=error,
                plugin_id="",
                plugin_options=[],
                inline_settings_keys=["channels", "sample_rate_hz", "normalize"],
                settings_schema=settings_schema,
                current_settings=effective,
                effective_settings=effective,
                ui_metadata=ui_metadata,
                artifacts=[],
                can_run=is_enabled,
                can_rerun=is_enabled,
            )

        stage_config = config_data.get("stages", {}).get(stage_id, {})
        if not isinstance(stage_config, dict):
            stage_config = {}
        plugin_id = str(stage_config.get("plugin_id", "")).strip()
        stage_plugin_ids = [
            str(item).strip()
            for item in list(stage_config.get("plugin_ids", []) or [])
            if str(item).strip()
        ]
        variants = stage_config.get("variants", [])
        variant_state = parse_variant_selection_state(variants)
        variant_plugin_ids = list(variant_state.plugin_ids)
        variant_params_by_plugin = dict(variant_state.params_by_plugin)
        variant_models_by_plugin = dict(variant_state.model_ids_by_plugin)
        warnings: list[str] = []
        if stage_id == "llm_processing":
            candidate_ids = variant_plugin_ids or ([plugin_id] if plugin_id else [])
            if candidate_ids and not any(pid for pid in candidate_ids):
                warnings.append("llm_provider_missing")
            text_stage_config = config_data.get("stages", {}).get("text_processing", {})
            if not isinstance(text_stage_config, dict):
                text_stage_config = {}
            text_plugin_id = str(text_stage_config.get("plugin_id", "") or "").strip()
            text_variant_plugin_ids = parse_variant_selection_state(text_stage_config.get("variants", [])).plugin_ids
            candidate_ids.extend(text_variant_plugin_ids or ([text_plugin_id] if text_plugin_id else []))
            hidden_state = states.get("text_processing")
            llm_status = str(state.status or "").strip().lower()
            if (
                hidden_state
                and llm_status not in {"running", "completed", "failed", "skipped"}
                and str(hidden_state.status or "").strip().lower() in {"running", "failed"}
            ):
                status = str(hidden_state.status or "").strip().lower()
                progress = hidden_state.progress
                error = hidden_state.error or error

        if stage_id == "transcription":
            selected_transcription_plugin = plugin_id
            if not selected_transcription_plugin and variant_plugin_ids:
                selected_transcription_plugin = variant_plugin_ids[0]
            if selected_transcription_plugin and selected_transcription_plugin in variant_params_by_plugin:
                current_settings = dict(variant_params_by_plugin[selected_transcription_plugin])
            else:
                current_settings = stage_config.get("params", {})
                if not isinstance(current_settings, dict):
                    current_settings = {}
            plugin_id = selected_transcription_plugin
        else:
            current_settings = stage_config.get("params", {})
            if not isinstance(current_settings, dict):
                current_settings = {}

        schema = self._schema_for(plugin_id, stage_id)
        ui_current_settings = dict(current_settings)
        if stage_id == "transcription" and self._supports_transcription_quality_presets(plugin_id):
            mode = str(ui_current_settings.get("language_mode", "") or "").strip()
            if mode == "auto_two_pass":
                ui_current_settings["language_mode"] = "auto"
                ui_current_settings["two_pass"] = True
        if stage_id == "transcription" and plugin_id:
            ui_current_settings["plugin_id"] = plugin_id
        defaults = self._stage_defaults(stage_id)
        effective = dict(defaults)
        effective.update(current_settings)
        ui_effective = dict(effective)
        if stage_id == "transcription" and self._supports_transcription_quality_presets(plugin_id):
            mode = str(ui_effective.get("language_mode", "") or "").strip()
            if mode == "auto_two_pass":
                ui_effective["language_mode"] = "auto"
                ui_effective["two_pass"] = True

        plugin_options = [SettingOption(label=label, value=pid) for pid, label in self._stage_plugin_options(stage_id)]
        inline_keys = self._inline_settings_keys(stage_config, schema)
        ui_metadata: dict[str, object] = {}
        if (
            self._active_meeting_base_name_provider()
            and self._active_meeting_source_path_provider()
            and is_enabled
        ):
            ui_metadata["attention"] = True

        if stage_id in {"transcription", "text_processing", "llm_processing"}:
            schema = []
            inline_keys = []
            plugin_options = []
            ui_metadata["hide_provider_row"] = True

        if stage_id == "transcription":
            providers = [(pid, label) for pid, label in self._stage_plugin_options(stage_id)]
            providers = self._order_transcription_providers(providers)
            installed, _known = self._whisper_models_state()
            preset_providers = [pid for pid, _label in providers if self._supports_transcription_quality_presets(pid)]
            enabled_seen: set[str] = set()
            enabled_providers = []
            for pid, _label in providers:
                if pid not in set(variant_plugin_ids):
                    continue
                if pid in enabled_seen:
                    continue
                enabled_seen.add(pid)
                enabled_providers.append(pid)
            if not enabled_providers and plugin_id:
                enabled_providers = [plugin_id]
            selected_provider = plugin_id or (enabled_providers[0] if enabled_providers else "")
            if not selected_provider and providers:
                selected_provider = providers[0][0]
            ui_metadata.update(
                {
                    "available_providers": providers,
                    "selected_provider": selected_provider,
                    "enabled_providers": enabled_providers,
                    "provider_params": variant_params_by_plugin,
                    "selected_models": variant_models_by_plugin,
                    "installed_models": installed,
                    "transcription_preset_providers": preset_providers,
                }
            )

        if stage_id == "text_processing":
            enabled_ids = list(variant_plugin_ids) if variant_plugin_ids else ([plugin_id] if plugin_id else [])
            enabled_set = set([pid for pid in enabled_ids if pid])
            provider_id = "semantic"
            provider_models: dict[str, list[dict]] = {provider_id: []}

            for pid, label in self._stage_plugin_options(stage_id):
                plugin = self._get_catalog().plugin_by_id(pid)
                tooltip = ""
                if plugin:
                    tooltip = str(plugin.highlights or plugin.description or "").strip()
                provider_models.setdefault(provider_id, []).append(
                    {
                        "plugin_id": pid,
                        "label": label,
                        "tooltip": tooltip,
                    }
                )

            available_providers = [(provider_id, "Semantic")] if provider_models.get(provider_id) else []
            enabled_map = {
                provider_id: [
                    entry["plugin_id"]
                    for entry in provider_models.get(provider_id, [])
                    if entry.get("plugin_id") in enabled_set
                ]
            }
            selected_provider = provider_id if available_providers else ""

            ui_metadata.update(
                {
                    "available_providers": available_providers,
                    "provider_models": provider_models,
                    "enabled_models": enabled_map,
                    "selected_provider": selected_provider,
                }
            )

        if stage_id == "llm_processing":
            providers = [(pid, label) for pid, label in self._stage_plugin_options(stage_id)]
            semantic_providers: list[tuple[str, str]] = []
            llm_providers: list[tuple[str, str]] = []
            for pid, label in providers:
                if self._text_processing_provider_group(pid):
                    semantic_providers.append((pid, label))
                else:
                    llm_providers.append((pid, label))
            text_stage_config = config_data.get("stages", {}).get("text_processing", {})
            if not isinstance(text_stage_config, dict):
                text_stage_config = {}
            semantic_enabled_ids: list[str] = []
            text_variant_state = parse_variant_selection_state(text_stage_config.get("variants"))
            if text_variant_state.plugin_ids:
                semantic_enabled_ids.extend(text_variant_state.plugin_ids)
            elif str(text_stage_config.get("plugin_id", "") or "").strip():
                semantic_enabled_ids.append(str(text_stage_config.get("plugin_id", "") or "").strip())

            semantic_provider_id = "semantic"
            semantic_provider_models: dict[str, list[dict]] = {semantic_provider_id: []}
            enabled_semantic = {pid for pid in semantic_enabled_ids if pid}
            for pid, label in semantic_providers:
                plugin = self._get_catalog().plugin_by_id(pid)
                tooltip = ""
                if plugin:
                    tooltip = str(plugin.highlights or plugin.description or "").strip()
                semantic_provider_models.setdefault(semantic_provider_id, []).append(
                    {"plugin_id": pid, "label": label, "tooltip": tooltip}
                )
            semantic_available_providers = (
                [(semantic_provider_id, "Semantic")] if semantic_provider_models.get(semantic_provider_id) else []
            )
            semantic_enabled_map: dict[str, list[str]] = {
                semantic_provider_id: [
                    entry["plugin_id"]
                    for entry in semantic_provider_models.get(semantic_provider_id, [])
                    if entry.get("plugin_id") in enabled_semantic
                ]
            }
            semantic_selected_provider = semantic_provider_id if semantic_available_providers else ""

            enabled_models, selected_provider = self._llm_enabled_models_from_stage(
                plugin_id=plugin_id,
                stage_params=current_settings,
                variants=variants,
                providers=[pid for pid, _label in llm_providers],
            )
            ui_metadata.update(
                {
                    "available_providers": llm_providers,
                    "provider_models": self._llm_provider_models_payload(
                        [pid for pid, _label in llm_providers],
                        enabled_models=enabled_models,
                        available_only=False,
                    ),
                    "enabled_models": enabled_models,
                    "selected_provider": selected_provider,
                    "refreshable_providers": [
                        pid for pid, _label in llm_providers if self._provider_supports_model_refresh(pid)
                    ],
                    "semantic_available_providers": semantic_available_providers,
                    "semantic_provider_models": semantic_provider_models,
                    "semantic_enabled_models": semantic_enabled_map,
                    "semantic_selected_provider": semantic_selected_provider,
                }
            )
            if status != "running":
                mock_summary, mock_reason = self._stage_mock_summary_state(stage_id)
                if mock_summary:
                    ui_metadata["mock_summary"] = True
                if mock_reason:
                    ui_metadata["mock_summary_reason"] = mock_reason
                    ui_metadata["mock_summary_reason_label"] = _format_warning_for_display(mock_reason)

        if status not in {"running", "completed", "failed", "skipped", "disabled"}:
            configured_plugin_ids = variant_plugin_ids or stage_plugin_ids or ([plugin_id] if plugin_id else [])
            effective_plugin_id = plugin_id or (configured_plugin_ids[0] if configured_plugin_ids else "")
            configured_ok = False
            if has_input and is_enabled:
                if plugin_id and self._plugin_available(plugin_id):
                    configured_ok = True
                elif configured_plugin_ids:
                    configured_ok = any(self._plugin_available(pid) for pid in configured_plugin_ids)
                elif stage_id == "llm_processing":
                    text_stage_config = config_data.get("stages", {}).get("text_processing", {})
                    if isinstance(text_stage_config, dict):
                        text_variants = text_stage_config.get("variants")
                        if isinstance(text_variants, list):
                            if not effective_plugin_id:
                                effective_plugin_id = next(
                                    (
                                        str(entry.get("plugin_id", "") or "").strip()
                                        for entry in text_variants
                                        if isinstance(entry, dict) and str(entry.get("plugin_id", "") or "").strip()
                                    ),
                                    "",
                                )
                            configured_ok = any(
                                self._plugin_available(str(entry.get("plugin_id", "") or "").strip())
                                for entry in text_variants
                                if isinstance(entry, dict)
                            )
                        elif str(text_stage_config.get("plugin_id", "") or "").strip():
                            effective_plugin_id = str(text_stage_config.get("plugin_id", "") or "").strip()
                            configured_ok = self._plugin_available(effective_plugin_id)
            status, config_error = self._normalize_ui_status(
                status,
                has_input=has_input,
                is_enabled=is_enabled,
                plugin_id=effective_plugin_id,
                plugin_available=configured_ok,
            )
            if config_error:
                error = config_error

        return StageViewModel(
            stage_id=stage_id,
            display_name=self._stage_display_name(stage_id),
            short_name=self._stage_short_name(stage_id),
            status=status,
            progress=progress,
            is_enabled=is_enabled,
            is_dirty=state.dirty,
            is_blocked=False,
            warnings=warnings,
            error=error,
            plugin_id=plugin_id,
            plugin_options=plugin_options,
            inline_settings_keys=inline_keys,
            settings_schema=schema,
            current_settings=ui_current_settings,
            effective_settings=ui_effective,
            ui_metadata=ui_metadata,
            artifacts=[],
            can_run=is_enabled,
            can_rerun=is_enabled,
        )

    def _stage_mock_summary_state(self, stage_id: str) -> tuple[bool, str]:
        warnings = self._latest_stage_run_warnings(stage_id)
        if not warnings:
            return False, ""
        has_mock = any(_warning_marker(item) in {"mock_fallback", "mock_output"} for item in warnings)
        if not has_mock:
            return False, ""
        for item in warnings:
            if _warning_marker(item) not in {"mock_fallback", "mock_output"}:
                return True, item[:220]
        return True, ""

    def _latest_stage_run_warnings(self, stage_id: str) -> list[str]:
        meeting = self._current_meeting_provider()
        runs = getattr(meeting, "pipeline_runs", None) if meeting is not None else None
        if not isinstance(runs, list) or not runs:
            return []
        latest_run = runs[-1]
        raw_warnings = getattr(latest_run, "warnings", None)
        if not isinstance(raw_warnings, list):
            return []
        prefix = f"{str(stage_id or '').strip()}:"
        stage_warnings: list[str] = []
        for item in raw_warnings:
            text = str(item or "").strip()
            if not text:
                continue
            if text.startswith(prefix):
                normalized = text[len(prefix) :].strip()
                if normalized:
                    stage_warnings.append(normalized)
        return stage_warnings

    def _provider_supports_model_refresh(self, plugin_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        if not pid:
            return False
        plugin = self._get_catalog().plugin_by_id(pid)
        raw_caps = getattr(plugin, "capabilities", {}) if plugin else {}
        capabilities = raw_caps if isinstance(raw_caps, dict) else {}
        models_caps = capabilities.get("models") if isinstance(capabilities, dict) else None
        if not isinstance(models_caps, dict):
            return False
        managed = models_caps.get("managed_actions")
        if isinstance(managed, dict) and str(managed.get("list", "") or "").strip():
            return True
        if isinstance(models_caps.get("local_files"), dict):
            return True
        return str(models_caps.get("storage", "") or "").strip().lower() == "local"


def _warning_marker(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    for separator in ("(", "=", ":"):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
    return text


def _format_warning_for_display(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "=" in text:
        _left, right = text.split("=", 1)
        if right.strip():
            text = right.strip()
    elif "(" in text and text.endswith(")"):
        prefix, inner = text.split("(", 1)
        inner = inner[:-1].strip()
        if inner and prefix.strip():
            text = inner
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip(" :;")
    if not text:
        return ""
    return text[0].upper() + text[1:220]
