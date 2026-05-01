from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class IndexQuery:
    query: str
    meeting_id: Optional[str] = None
    alias: Optional[str] = None
    kind: Optional[str] = None


@dataclass(frozen=True)
class IndexHit:
    meeting_id: str
    alias: Optional[str]
    kind: str
    snippet: str
    score: float


class IndexProvider:
    def on_artifact_written(self, meeting_id: str, alias: Optional[str], kind: str, relpath: str) -> None:
        raise NotImplementedError

    def on_meeting_saved(self, meeting_id: str) -> None:
        raise NotImplementedError

    def search(self, query: IndexQuery) -> Iterable[IndexHit]:
        raise NotImplementedError

    def get_text(self, meeting_id: str, alias: Optional[str], kind: str) -> str:
        raise NotImplementedError

    def rebuild(self, meeting_id: Optional[str] = None) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
