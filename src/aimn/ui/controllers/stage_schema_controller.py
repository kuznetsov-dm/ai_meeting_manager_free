from __future__ import annotations

from collections.abc import Callable

from aimn.ui.tabs.contracts import SettingField, SettingOption


class StageSchemaController:
    _ORCHESTRATOR_PARAM_KEYS = {"prompt_signature", "model", "model_id", "model_path"}

    def __init__(
        self,
        *,
        get_catalog: Callable[[], object],
        config_data_provider: Callable[[], dict],
        is_transcription_local_plugin: Callable[[str], bool],
        whisper_models_state: Callable[[], tuple[list[str], list[str]]],
        model_options_for: Callable[[str], list[SettingOption]],
        is_local_models_plugin: Callable[[str], bool] | None = None,
        load_agenda_catalog: Callable[[], list[dict]] | None = None,
        load_project_catalog: Callable[[], list[dict]] | None = None,
        coerce_setting_value: Callable[[object], object],
        is_secret_field_name: Callable[[str], bool],
    ) -> None:
        self._get_catalog = get_catalog
        self._config_data_provider = config_data_provider
        self._is_transcription_local_plugin = is_transcription_local_plugin
        self._whisper_models_state = whisper_models_state
        self._model_options_for = model_options_for
        self._is_local_models_plugin = is_local_models_plugin or (lambda _pid: False)
        self._load_agenda_catalog = load_agenda_catalog or (lambda: [])
        self._load_project_catalog = load_project_catalog or (lambda: [])
        self._coerce_setting_value = coerce_setting_value
        self._is_secret_field_name = is_secret_field_name

    def schema_for(self, plugin_id: str, *, stage_id: str) -> list[SettingField]:
        stage_config = self._config_data_provider().get("stages", {}).get(stage_id, {})
        if not isinstance(stage_config, dict):
            stage_config = {}
        current_params = stage_config.get("params", {})
        if not isinstance(current_params, dict):
            current_params = {}
        if stage_id == "management":
            return self._management_prompt_fields(current_params)
        if not plugin_id:
            return []
        schema = self._get_catalog().schema_for(plugin_id)
        if not schema:
            return []
        fields: list[SettingField] = []
        for setting in schema.settings:
            options: list[SettingOption] = []
            if setting.options:
                options = [SettingOption(label=o.label, value=o.value) for o in setting.options]
            fields.append(
                SettingField(
                    key=setting.key,
                    label=setting.label,
                    value=self._coerce_setting_value(setting.value),
                    options=options,
                    editable=setting.editable,
                )
            )

        if stage_id == "transcription" and self._is_transcription_local_plugin(plugin_id):
            installed, known = self._whisper_models_state()
            enriched: list[SettingField] = []
            for field in fields:
                if field.key == "model":
                    current = str(current_params.get("model", "") or "").strip()
                    opts: list[SettingOption] = []
                    if current and current not in set(installed):
                        suffix = "missing" if current and current not in set(known) else "not installed"
                        opts.append(SettingOption(label=f"{current} ({suffix})", value=current))
                    for mid in installed:
                        opts.append(SettingOption(label=mid, value=mid))
                    enriched.append(
                        SettingField(
                            key=field.key,
                            label=field.label,
                            value=field.value,
                            options=opts,
                            editable=field.editable,
                        )
                    )
                    continue
                if field.key == "language_mode":
                    enriched.append(
                        SettingField(
                            key=field.key,
                            label=field.label,
                            value=field.value,
                            options=[
                                SettingOption(label="Auto", value="auto"),
                                SettingOption(label="None", value="none"),
                                SettingOption(label="Forced", value="forced"),
                            ],
                            editable=field.editable,
                        )
                    )
                    continue
                if field.key == "language_code" and not field.options:
                    options = [
                        SettingOption(label="(not set)", value=""),
                        SettingOption(label="English (en)", value="en"),
                        SettingOption(label="Russian (ru)", value="ru"),
                        SettingOption(label="Ukrainian (uk)", value="uk"),
                        SettingOption(label="German (de)", value="de"),
                        SettingOption(label="French (fr)", value="fr"),
                        SettingOption(label="Spanish (es)", value="es"),
                        SettingOption(label="Italian (it)", value="it"),
                        SettingOption(label="Portuguese (pt)", value="pt"),
                        SettingOption(label="Polish (pl)", value="pl"),
                        SettingOption(label="Turkish (tr)", value="tr"),
                        SettingOption(label="Arabic (ar)", value="ar"),
                        SettingOption(label="Hindi (hi)", value="hi"),
                        SettingOption(label="Chinese (zh)", value="zh"),
                        SettingOption(label="Japanese (ja)", value="ja"),
                        SettingOption(label="Korean (ko)", value="ko"),
                    ]
                    current = str(field.value or "").strip()
                    if current and all(opt.value != current for opt in options):
                        options.insert(1, SettingOption(label=f"{current} (custom)", value=current))
                    enriched.append(
                        SettingField(
                            key=field.key,
                            label=field.label,
                            value=field.value,
                            options=options,
                            editable=field.editable,
                        )
                    )
                    continue
                enriched.append(field)
            fields = enriched

        if stage_id == "llm_processing":
            model_options = self._model_options_for(plugin_id)
            if model_options:
                enriched: list[SettingField] = []
                for field in fields:
                    if field.key != "model_id":
                        enriched.append(field)
                        continue
                    enriched.append(
                        SettingField(
                            key=field.key,
                            label=field.label,
                            value=field.value,
                            options=list(model_options),
                            editable=(field.editable and not self._is_local_models_plugin(plugin_id)),
                        )
                    )
                fields = enriched

        return fields

    def _management_prompt_fields(self, current_params: dict) -> list[SettingField]:
        agenda_options = [SettingOption(label="No planned agenda", value="")]
        for item in self._load_agenda_catalog():
            if not isinstance(item, dict):
                continue
            agenda_id = str(item.get("id", "") or "").strip()
            if not agenda_id:
                continue
            title = str(item.get("title", "") or "").strip() or agenda_id
            agenda_options.append(SettingOption(label=title, value=agenda_id))

        project_options: list[SettingOption] = [SettingOption(label="No linked projects (you can type IDs)", value="")]
        for item in self._load_project_catalog():
            if not isinstance(item, dict):
                continue
            project_id = str(item.get("project_id", "") or item.get("id", "") or "").strip()
            if not project_id:
                continue
            name = str(item.get("name", "") or "").strip() or project_id
            project_options.append(SettingOption(label=f"{name} ({project_id})", value=project_id))

        return [
            SettingField(
                key="prompt_agenda_id",
                label="Planned agenda",
                value=self._coerce_setting_value(current_params.get("prompt_agenda_id", "")),
                options=agenda_options,
                editable=False,
            ),
            SettingField(
                key="prompt_project_ids",
                label="Projects (comma-separated IDs)",
                value=self._coerce_setting_value(current_params.get("prompt_project_ids", "")),
                options=project_options,
                editable=False,
                multi_select=True,
            ),
            SettingField(
                key="prompt_agenda_title",
                label="Manual agenda title (optional)",
                value=self._coerce_setting_value(current_params.get("prompt_agenda_title", "")),
                options=[],
                editable=True,
            ),
            SettingField(
                key="prompt_agenda_text",
                label="Manual agenda text (optional)",
                value=self._coerce_setting_value(current_params.get("prompt_agenda_text", "")),
                options=[],
                editable=True,
            ),
        ]

    def sanitize_params_for_plugin(self, plugin_id: str, params: dict) -> dict[str, object]:
        if not isinstance(params, dict):
            return {}
        raw = dict(params)
        plugin_key = str(plugin_id or "").strip()
        if not plugin_key:
            sanitized = raw
            return self._merge_orchestrator_params(raw, sanitized)
        schema = self._get_catalog().schema_for(plugin_key)
        if not schema:
            sanitized = raw
            return self._merge_orchestrator_params(raw, sanitized)
        allowed = {str(setting.key).strip() for setting in schema.settings if str(setting.key).strip()}
        if not allowed:
            sanitized = {}
            return self._merge_orchestrator_params(raw, sanitized)
        sanitized = {str(key): value for key, value in raw.items() if str(key).strip() in allowed}
        return self._merge_orchestrator_params(raw, sanitized)

    def _merge_orchestrator_params(self, raw: dict, sanitized: dict[str, object]) -> dict[str, object]:
        merged = dict(sanitized)
        for key in self._ORCHESTRATOR_PARAM_KEYS:
            if key in raw:
                merged[str(key)] = raw.get(key)
        model_value = str(merged.get("model", "") or "").strip()
        model_id_value = str(merged.get("model_id", "") or "").strip()
        if model_value and not model_id_value:
            merged["model_id"] = model_value
        return merged

    def inline_settings_keys(self, stage_config: dict, schema: list[SettingField]) -> list[str]:
        ui = stage_config.get("ui", {}) if isinstance(stage_config, dict) else {}
        inline = ui.get("inline_settings")
        if isinstance(inline, list):
            keys = [str(item) for item in inline if str(item)]
            keys = [k for k in keys if not self._is_secret_field_name(k)]
            schema_by_key = {f.key: f for f in schema}
            filtered: list[str] = []
            for key in keys:
                field = schema_by_key.get(key)
                if not field:
                    continue
                if field.options:
                    filtered.append(key)
                    continue
                value = field.value
                if isinstance(value, bool) or str(value).strip().lower() in {"true", "false"}:
                    filtered.append(key)
            return filtered[:4]

        preferred = [
            "model",
            "model_id",
            "language_mode",
            "language_code",
            "auth_mode",
            "temperature",
        ]
        available = [field.key for field in schema]
        keys = [key for key in preferred if key in available and not self._is_secret_field_name(key)]
        if not keys:
            keys = available[:2]
        schema_by_key = {f.key: f for f in schema}
        drawer_keys: list[str] = []
        for key in keys:
            field = schema_by_key.get(key)
            if not field:
                continue
            if field.options:
                drawer_keys.append(key)
                continue
            value = field.value
            if isinstance(value, bool) or str(value).strip().lower() in {"true", "false"}:
                drawer_keys.append(key)
        return drawer_keys[:4]
