from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from aimn.core.atomic_io import atomic_write_text
from aimn.core.plugins_registry import load_registry_payload, registry_write_path


@dataclass(frozen=True)
class PluginRegistrySnapshot:
    payload: dict
    source: str
    path: Path | None


class PluginRegistryService:
    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def load(self) -> PluginRegistrySnapshot:
        payload, source, path = load_registry_payload(self._repo_root)
        data = payload if isinstance(payload, dict) else {}
        return PluginRegistrySnapshot(data, str(source or ""), path)

    def write(self, payload: dict) -> Path:
        data = payload if isinstance(payload, dict) else {}
        out_path = registry_write_path(self._repo_root)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True))
        return out_path

    @staticmethod
    def stamp(snapshot: PluginRegistrySnapshot) -> str:
        mtime = ""
        try:
            mtime = str(snapshot.path.stat().st_mtime) if snapshot.path and snapshot.path.exists() else ""
        except Exception:
            mtime = ""
        return f"{snapshot.source}:{mtime}"
