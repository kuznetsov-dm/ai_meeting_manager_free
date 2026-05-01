from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from aimn.core.app_paths import get_config_dir
from aimn.core.index_sqlite import SqliteIndexProvider
from aimn.core.index_types import IndexHit, IndexProvider, IndexQuery


class IndexService:
    def __init__(self, provider: IndexProvider) -> None:
        self._provider = provider

    def on_artifact_written(self, meeting_id: str, alias: Optional[str], kind: str, relpath: str) -> None:
        self._provider.on_artifact_written(meeting_id, alias, kind, relpath)

    def on_meeting_saved(self, meeting_id: str) -> None:
        self._provider.on_meeting_saved(meeting_id)

    def search(self, query: IndexQuery) -> Iterable[IndexHit]:
        return self._provider.search(query)

    def get_text(self, meeting_id: str, alias: Optional[str], kind: str) -> str:
        return self._provider.get_text(meeting_id, alias, kind)

    def rebuild(self, meeting_id: Optional[str] = None) -> None:
        self._provider.rebuild(meeting_id)

    def close(self) -> None:
        self._provider.close()


def create_default_index_service(
    output_dir: Path | str,
    *,
    app_root: Path | str | None = None,
) -> IndexService:
    output_path = Path(output_dir)
    root = Path(app_root) if app_root is not None else output_path.parent
    index_dir = get_config_dir(root) / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    db_path = index_dir / "index.sqlite"
    provider = SqliteIndexProvider(db_path=db_path, output_dir=output_path)
    return IndexService(provider)
