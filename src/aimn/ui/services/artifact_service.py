from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from aimn.core.api import ArtifactStoreService
from aimn.domain.meeting import MeetingManifest


@dataclass(frozen=True)
class ArtifactItem:
    relpath: str
    kind: str
    stage_id: str
    alias: str
    timestamp: str = ""
    user_visible: bool = True


@dataclass(frozen=True)
class SearchHit:
    meeting_id: str
    alias: str
    kind: str
    snippet: str


class ArtifactService:
    def __init__(self, app_root: Path) -> None:
        self._core = ArtifactStoreService(app_root)
        self._output_dir = self._core.output_dir

    def list_meetings(self) -> List[MeetingManifest]:
        return self._core.list_meetings()

    def load_meeting(self, base_name: str) -> MeetingManifest:
        return self._core.load_meeting(base_name)

    def save_meeting(self, meeting: MeetingManifest) -> None:
        self._core.save_meeting(meeting)

    def list_artifacts(self, meeting: MeetingManifest, *, include_internal: bool = True) -> List[ArtifactItem]:
        entries = self._core.list_artifacts(meeting, include_internal=include_internal)
        return [
            ArtifactItem(
                relpath=item.relpath,
                kind=item.kind,
                stage_id=item.stage_id,
                alias=item.alias,
                timestamp=item.timestamp,
                user_visible=item.user_visible,
            )
            for item in entries
        ]

    def read_artifact_text(self, relpath: str) -> str:
        return self._core.read_artifact_text(relpath)

    def open_artifact(self, relpath: str) -> bool:
        path = self._output_dir / relpath
        if not path.exists():
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return True

    def open_output_folder(self) -> bool:
        if not self._output_dir.exists():
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
        return True

    def search(self, query: str) -> List[SearchHit]:
        return [
            SearchHit(
                meeting_id=item.meeting_id,
                alias=item.alias,
                kind=item.kind,
                snippet=item.snippet,
            )
            for item in self._core.search(query)
        ]

    def get_search_text(self, meeting_id: str, alias: str, kind: str) -> str:
        return self._core.get_search_text(meeting_id, alias, kind)

    def close(self) -> None:
        self._core.close()
