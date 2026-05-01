from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from aimn.core.contracts import ActionDescriptor
from aimn.core.plugin_catalog_service import PluginCatalogService
from aimn.core.plugin_manager import PluginManager


class PluginActionService:
    def __init__(self, app_root: Path, *, catalog_service: PluginCatalogService | None = None) -> None:
        self._app_root = app_root
        self._catalog_service = catalog_service or PluginCatalogService(app_root)
        self._manager: PluginManager | None = None
        self._stamp = ""
        self._lock = threading.RLock()

    def invoke_action(
        self,
        plugin_id: str,
        action: str,
        payload: dict[str, Any],
        *,
        settings_override: dict[str, Any] | None = None,
    ) -> Any:
        with self._lock:
            manager = self._get_manager()
            if not manager:
                raise RuntimeError("plugin_manager_unavailable")
            return manager.invoke_action(
                plugin_id,
                action,
                payload,
                settings_override=settings_override,
            )

    def list_actions(self, plugin_id: str) -> list[ActionDescriptor]:
        with self._lock:
            manager = self._get_manager()
            if not manager:
                raise RuntimeError("plugin_manager_unavailable")
            return list(manager.actions_for(plugin_id))

    def get_job_status(self, plugin_id: str, job_id: str):
        with self._lock:
            manager = self._get_manager()
            if not manager:
                raise RuntimeError("plugin_manager_unavailable")
            return manager.get_job_status(plugin_id, job_id)

    def cancel_job(self, plugin_id: str, job_id: str) -> bool:
        with self._lock:
            manager = self._get_manager()
            if not manager:
                raise RuntimeError("plugin_manager_unavailable")
            return bool(manager.cancel_job(plugin_id, job_id))

    def shutdown(self) -> None:
        with self._lock:
            if self._manager:
                try:
                    self._manager.shutdown()
                except Exception:
                    pass
                self._manager = None
                self._stamp = ""

    def _get_manager(self) -> PluginManager | None:
        snapshot = self._catalog_service.load()
        if self._manager and snapshot.stamp == self._stamp:
            return self._manager
        if self._manager:
            try:
                self._manager.shutdown()
            except Exception:
                pass
        manager = PluginManager(self._app_root, snapshot.config)
        manager.load()
        self._manager = manager
        self._stamp = snapshot.stamp
        return self._manager
