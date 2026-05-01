from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from aimn.core.atomic_io import atomic_write_text


class UiSettingsStore:
    def __init__(self, base_dir: Path) -> None:
        self._path = base_dir / "ui.json"

    def get(self, key: str) -> object | None:
        data = self._load()
        return data.get(key)

    def set(self, key: str, value: object) -> None:
        data = self._load()
        data[key] = value
        payload = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path, payload)

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}
