from __future__ import annotations

from collections.abc import Callable


def _cap_get(payload: object, *keys: str, default: object = None) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(str(key))
    return current if current is not None else default


class StagePluginConfigController:
    def __init__(
        self,
        *,
        get_catalog: Callable[[], object],
        config_data_provider: Callable[[], dict],
        offline_mode: Callable[[], bool],
        coerce_setting_value: Callable[[object], object],
        is_secret_field_name: Callable[[str], bool],
        plugin_capabilities: Callable[[str], dict],
        capability_bool: Callable[..., bool],
        capability_int: Callable[..., int],
    ) -> None:
        self._get_catalog = get_catalog
        self._config_data_provider = config_data_provider
        self._offline_mode = offline_mode
        self._coerce_setting_value = coerce_setting_value
        self._is_secret_field_name = is_secret_field_name
        self._plugin_capabilities = plugin_capabilities
        self._capability_bool = capability_bool
        self._capability_int = capability_int

    def selected_plugin_id(self, stage_id: str) -> str:
        stage = self._config_data_provider().get("stages", {}).get(stage_id, {})
        if not isinstance(stage, dict):
            return ""
        plugin_id = str(stage.get("plugin_id", "")).strip()
        if plugin_id:
            return plugin_id
        variants = stage.get("variants")
        if isinstance(variants, list):
            for entry in variants:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("plugin_id", "") or "").strip()
                if pid:
                    return pid
        return ""

    def is_transcription_local_plugin(self, plugin_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        if not pid:
            return False
        return bool(
            _cap_get(self._plugin_capabilities(pid), "models", "local_files")
            or self._capability_bool(pid, "ui", "transcription", "local_provider", default=False)
        )

    def supports_transcription_quality_presets(self, plugin_id: str) -> bool:
        return self._capability_bool(plugin_id, "ui", "transcription", "preset_overrides", default=False)

    def transcription_provider_order(self, plugin_id: str) -> int:
        return self._capability_int(plugin_id, "ui", "transcription", "order", default=100)

    def order_transcription_providers(self, providers: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return sorted(
            providers,
            key=lambda item: (
                self.transcription_provider_order(item[0]),
                str(item[1] or "").lower(),
                str(item[0] or "").lower(),
            ),
        )

    def text_processing_provider_group(self, plugin_id: str) -> str:
        value = str(
            _cap_get(self._plugin_capabilities(plugin_id), "ui", "text_processing", "group", default="")
            or ""
        ).strip().lower()
        return value if value in {"essentials", "advanced", "diagnostics"} else ""

    def first_transcription_local_plugin_id(self) -> str:
        for pid, _label in self.stage_plugin_options("transcription"):
            if self.is_transcription_local_plugin(pid):
                return pid
        return ""

    def stage_plugin_options(self, stage_id: str) -> list[tuple[str, str]]:
        if stage_id in {"input", "media_convert"}:
            return []
        catalog = self._get_catalog()
        plugins = [
            plugin
            for plugin in catalog.plugins_for_stage(stage_id)
            if plugin.installed and (plugin.enabled or self._offline_mode())
        ]
        return [(p.plugin_id, catalog.display_name(p.plugin_id)) for p in plugins]

    def stage_defaults(self, stage_id: str) -> dict[str, object]:
        plugin_id = self.selected_plugin_id(stage_id)
        schema = self._get_catalog().schema_for(plugin_id)
        if not schema:
            return {}
        defaults: dict[str, object] = {}
        for setting in schema.settings:
            value = self._coerce_setting_value(setting.value)
            if self._is_secret_field_name(setting.key) and (value is None or value == ""):
                continue
            defaults[setting.key] = value
        return defaults
