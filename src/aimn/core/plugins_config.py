from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class PluginsConfig:
    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def enabled_plugin_ids(self) -> list[str]:
        enabled = self._data.get("enabled")
        if isinstance(enabled, list):
            return [str(item) for item in enabled]
        return []

    def stage_ids(self) -> list[str]:
        stages = self._data.get("stages", {})
        return list(stages.keys())

    def plugin_id_for(self, stage_id: str) -> str:
        stages = self._data.get("stages", {})
        stage = stages.get(stage_id, {})
        plugin_id = stage.get("plugin_id")
        if not plugin_id:
            variants = stage.get("variants")
            if isinstance(variants, list) and variants:
                first = variants[0]
                if isinstance(first, dict) and first.get("plugin_id"):
                    return str(first["plugin_id"])
            raise ValueError(f"No plugin_id configured for stage '{stage_id}'")
        return plugin_id

    def plugin_ids_for(self, stage_id: str) -> list[str]:
        stages = self._data.get("stages", {})
        stage = stages.get(stage_id, {})
        plugin_ids = stage.get("plugin_ids")
        if isinstance(plugin_ids, list):
            normalized = [str(item).strip() for item in plugin_ids if str(item).strip()]
            if normalized:
                return normalized
        return [self.plugin_id_for(stage_id)]

    def plugin_params_for(self, stage_id: str) -> Dict[str, Any]:
        stages = self._data.get("stages", {})
        stage = stages.get(stage_id, {})
        params = stage.get("params", {})
        if not isinstance(params, dict):
            return {}
        return params

    def variants_for_stage(self, stage_id: str) -> list[dict]:
        stages = self._data.get("stages", {})
        stage = stages.get(stage_id, {})
        variants = stage.get("variants")
        if isinstance(variants, list):
            return [variant for variant in variants if isinstance(variant, dict)]
        return []

    def allowlist(self) -> list[str] | None:
        allowlist = self._data.get("allowlist")
        if not allowlist:
            return None
        if isinstance(allowlist, dict):
            ids = allowlist.get("ids")
        else:
            ids = allowlist
        if isinstance(ids, list):
            return [str(item) for item in ids]
        return None

    def disabled(self) -> list[str] | None:
        disabled = self._data.get("disabled")
        if not disabled:
            return None
        if isinstance(disabled, dict):
            ids = disabled.get("ids")
        else:
            ids = disabled
        if isinstance(ids, list):
            return [str(item) for item in ids]
        return None

    def disabled_plugin_ids(self) -> list[str] | None:
        return self.disabled()

    def plugin_params_for_id(self, plugin_id: str) -> Dict[str, Any]:
        config = self._data.get("plugin_config", {})
        if not isinstance(config, dict):
            return {}
        params = config.get(plugin_id, {})
        if not isinstance(params, dict):
            return {}
        return params

    def global_settings(self) -> Dict[str, Any]:
        settings = self._data.get("global_settings", {})
        return settings if isinstance(settings, dict) else {}

    def optional_stage_retries(self) -> int:
        pipeline = self._data.get("pipeline", {})
        if isinstance(pipeline, dict):
            value = pipeline.get("optional_stage_retries")
            if isinstance(value, int):
                return max(0, value)
        return 1

    def disabled_stages(self) -> list[str]:
        pipeline = self._data.get("pipeline", {})
        if isinstance(pipeline, dict):
            raw = pipeline.get("disabled_stages", [])
            if isinstance(raw, list):
                return [str(item) for item in raw if str(item)]
        return []

    def trusted_plugins(self) -> list[str]:
        trusted = self._data.get("trusted_plugins", [])
        if isinstance(trusted, list):
            return [str(item) for item in trusted]
        return []

    def isolated_action_plugins(self) -> list[str]:
        isolation = self._data.get("isolation", {})
        if not isinstance(isolation, dict):
            return []
        actions = isolation.get("actions", {})
        if isinstance(actions, dict):
            if actions.get("enabled") is False:
                return []
            plugins = actions.get("plugins", [])
        else:
            plugins = []
        if isinstance(plugins, list):
            return [str(item) for item in plugins]
        return []

    def isolated_hook_plugins(self) -> list[str]:
        isolation = self._data.get("isolation", {})
        if not isinstance(isolation, dict):
            return []
        hooks = isolation.get("hooks", {})
        if isinstance(hooks, dict):
            if hooks.get("enabled") is False:
                return []
            plugins = hooks.get("plugins", [])
        else:
            plugins = []
        if isinstance(plugins, list):
            return [str(item) for item in plugins]
        return []


def load_plugins_config(path: Path | str) -> PluginsConfig:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return PluginsConfig(data)
