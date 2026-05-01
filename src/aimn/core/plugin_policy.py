from __future__ import annotations

from typing import Iterable, Set

from aimn.core.plugins_config import PluginsConfig


class PluginPolicy:
    def __init__(self, config: PluginsConfig) -> None:
        self._enabled = _to_set(config.enabled_plugin_ids())
        self._allowlist = _to_set(config.allowlist() or [])
        self._disabled = _to_set(config.disabled_plugin_ids() or [])

    def is_enabled(self, plugin_id: str) -> bool:
        if self._enabled:
            return plugin_id in self._enabled
        if self._allowlist:
            return plugin_id in self._allowlist
        if self._disabled:
            return plugin_id not in self._disabled
        return True


def _to_set(values: Iterable[str]) -> Set[str]:
    return {str(item) for item in values if str(item)}
