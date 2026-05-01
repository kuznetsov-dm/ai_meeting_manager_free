from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


_LOG = logging.getLogger(__name__)


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


class PluginCapabilitiesController:
    def __init__(
        self,
        *,
        get_catalog: Callable[[], object],
        list_actions: Callable[[str], list[object]],
    ) -> None:
        self._get_catalog = get_catalog
        self._list_actions = list_actions

    def plugin_capabilities(self, plugin_id: str) -> dict[str, Any]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return {}
        plugin = self._get_catalog().plugin_by_id(pid)
        caps = getattr(plugin, "capabilities", None) if plugin else None
        return dict(caps) if isinstance(caps, dict) else {}

    def capability_bool(self, plugin_id: str, *keys: str, default: bool = False) -> bool:
        value = _cap_get(self.plugin_capabilities(plugin_id), *keys, default=default)
        if isinstance(value, bool):
            return value
        return _coerce_bool(value) if value is not None else bool(default)

    def capability_int(self, plugin_id: str, *keys: str, default: int = 100) -> int:
        value = _cap_get(self.plugin_capabilities(plugin_id), *keys, default=default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def integration_export_targets(self, *, action_keys: tuple[str, ...]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        catalog = self._get_catalog()
        for plugin in catalog.enabled_plugins():
            pid = str(getattr(plugin, "plugin_id", "") or "").strip()
            if not pid:
                continue
            caps = plugin.capabilities if isinstance(getattr(plugin, "capabilities", None), dict) else {}
            export_caps = caps.get("artifact_export") if isinstance(caps, dict) else None
            if not isinstance(export_caps, dict):
                continue
            action_id = ""
            for key in action_keys:
                action_id = str(export_caps.get(str(key), "") or "").strip()
                if action_id:
                    break
            if not action_id:
                continue
            try:
                actions = self._list_actions(pid)
            except Exception as exc:
                _LOG.warning("list_actions_failed plugin_id=%s error=%s", pid, exc)
                continue
            action_ids = {str(getattr(item, "action_id", "") or "").strip() for item in actions}
            if action_id not in action_ids:
                continue
            label = str(export_caps.get("label", "") or "").strip() or catalog.display_name(pid)
            icon = str(export_caps.get("icon", "") or "").strip()
            targets.append({"plugin_id": pid, "action_id": action_id, "label": label, "icon": icon})
        targets.sort(key=lambda item: (str(item.get("label", "")).lower(), str(item.get("plugin_id", "")).lower()))
        return targets
