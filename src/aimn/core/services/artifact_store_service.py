from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from aimn.core.app_paths import AppPaths
from aimn.core.contracts import (
    KIND_AUDIO,
    KIND_SEGMENTS,
    KIND_TRANSCRIPT,
)
from aimn.core.index_service import create_default_index_service
from aimn.core.index_types import IndexQuery
from aimn.domain.meeting import MeetingManifest


@dataclass(frozen=True)
class ArtifactRecord:
    relpath: str
    kind: str
    stage_id: str
    alias: str
    timestamp: str = ""
    user_visible: bool = True


@dataclass(frozen=True)
class SearchHitRecord:
    meeting_id: str
    alias: str
    kind: str
    snippet: str


class ArtifactStoreService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._output_dir = AppPaths.resolve(app_root).output_dir
        from aimn.core.meeting_store import FileMeetingStore

        self._store = FileMeetingStore(self._output_dir)
        self._index = None

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def list_meetings(self) -> list[MeetingManifest]:
        meetings: list[MeetingManifest] = []
        for base_name in self._store.list_meetings():
            try:
                meetings.append(self._store.load(base_name))
            except Exception:
                continue
        meetings.sort(key=lambda item: item.updated_at or "", reverse=True)
        return meetings

    def load_meeting(self, base_name: str) -> MeetingManifest:
        return self._store.load(base_name)

    def save_meeting(self, meeting: MeetingManifest) -> None:
        self._store.save(meeting)
        if self._index is not None:
            self._ensure_index().on_meeting_saved(meeting.meeting_id)

    def index_meeting(self, meeting_id: str) -> None:
        if meeting_id:
            self._ensure_index().on_meeting_saved(meeting_id)

    def list_artifacts(
        self, meeting: MeetingManifest, *, include_internal: bool = True
    ) -> list[ArtifactRecord]:
        entries: list[ArtifactRecord] = []
        relpaths_from_nodes: set[str] = set()
        kinds_from_nodes: set[str] = set()
        for alias, node in meeting.nodes.items():
            for artifact in node.artifacts:
                if not include_internal and not bool(getattr(artifact, "user_visible", True)):
                    continue
                relpaths_from_nodes.add(artifact.path)
                kinds_from_nodes.add(str(getattr(artifact, "kind", "") or "").strip())
                entries.append(
                    ArtifactRecord(
                        relpath=artifact.path,
                        kind=artifact.kind,
                        stage_id=node.stage_id,
                        alias=alias,
                        timestamp=self._artifact_timestamp(artifact.path),
                        user_visible=bool(getattr(artifact, "user_visible", True)),
                    )
                )
        top_level = [
            (KIND_TRANSCRIPT, meeting.transcript_relpath),
            (KIND_SEGMENTS, meeting.segments_relpath),
            (KIND_AUDIO, meeting.audio_relpath),
        ]
        for kind, relpath in top_level:
            if not relpath:
                continue
            # Backwards compat: older manifests had only meeting-level relpaths. Once lineage nodes exist
            # for the same kind, meeting-level pointers become ambiguous and can create "unnamed" versions.
            if str(kind) in kinds_from_nodes:
                continue
            # Avoid clobbering lineage artifacts: prefer node metadata (stage_id/alias) when present.
            if relpath in relpaths_from_nodes:
                continue
            if not (self._output_dir / relpath).exists():
                continue
            if not include_internal and kind in {KIND_SEGMENTS, KIND_AUDIO}:
                continue
            entries.append(
                ArtifactRecord(
                    relpath=relpath,
                    kind=kind,
                    stage_id="meeting",
                    alias="",
                    timestamp=self._artifact_timestamp(relpath),
                    user_visible=(kind not in {KIND_SEGMENTS, KIND_AUDIO}),
                )
            )
        entries = list({item.relpath: item for item in entries}.values())
        entries.sort(key=lambda item: (item.stage_id, item.alias, item.kind, item.relpath))
        return entries

    def read_artifact_text(self, relpath: str) -> str:
        path = self._output_dir / relpath
        if not path.exists():
            return f"Missing: {path}"
        if path.suffix.lower() in {".txt", ".json", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        return str(path)

    def search(self, query: str) -> list[SearchHitRecord]:
        if not query.strip():
            return []
        hits = list(self._ensure_index().search(IndexQuery(query=query)))
        return [
            SearchHitRecord(
                meeting_id=str(hit.meeting_id),
                alias=str(hit.alias),
                kind=str(hit.kind),
                snippet=str(hit.snippet),
            )
            for hit in hits
        ]

    def get_search_text(self, meeting_id: str, alias: str, kind: str) -> str:
        return self._ensure_index().get_text(meeting_id, alias, kind)

    def rebuild_index(self, meeting_id: str | None = None) -> None:
        self._ensure_index().rebuild(meeting_id)

    def close(self) -> None:
        if self._index is not None:
            self._index.close()
            self._index = None

    def _ensure_index(self):
        if self._index is None:
            self._index = create_default_index_service(self._output_dir, app_root=self._app_root)
        return self._index

    def _artifact_timestamp(self, relpath: str) -> str:
        path = self._output_dir / relpath
        if not path.exists():
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))
        except Exception:
            return ""
