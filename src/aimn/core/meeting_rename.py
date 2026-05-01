from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Literal

from aimn.core.meeting_ids import sanitize_name, utc_now_iso
from aimn.core.meeting_store import FileMeetingStore

_FORBIDDEN_CHARS_RE = re.compile(r"[<>:\"/\\|?*\x00-\x1F]+")
_RENAME_MODES = {"metadata_only", "artifacts_and_manifest", "full_with_source"}
RenameMode = Literal["metadata_only", "artifacts_and_manifest", "full_with_source"]


def rename_meeting(
    store: FileMeetingStore,
    *,
    base_name: str,
    new_title: str,
    rename_mode: RenameMode = "artifacts_and_manifest",
    rename_source: bool = False,
    lock_base_name: bool = True,
) -> str:
    old_base = str(base_name or "").strip()
    title = _normalize_title(new_title)
    mode = _normalize_mode(rename_mode)
    if not old_base:
        raise ValueError("empty_base_name")

    meeting = store.load(old_base)
    updated = meeting.model_copy(deep=True)
    managed_roots = _managed_import_roots(store)
    new_base = old_base if mode == "metadata_only" else _build_target_base_name(old_base, title)
    relpath_updates = (
        {}
        if mode == "metadata_only"
        else _artifact_relpath_updates(updated, old_base=old_base, new_base=new_base)
    )
    source_updates = _source_path_updates(
        updated,
        old_base=old_base,
        new_base=new_base,
        mode=mode,
        rename_source=bool(rename_source),
        managed_roots=managed_roots,
    )
    moved_paths: list[tuple[Path, Path]] = []
    moved = False
    try:
        if mode != "metadata_only" and new_base != old_base:
            _ensure_no_collisions(store.output_dir, relpath_updates)
            _apply_renames(store.output_dir, relpath_updates, moved_paths)
            moved = bool(moved_paths)
        if source_updates:
            _ensure_source_no_collisions(source_updates)
            _apply_source_renames(source_updates, moved_paths)
            moved = bool(moved_paths)

        _apply_manifest_updates(updated, relpath_updates, new_base=new_base, title=title, lock_base_name=lock_base_name)
        if source_updates:
            _apply_source_manifest_updates(updated, source_updates)
        store.save(updated)
    except Exception:
        if moved:
            _rollback_renames(moved_paths)
        raise
    return new_base


def _normalize_mode(value: object) -> RenameMode:
    raw = str(value or "").strip().lower()
    if raw in _RENAME_MODES:
        return raw  # type: ignore[return-value]
    raise ValueError("invalid_rename_mode")


