from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from aimn.core.plugin_manifest import PluginManifest, load_plugin_manifest


@dataclass(frozen=True)
class DiscoveredPluginManifest:
    manifest: PluginManifest
    manifest_path: Path
    root_dir: Path


class PluginDiscovery:
    def __init__(self, plugins_dir: Path | Iterable[Path]) -> None:
        if isinstance(plugins_dir, Path):
            self._plugins_dirs = [plugins_dir]
        else:
            self._plugins_dirs = [Path(item) for item in plugins_dir]

    def discover(self) -> List[PluginManifest]:
        return [entry.manifest for entry in self.discover_entries()]

    def discover_entries(self) -> List[DiscoveredPluginManifest]:
        entries: List[DiscoveredPluginManifest] = []
        seen: dict[str, Path] = {}
        for plugins_dir in self._plugins_dirs:
            if not plugins_dir.exists():
                continue
            for manifest_path in sorted(plugins_dir.rglob("plugin.json")):
                try:
                    manifest = load_plugin_manifest(manifest_path)
                except Exception as exc:
                    logging.getLogger("aimn.plugins").warning(
                        "plugin_manifest_invalid path=%s error=%s", manifest_path, exc
                    )
                    continue
                existing = seen.get(manifest.plugin_id)
                if existing and existing != manifest_path:
                    logging.getLogger("aimn.plugins").warning(
                        "plugin_manifest_duplicate_id id=%s first=%s ignored=%s",
                        manifest.plugin_id,
                        existing,
                        manifest_path,
                    )
                    continue
                seen.setdefault(manifest.plugin_id, manifest_path)
                entries.append(
                    DiscoveredPluginManifest(
                        manifest=manifest,
                        manifest_path=manifest_path,
                        root_dir=plugins_dir,
                    )
                )
        return entries
