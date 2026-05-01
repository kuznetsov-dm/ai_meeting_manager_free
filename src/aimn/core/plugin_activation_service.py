from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aimn.core.app_paths import get_plugin_activation_path
from aimn.core.atomic_io import atomic_write_text
from aimn.core.plugins_registry import set_plugin_enabled

_ACTIVE = "active"
_INACTIVE = "inactive"
_VALID_STATES = {_ACTIVE, _INACTIVE}


@dataclass(frozen=True)
class PluginActivationSnapshot:
    payload: dict
    path: Path


class PluginActivationService:
    def __init__(self, app_root: Path) -> None:
        self._path = get_plugin_activation_path(app_root)

    def load(self) -> PluginActivationSnapshot:
        return PluginActivationSnapshot(payload=self._load_payload(), path=self._path)

    def desired_state(self, plugin_id: str) -> str:
        plugins = self._plugins_payload()
        item = plugins.get(str(plugin_id or "").strip())
        if not isinstance(item, dict):
            return ""
        state = str(item.get("state", "") or "").strip().lower()
        return state if state in _VALID_STATES else ""

    def is_enabled(self, plugin_id: str, *, default: bool) -> bool:
        state = self.desired_state(plugin_id)
        if state == _ACTIVE:
            return True
        if state == _INACTIVE:
            return False
        return bool(default)

    def set_enabled(self, plugin_id: str, enabled: bool) -> Path:
        payload = self._load_payload()
        plugins = payload.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            payload["plugins"] = plugins
        pid = str(plugin_id or "").strip()
        if not pid:
            return self._path
        plugins[pid] = {"state": _ACTIVE if enabled else _INACTIVE}
        self._write_payload(payload)
        return self._path

    def ensure_state(self, plugin_id: str, *, enabled: bool) -> Path:
        if self.desired_state(plugin_id):
            return self._path
        return self.set_enabled(plugin_id, enabled)

    def apply_to_registry_payload(self, payload: dict) -> dict:
        data = dict(payload) if isinstance(payload, dict) else {}
        plugins = self._plugins_payload()
        for plugin_id, item in plugins.items():
            if not isinstance(item, dict):
                continue
            state = str(item.get("state", "") or "").strip().lower()
            if state not in _VALID_STATES:
                continue
            data = set_plugin_enabled(data, plugin_id, state == _ACTIVE)
        return data

    def _plugins_payload(self) -> dict:
        payload = self._load_payload()
        plugins = payload.get("plugins")
        return dict(plugins) if isinstance(plugins, dict) else {}

    def _load_payload(self) -> dict:
        if not self._path.exists():
            return {"version": "1", "plugins": {}}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": "1", "plugins": {}}
        if not isinstance(raw, dict):
            return {"version": "1", "plugins": {}}
        payload = dict(raw)
        payload["version"] = "1"
        if not isinstance(payload.get("plugins"), dict):
            payload["plugins"] = {}
        return payload

    def _write_payload(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._path,
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        )