def _normalize_title(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise ValueError("empty_meeting_title")
    return text


def _build_target_base_name(old_base: str, title: str) -> str:
    prefix = str(old_base).split("_", 1)[0]
    sanitized = sanitize_name(_FORBIDDEN_CHARS_RE.sub(" ", title))
    if prefix:
        return f"{prefix}_{sanitized}"
    return sanitized


def _artifact_relpath_updates(meeting, *, old_base: str, new_base: str) -> dict[str, str]:
    if new_base == old_base:
        return {}
    relpaths: set[str] = set()
    for node in (meeting.nodes or {}).values():
        for artifact in (node.artifacts or []):
            relpath = str(getattr(artifact, "path", "") or "").strip()
            if relpath:
                relpaths.add(relpath)
    for relpath in (
        str(getattr(meeting, "audio_relpath", "") or "").strip(),
        str(getattr(meeting, "segments_relpath", "") or "").strip(),
        str(getattr(meeting, "transcript_relpath", "") or "").strip(),
    ):
        if relpath:
            relpaths.add(relpath)

    updates: dict[str, str] = {}
    for old_relpath in relpaths:
        new_relpath = _replace_base_prefix(old_relpath, old_base=old_base, new_base=new_base)
        if new_relpath != old_relpath:
            updates[old_relpath] = new_relpath

    updates[f"{old_base}__MEETING.json"] = f"{new_base}__MEETING.json"
    return updates


def _replace_base_prefix(relpath: str, *, old_base: str, new_base: str) -> str:
    text = str(relpath or "")
    for marker in ("__", "."):
        prefix = f"{old_base}{marker}"
        if text.startswith(prefix):
            return f"{new_base}{text[len(old_base):]}"
    return text


def _ensure_no_collisions(output_dir: Path, relpath_updates: dict[str, str]) -> None:
    for old_relpath, new_relpath in relpath_updates.items():
        old_path = output_dir / old_relpath
        new_path = output_dir / new_relpath
        if not old_path.exists() or old_path == new_path:
            continue
        if new_path.exists():
            raise FileExistsError(f"target_exists:{new_path.name}")


def _apply_renames(output_dir: Path, relpath_updates: dict[str, str], moved_paths: list[tuple[Path, Path]]) -> None:
    # Rename artifacts first, manifest last.
    artifacts = [(old, new) for old, new in relpath_updates.items() if not old.endswith("__MEETING.json")]
    meeting_file = [(old, new) for old, new in relpath_updates.items() if old.endswith("__MEETING.json")]
    for old_relpath, new_relpath in artifacts + meeting_file:
        old_path = output_dir / old_relpath
        new_path = output_dir / new_relpath
        if not old_path.exists() or old_path == new_path:
            continue
        _replace_with_retry(old_path, new_path)
        moved_paths.append((new_path, old_path))


def _rollback_renames(moved_paths: list[tuple[Path, Path]]) -> None:
    for new_path, old_path in reversed(moved_paths):
        try:
            if new_path.exists():
                os.replace(new_path, old_path)
        except Exception:
            continue


def _apply_manifest_updates(meeting, relpath_updates: dict[str, str], *, new_base: str, title: str, lock_base_name: bool) -> None:
    for node in (meeting.nodes or {}).values():
        for artifact in (node.artifacts or []):
            old_relpath = str(getattr(artifact, "path", "") or "").strip()
            if old_relpath in relpath_updates:
                artifact.path = relpath_updates[old_relpath]

    if str(getattr(meeting, "audio_relpath", "") or "").strip() in relpath_updates:
        meeting.audio_relpath = relpath_updates[str(meeting.audio_relpath)]
    if str(getattr(meeting, "segments_relpath", "") or "").strip() in relpath_updates:
        meeting.segments_relpath = relpath_updates[str(meeting.segments_relpath)]
    if str(getattr(meeting, "transcript_relpath", "") or "").strip() in relpath_updates:
        meeting.transcript_relpath = relpath_updates[str(meeting.transcript_relpath)]

    meeting.base_name = new_base
    meeting.updated_at = utc_now_iso()
    meeting.display_title = title
    if lock_base_name:
        meeting.base_name_locked = True


def _managed_import_roots(store: FileMeetingStore) -> list[Path]:
    app_root = store.output_dir.parent.resolve()
    candidates = [
        app_root / "input",
        app_root / "inputs",
        app_root / "imports",
        app_root / "media" / "imports",
    ]
    return [path.resolve() for path in candidates]


def _source_path_updates(
    meeting,
    *,
    old_base: str,
    new_base: str,
    mode: RenameMode,
    rename_source: bool,
    managed_roots: list[Path],
) -> list[tuple[Path, Path]]:
    if mode == "metadata_only":
        if rename_source:
            raise ValueError("source_rename_requires_full_mode")
        return []
    if mode != "full_with_source" or not rename_source:
        return []
    if new_base == old_base:
        return []

    items = getattr(getattr(meeting, "source", None), "items", None)
    if not items:
        raise ValueError("source_items_missing")

    updates: list[tuple[Path, Path]] = []
    for item in items:
        source_path = _resolve_source_item_path(item)
        if source_path is None:
            continue
        if not source_path.exists() or not source_path.is_file():
            continue
        if not _is_path_under_any(source_path, managed_roots):
            raise PermissionError("source_not_in_managed_import")
        target = source_path.with_name(f"{new_base}{source_path.suffix}")
        if target == source_path:
            continue
        updates.append((source_path, target))
    return updates


def _resolve_source_item_path(item: object) -> Path | None:
    raw = str(getattr(item, "input_path", "") or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


def _is_path_under_any(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except Exception:
            continue
    return False


def _ensure_source_no_collisions(updates: list[tuple[Path, Path]]) -> None:
    for source, target in updates:
        if source == target:
            continue
        if target.exists():
            raise FileExistsError(f"source_target_exists:{target}")


def _apply_source_renames(
    source_updates: list[tuple[Path, Path]],
    moved_paths: list[tuple[Path, Path]],
) -> None:
    for source_path, target_path in source_updates:
        if source_path == target_path or not source_path.exists():
            continue
        _replace_with_retry(source_path, target_path)
        moved_paths.append((target_path, source_path))


def _apply_source_manifest_updates(meeting, source_updates: list[tuple[Path, Path]]) -> None:
    updates = {str(source.resolve()): target.resolve() for source, target in source_updates}
    items = getattr(getattr(meeting, "source", None), "items", None)
    if not items:
        return
    for item in items:
        source_path = _resolve_source_item_path(item)
        if source_path is None:
            continue
        target = updates.get(str(source_path))
        if target is None:
            continue
        item.input_path = str(target)
        item.input_filename = target.name


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
