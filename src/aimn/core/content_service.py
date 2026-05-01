from __future__ import annotations

from pathlib import Path
from typing import Any

from aimn.core.content_store import get_content


class ContentService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root

    def get(self, path: str, *, default: Any = None) -> Any:
        return get_content(path, default=default, repo_root=self._app_root)
