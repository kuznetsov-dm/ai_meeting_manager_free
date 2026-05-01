from __future__ import annotations

from pathlib import Path

from aimn.core.app_paths import get_output_dir
from aimn.core.meeting_ids import utc_now_iso
from aimn.core.meeting_loader import load_or_create_meeting
from aimn.core.meeting_rename import rename_meeting
from aimn.core.meeting_store import FileMeetingStore
from aimn.domain.meeting import MeetingManifest


class MeetingService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._output_dir = get_output_dir(app_root)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._store = FileMeetingStore(self._output_dir)

    def load_or_create(self, file_path: str | Path) -> MeetingManifest:
        return load_or_create_meeting(self._store, Path(file_path))

    def save(self, meeting: MeetingManifest) -> None:
        self._store.save(meeting)

    def touch_updated(self, meeting: MeetingManifest) -> None:
        meeting.updated_at = utc_now_iso()

    def load_by_base_name(self, base_name: str) -> MeetingManifest:
        return self._store.load(base_name)

    def rename_meeting(
        self,
        base_name: str,
        *,
        title: str,
        rename_mode: str = "artifacts_and_manifest",
        rename_source: bool = False,
    ) -> str:
        return rename_meeting(
            self._store,
            base_name=base_name,
            new_title=title,
            rename_mode=rename_mode,
            rename_source=rename_source,
        )
