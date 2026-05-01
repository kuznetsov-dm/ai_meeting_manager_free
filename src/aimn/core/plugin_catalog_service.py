from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from aimn.core.app_paths import (
    get_installed_plugins_state_path,
    get_plugin_activation_path,
    get_plugin_distribution_path,
    get_plugin_entitlements_path,
    get_plugin_remote_catalog_path,
    get_plugin_roots,
    get_plugin_trust_policy_path,
)
from aimn.core.plugin_activation_service import PluginActivationService
from aimn.core.plugin_catalog import PluginCatalog, create_default_catalog
from aimn.core.plugin_registry_service import PluginRegistryService, PluginRegistrySnapshot
from aimn.core.plugins_config import PluginsConfig

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginCatalogSnapshot:
    catalog: PluginCatalog
    registry: PluginRegistrySnapshot
    config: PluginsConfig
    stamp: str


class PluginCatalogService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._registry = PluginRegistryService(app_root)
        self._activation = PluginActivationService(app_root)
        self._cache: PluginCatalogSnapshot | None = None

    def load(self) -> PluginCatalogSnapshot:
        started_at = time.perf_counter()
        registry = self._registry.load()
        stamp, manifest_count = self._catalog_stamp(registry)
        if self._cache and self._cache.stamp == stamp:
            elapsed_ms = int(max(0.0, (time.perf_counter() - started_at) * 1000.0))
            if elapsed_ms >= 50:
                _LOG.info(
                    "plugin_catalog_load cache=hit elapsed_ms=%s manifest_count=%s",
                    elapsed_ms,
                    manifest_count,
                )
            return self._cache
        payload = registry.payload if isinstance(registry.payload, dict) else {}
        config = PluginsConfig(self._activation.apply_to_registry_payload(payload))
        catalog = create_default_catalog(self._app_root, config=config)
        snapshot = PluginCatalogSnapshot(
            catalog=catalog,
            registry=registry,
            config=config,
            stamp=stamp,
        )
        self._cache = snapshot
        elapsed_ms = int(max(0.0, (time.perf_counter() - started_at) * 1000.0))
        if elapsed_ms >= 50:
            _LOG.info(
                "plugin_catalog_load cache=miss elapsed_ms=%s manifest_count=%s enabled_plugins=%s",
                elapsed_ms,
                manifest_count,
                len(list(catalog.enabled_plugins())),
            )
        return snapshot

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        snapshot = self.load()
        plugin = snapshot.catalog.plugin_by_id(plugin_id)
        return bool(plugin and plugin.installed and plugin.runtime_state == "active")

    def write_registry(self, payload: dict) -> Path:
        path = self._registry.write(payload)
        self._cache = None
        return path

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> Path:
        path = self._activation.set_enabled(plugin_id, enabled)
        self._cache = None
        return path

    def _catalog_stamp(self, registry: PluginRegistrySnapshot) -> tuple[str, int]:
        started_at = time.perf_counter()
        parts = [self._registry.stamp(registry)]
        manifest_count = 0
        extra_paths = [
            get_plugin_distribution_path(self._app_root),
            get_plugin_entitlements_path(self._app_root),
            get_plugin_remote_catalog_path(self._app_root),
            get_plugin_trust_policy_path(self._app_root),
            get_installed_plugins_state_path(self._app_root),
            get_plugin_activation_path(self._app_root),
        ]
        for path in extra_paths:
            parts.append(_path_stamp(path))
        for root in get_plugin_roots(self._app_root):
            if not root.exists():
                parts.append(f"{root}:missing")
                continue
            for manifest_path in sorted(root.rglob("plugin.json")):
                if _is_test_plugin_manifest(manifest_path):
                    continue
                manifest_count += 1
                parts.append(_path_stamp(manifest_path))
        stamp = "|".join(parts)
        elapsed_ms = int(max(0.0, (time.perf_counter() - started_at) * 1000.0))
        if elapsed_ms >= 25:
            _LOG.info(
                "plugin_catalog_stamp elapsed_ms=%s manifest_count=%s extra_paths=%s",
                elapsed_ms,
                manifest_count,
                len(extra_paths),
            )
        return stamp, manifest_count


def _path_stamp(path: Path) -> str:
    try:
        return f"{path}:{path.stat().st_mtime}"
    except Exception:
        return f"{path}:missing"


def _is_test_plugin_manifest(path: Path) -> bool:
    parent_name = str(path.parent.name or "").strip()
    return parent_name.startswith("_test_")
