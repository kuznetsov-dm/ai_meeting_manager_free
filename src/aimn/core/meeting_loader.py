from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from aimn.core.fingerprinting import compute_source_fingerprint
from aimn.core.meeting_ids import make_meeting_ids, utc_now_iso
from aimn.core.meeting_store import FileMeetingStore
from aimn.domain.meeting import MeetingManifest, SourceInfo, SourceItem, StorageInfo, SCHEMA_VERSION


def load_or_create_meeting(store: FileMeetingStore, media_path: Path) -> MeetingManifest:
    fingerprint = compute_source_fingerprint(str(media_path))
    meeting_id, base_name = make_meeting_ids(media_path, fingerprint=fingerprint)
    meeting_path = store.output_dir / f"{base_name}__MEETING.json"
    if meeting_path.exists():
        meeting = store.load(base_name)
        _update_sources(meeting, media_path, fingerprint)
        _rename_meeting_if_needed(store, meeting, base_name)
        return meeting

    meeting = _find_meeting_by_source(store, media_path, fingerprint)
    if meeting:
        _update_sources(meeting, media_path, fingerprint)
        _rename_meeting_if_needed(store, meeting, base_name)
        return meeting

    meeting = MeetingManifest(
        schema_version=SCHEMA_VERSION,
        meeting_id=meeting_id,
        base_name=base_name,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
        storage=StorageInfo(),
        source=SourceInfo(
            items=[
                _build_source_item(media_path, "src1", fingerprint)
            ]
        ),
    )
    return meeting


def _update_sources(meeting: MeetingManifest, media_path: Path, fingerprint: str) -> MeetingManifest:
    stat = media_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    mtime_utc = mtime.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for item in meeting.source.items:
        if item.input_path == str(media_path):
            _refresh_source_item(item, media_path, fingerprint)
            return meeting
        if item.content_fingerprint == fingerprint:
            _refresh_source_item(item, media_path, fingerprint, override_path=True)
            return meeting
        if item.size_bytes == stat.st_size and item.mtime_utc == mtime_utc:
            _refresh_source_item(item, media_path, fingerprint, override_path=True)
            return meeting
    meeting.source.items.append(
        _build_source_item(media_path, f"src{len(meeting.source.items) + 1}", fingerprint)
    )
    return meeting


def _build_source_item(media_path: Path, source_id: str, fingerprint: str) -> SourceItem:
    stat = media_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    return SourceItem(
        source_id=source_id,
        input_filename=media_path.name,
        input_path=str(media_path),
        size_bytes=stat.st_size,
        mtime_utc=mtime.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        content_fingerprint=fingerprint,
    )


def _refresh_source_item(
    item: SourceItem, media_path: Path, fingerprint: str, *, override_path: bool = False
) -> None:
    stat = media_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    item.input_filename = media_path.name
    if override_path:
        item.input_path = str(media_path)
    item.size_bytes = stat.st_size
    item.mtime_utc = mtime.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    item.content_fingerprint = fingerprint


def _find_meeting_by_source(
    store: FileMeetingStore, media_path: Path, fingerprint: str
) -> MeetingManifest | None:
    stat = media_path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    mtime_utc = mtime.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    candidates: list[MeetingManifest] = []
    for base_name in store.list_meetings():
        try:
            meeting = store.load(base_name)
        except Exception:
            continue
        for item in meeting.source.items:
            if item.content_fingerprint == fingerprint:
                return meeting
            if item.size_bytes == stat.st_size and item.mtime_utc == mtime_utc:
                candidates.append(meeting)
                break
    if len(candidates) == 1:
        return candidates[0]
    return None


def _rename_meeting_if_needed(
    store: FileMeetingStore, meeting: MeetingManifest, new_base_name: str
) -> None:
    if _is_base_name_locked(meeting):
        return
    if meeting.base_name == new_base_name:
        return
    meeting_path = store.output_dir / f"{new_base_name}__MEETING.json"
    if meeting_path.exists():
        return
    _rename_meeting_files(store, meeting, new_base_name)


def _rename_meeting_files(
    store: FileMeetingStore, meeting: MeetingManifest, new_base_name: str
) -> None:
    output_dir = store.output_dir
    old_base_name = meeting.base_name
    use_alias = meeting.naming_mode == "branched"
    ops: list[tuple[object, str, str, Path, Path]] = []
    for alias, node in meeting.nodes.items():
        for artifact in node.artifacts:
            ext = Path(artifact.path).suffix.lstrip(".")
            alias_value = alias if use_alias else None
            new_relpath = store.resolve_artifact_path(
                new_base_name,
                alias_value,
                artifact.kind,
                ext,
            )
            old_path = output_dir / artifact.path
            new_path = output_dir / new_relpath
            ops.append((artifact, artifact.path, new_relpath, old_path, new_path))
    old_meeting_path = output_dir / f"{old_base_name}__MEETING.json"
    new_meeting_path = output_dir / f"{new_base_name}__MEETING.json"

    renamed_paths: list[tuple[Path, Path]] = []
    try:
        for _artifact, _old_relpath, _new_relpath, old_path, new_path in ops:
            if old_path.exists():
                _replace_with_retry(old_path, new_path)
                renamed_paths.append((new_path, old_path))
        if old_meeting_path.exists():
            _replace_with_retry(old_meeting_path, new_meeting_path)
            renamed_paths.append((new_meeting_path, old_meeting_path))
    except PermissionError as exc:
        for new_path, old_path in reversed(renamed_paths):
            try:
                if new_path.exists():
                    os.replace(new_path, old_path)
            except Exception:
                continue
        logging.getLogger("aimn.meeting_loader").warning(
            "meeting_rename_skipped old=%s new=%s error=%s", old_base_name, new_base_name, exc
        )
        return

    for artifact, old_relpath, new_relpath, _old_path, _new_path in ops:
        if meeting.transcript_relpath == old_relpath:
            meeting.transcript_relpath = new_relpath
        if meeting.segments_relpath == old_relpath:
            meeting.segments_relpath = new_relpath
        if meeting.audio_relpath == old_relpath:
            meeting.audio_relpath = new_relpath
        artifact.path = new_relpath
    meeting.base_name = new_base_name


def _replace_with_retry(source: Path, target: Path) -> None:
    attempts = 6
    delay = 0.25
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt >= attempts - 1:
                raise
            time.sleep(delay)


def _is_base_name_locked(meeting: MeetingManifest) -> bool:
    value = getattr(meeting, "base_name_locked", False)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}
