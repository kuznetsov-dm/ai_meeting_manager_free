from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


class MeetingHistoryController:
    def __init__(self) -> None:
        self._all_meetings: list[object] = []
        self._meta_cache: dict[str, dict[str, str]] = {}

    def set_meetings(self, meetings: list[object]) -> None:
        normalized_meetings: list[object] = []
        for meeting in list(meetings or []):
            self.normalize_meeting_processing_status(meeting)
            normalized_meetings.append(meeting)
        self._all_meetings = normalized_meetings
        known_bases = {
            str(getattr(item, "base_name", "") or "").strip()
            for item in self._all_meetings
            if str(getattr(item, "base_name", "") or "").strip()
        }
        if known_bases:
            self._meta_cache = {
                base: payload for base, payload in self._meta_cache.items() if str(base or "").strip() in known_bases
            }
        else:
            self._meta_cache.clear()

    def all_meetings(self) -> list[object]:
        return list(self._all_meetings)

    def meta_cache_snapshot(self) -> dict[str, dict[str, str]]:
        return {
            str(base): {
                "updated_at": str(payload.get("updated_at", "") or ""),
                "display_meeting_time": str(payload.get("display_meeting_time", "") or ""),
                "display_processed_time": str(payload.get("display_processed_time", "") or ""),
                "display_stats": str(payload.get("display_stats", "") or ""),
            }
            for base, payload in self._meta_cache.items()
            if isinstance(payload, dict) and str(base or "").strip()
        }

    def restore_meta_cache(self, snapshot: dict[str, dict[str, str]] | None) -> None:
        cache: dict[str, dict[str, str]] = {}
        for base, payload in (snapshot or {}).items():
            key = str(base or "").strip()
            if not key or not isinstance(payload, dict):
                continue
            cache[key] = {
                "updated_at": str(payload.get("updated_at", "") or ""),
                "display_meeting_time": str(payload.get("display_meeting_time", "") or ""),
                "display_processed_time": str(payload.get("display_processed_time", "") or ""),
                "display_stats": str(payload.get("display_stats", "") or ""),
            }
        self._meta_cache = cache

    @staticmethod
    def meeting_primary_path(meeting: object) -> str:
        try:
            source = getattr(meeting, "source", None)
            items = getattr(source, "items", None) if source else None
            if not items:
                return ""
            item = items[0]
            return str(getattr(item, "input_path", "") or "")
        except Exception:
            return ""

    def active_meeting_path(
        self,
        *,
        base_name: str,
        loader: Callable[[str], object],
    ) -> str:
        base = str(base_name or "").strip()
        if not base:
            return ""
        try:
            meeting = loader(base)
        except Exception:
            return ""
        return self.meeting_primary_path(meeting)

    def active_meeting_status(
        self,
        *,
        base_name: str,
        loader: Callable[[str], object],
    ) -> str:
        base = str(base_name or "").strip()
        if not base:
            return ""
        try:
            meeting = loader(base)
        except Exception:
            return ""
        self.normalize_meeting_processing_status(meeting)
        return str(getattr(meeting, "processing_status", "") or "").strip().lower()

    def pending_files_from_meetings(self, meetings: list[object]) -> list[str]:
        pending: list[str] = []
        for meeting in meetings:
            self.normalize_meeting_processing_status(meeting)
            status = str(getattr(meeting, "processing_status", "") or "").strip().lower()
            if status in {"raw", "pending", "queued", "cancelled"}:
                path = self.meeting_primary_path(meeting)
                if path:
                    pending.append(path)
        return pending

    @staticmethod
    def normalize_meeting_processing_status(meeting: object) -> str:
        current = str(getattr(meeting, "processing_status", "") or "").strip().lower()
        runs = list(getattr(meeting, "pipeline_runs", []) or [])
        if not runs:
            return current
        latest = runs[-1]
        latest_result = str(getattr(latest, "result", "") or "").strip().lower()
        latest_finished_at = str(getattr(latest, "finished_at", "") or "").strip()
        terminal_result = latest_result if latest_result in {"completed", "failed", "cancelled"} else ""
        if current == "running" and (terminal_result or latest_finished_at):
            normalized = terminal_result or "completed"
            setattr(meeting, "processing_status", normalized)
            if normalized != "failed":
                setattr(meeting, "processing_error", "")
            return normalized
        if not current and terminal_result:
            setattr(meeting, "processing_status", terminal_result)
            if terminal_result != "failed":
                setattr(meeting, "processing_error", "")
            return terminal_result
        return current

    @staticmethod
    def normalize_ad_hoc_input_files(paths: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in paths or []:
            value = str(raw or "").strip()
            if not value:
                continue
            if Path(value).exists():
                normalized.append(value)
        return normalized

    def resolve_meeting_base(self, meeting_key: str) -> str:
        key = str(meeting_key or "").strip()
        if not key:
            return ""
        for meeting in self._all_meetings:
            base = str(getattr(meeting, "base_name", "") or "").strip()
            if base and base == key:
                return base
        for meeting in self._all_meetings:
            meeting_id = str(getattr(meeting, "meeting_id", "") or "").strip()
            if meeting_id and meeting_id == key:
                base = str(getattr(meeting, "base_name", "") or "").strip()
                if base:
                    return base
        return key

    @staticmethod
    def parse_iso(ts: str) -> datetime | None:
        raw = str(ts or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def format_dt(dt: datetime | None) -> str:
        if not dt:
            return ""
        try:
            local = dt.astimezone()
        except Exception:
            local = dt
        return local.strftime("%a %d %b %H:%M")

    def meeting_time_label(self, meeting: object) -> str:
        mtime = ""
        try:
            source = getattr(meeting, "source", None)
            items = getattr(source, "items", None) if source else None
            if items:
                mtime = str(getattr(items[0], "mtime_utc", "") or "")
        except Exception:
            mtime = ""
        dt = self.parse_iso(mtime) or self.parse_iso(str(getattr(meeting, "created_at", "") or ""))
        label = self.format_dt(dt)
        return f"Meeting: {label}" if label else ""

    def processed_time_label(self, meeting: object) -> str:
        last = ""
        runs = getattr(meeting, "pipeline_runs", []) or []
        if runs:
            finished = [str(getattr(run, "finished_at", "") or "") for run in runs if run]
            finished = [ts for ts in finished if ts]
            if finished:
                last = max(finished)
        if not last:
            last = str(getattr(meeting, "updated_at", "") or "")
        dt = self.parse_iso(last)
        label = self.format_dt(dt)
        return f"Last processed: {label}" if label else ""

    @staticmethod
    def latest_artifact_relpath(meeting: object, kind: str) -> str:
        if kind == "transcript":
            rel = str(getattr(meeting, "transcript_relpath", "") or "").strip()
            if rel:
                return rel
        if kind == "segments":
            rel = str(getattr(meeting, "segments_relpath", "") or "").strip()
            if rel:
                return rel
        best_rel = ""
        best_ts = ""
        nodes = getattr(meeting, "nodes", {}) or {}
        for node in nodes.values():
            artifacts = getattr(node, "artifacts", []) or []
            created_at = str(getattr(node, "created_at", "") or "")
            for artifact in artifacts:
                if str(getattr(artifact, "kind", "") or "") != kind:
                    continue
                relpath = str(getattr(artifact, "path", "") or "")
                if not relpath:
                    continue
                if created_at >= best_ts:
                    best_ts = created_at
                    best_rel = relpath
        return best_rel

    def meeting_segments_stats(self, meeting: object, *, output_dir: Path) -> tuple[int, int, int]:
        rel = self.latest_artifact_relpath(meeting, "segments")
        if not rel:
            return 0, 0, 0
        path = output_dir / rel
        if not path.exists():
            return 0, 0, 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return 0, 0, 0
        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            return 0, 0, 0
        max_end_ms = 0
        speakers: set[str] = set()
        for rec in records:
            if not isinstance(rec, dict):
                continue
            try:
                end_ms = int(rec.get("end_ms") or 0)
            except Exception:
                end_ms = 0
            speaker = str(rec.get("speaker") or "").strip()
            if speaker:
                speakers.add(speaker)
            if end_ms > max_end_ms:
                max_end_ms = end_ms
        return int(max_end_ms / 1000), len(records), len(speakers)

    def meeting_word_count(self, meeting: object, *, output_dir: Path) -> int:
        rel = self.latest_artifact_relpath(meeting, "transcript")
        if not rel:
            return 0
        path = output_dir / rel
        if not path.exists():
            return 0
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return 0
        return len(re.findall(r"\w+", text, flags=re.UNICODE))

    @staticmethod
    def meeting_source_size_bytes(meeting: object) -> int:
        try:
            source = getattr(meeting, "source", None)
            items = getattr(source, "items", None) if source else None
            if items:
                size = getattr(items[0], "size_bytes", None)
                if size:
                    return int(size)
                path = str(getattr(items[0], "input_path", "") or "")
                if path:
                    item_path = Path(path)
                    if item_path.exists():
                        return int(item_path.stat().st_size)
        except Exception:
            return 0
        return 0

    @staticmethod
    def format_bytes(value: int) -> str:
        size = float(value or 0)
        if size <= 0:
            return ""
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    @staticmethod
    def format_duration(seconds: int) -> str:
        value = int(seconds or 0)
        if value <= 0:
            return ""
        mins, sec = divmod(value, 60)
        hrs, mins = divmod(mins, 60)
        if hrs:
            return f"{hrs}h {mins:02d}m"
        if mins:
            return f"{mins}m {sec:02d}s"
        return f"{sec}s"

    def enrich_history_meta(self, meeting: object, *, output_dir: Path) -> None:
        base = str(getattr(meeting, "base_name", "") or "").strip()
        stamp = str(getattr(meeting, "updated_at", "") or "").strip()
        cached = self._meta_cache.get(base) if base else None
        if isinstance(cached, dict) and str(cached.get("updated_at", "")) == stamp:
            try:
                meeting.display_meeting_time = str(cached.get("display_meeting_time", "") or "")
                meeting.display_processed_time = str(cached.get("display_processed_time", "") or "")
                meeting.display_stats = str(cached.get("display_stats", "") or "")
                return
            except Exception:
                pass

        meeting_time = self.meeting_time_label(meeting)
        processed_time = self.processed_time_label(meeting)
        words = self.meeting_word_count(meeting, output_dir=output_dir)
        duration_s, segments_count, speakers_count = self.meeting_segments_stats(meeting, output_dir=output_dir)
        size_bytes = self.meeting_source_size_bytes(meeting)
        runs = len(getattr(meeting, "pipeline_runs", []) or [])
        branches = 0
        try:
            nodes = getattr(meeting, "nodes", None)
            if isinstance(nodes, dict):
                by_stage: dict[str, int] = {}
                for _alias, node in nodes.items():
                    stage_id = str(getattr(node, "stage_id", "") or "").strip()
                    if not stage_id:
                        continue
                    by_stage[stage_id] = by_stage.get(stage_id, 0) + 1
                for count in by_stage.values():
                    if count > 1:
                        branches += count - 1
        except Exception:
            branches = 0

        stats_parts: list[str] = []
        if duration_s:
            stats_parts.append(f"Duration: {self.format_duration(duration_s)}")
        if words:
            stats_parts.append(f"Words: {words}")
        if segments_count:
            stats_parts.append(f"Segments: {segments_count}")
        if speakers_count:
            stats_parts.append(f"Speakers: {speakers_count}")
        if size_bytes:
            stats_parts.append(f"Size: {self.format_bytes(size_bytes)}")
        if runs > 1:
            stats_parts.append(f"Runs: {runs}")
        if branches > 0:
            stats_parts.append(f"Branches: {branches}")
        if len(stats_parts) > 4:
            stats_parts = stats_parts[:4]

        try:
            meeting.display_meeting_time = meeting_time
            meeting.display_processed_time = processed_time
            meeting.display_stats = " • ".join(stats_parts)
            if base:
                self._meta_cache[base] = {
                    "updated_at": stamp,
                    "display_meeting_time": str(meeting.display_meeting_time or ""),
                    "display_processed_time": str(meeting.display_processed_time or ""),
                    "display_stats": str(meeting.display_stats or ""),
                }
        except Exception:
            return

    @staticmethod
    def set_meeting_status(
        meeting: object,
        status: str,
        *,
        error: str = "",
        touch_updated: Callable[[object], None] | None = None,
    ) -> None:
        try:
            meeting.processing_status = str(status or "").strip().lower() or "raw"
            meeting.processing_error = str(error or "").strip()
            if hasattr(meeting, "updated_at") and callable(touch_updated):
                touch_updated(meeting)
        except Exception:
            return
