from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from aimn.ui.controllers.meeting_history_controller import MeetingHistoryController


@dataclass(frozen=True)
class HistoryRefreshPayload:
    meetings: list[object] = field(default_factory=list)
    visible_meetings: list[object] = field(default_factory=list)
    known_bases: set[str] = field(default_factory=set)
    pending_files: list[str] = field(default_factory=list)
    desired_base: str = ""
    fallback_first_base: str = ""
    meta_cache: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class AppliedHistoryRefreshState:
    all_meetings: list[object] = field(default_factory=list)
    meeting_payload_cache: dict[str, object] = field(default_factory=dict)
    input_files: list[str] = field(default_factory=list)
    ad_hoc_input_files: list[str] = field(default_factory=list)
    visible_meetings: list[object] = field(default_factory=list)
    select_base_name: str = ""
    meta_cache: dict[str, dict] = field(default_factory=dict)


class MeetingHistoryRefreshController:
    @staticmethod
    def build_payload(
        *,
        meetings: list[object],
        output_dir: Path,
        meta_cache_snapshot: dict[str, dict],
        global_query: str,
        global_meeting_ids: set[str],
        select_base_name: str,
        current_selection: str,
    ) -> HistoryRefreshPayload:
        helper = MeetingHistoryController()
        helper.restore_meta_cache(meta_cache_snapshot)
        for meeting in meetings:
            helper.enrich_history_meta(meeting, output_dir=output_dir)
        known_bases = {
            str(getattr(item, "base_name", "") or "").strip()
            for item in meetings
            if str(getattr(item, "base_name", "") or "").strip()
        }
        pending_files = helper.pending_files_from_meetings(meetings)
        visible_meetings = list(meetings)
        normalized_query = str(global_query or "").strip()
        normalized_meeting_ids = {str(item or "").strip() for item in set(global_meeting_ids or set()) if str(item or "").strip()}
        if normalized_query:
            visible_meetings = [
                item
                for item in visible_meetings
                if str(getattr(item, "meeting_id", "") or "").strip() in normalized_meeting_ids
            ]
        desired = str(select_base_name or current_selection or "").strip()
        first_base = ""
        if not desired and visible_meetings:
            first_base = str(getattr(visible_meetings[0], "base_name", "") or "").strip()
        return HistoryRefreshPayload(
            meetings=list(meetings),
            visible_meetings=visible_meetings,
            known_bases=known_bases,
            pending_files=[str(path or "").strip() for path in pending_files if str(path or "").strip()],
            desired_base=desired,
            fallback_first_base=first_base,
            meta_cache=helper.meta_cache_snapshot(),
        )

    @staticmethod
    def apply_payload(
        payload: HistoryRefreshPayload | dict[str, object],
        *,
        meeting_history: MeetingHistoryController,
        meeting_payload_cache: dict[str, object],
        ad_hoc_input_files: list[str],
    ) -> AppliedHistoryRefreshState:
        normalized = MeetingHistoryRefreshController._coerce_payload(payload)
        meeting_history.restore_meta_cache(normalized.meta_cache)
        meeting_history.set_meetings(list(normalized.meetings))
        filtered_cache = {
            base: cached
            for base, cached in meeting_payload_cache.items()
            if str(base or "").strip() in normalized.known_bases
        }
        if normalized.pending_files:
            input_files = list(normalized.pending_files)
            normalized_ad_hoc = list(ad_hoc_input_files)
        else:
            normalized_ad_hoc = meeting_history.normalize_ad_hoc_input_files(list(ad_hoc_input_files))
            input_files = list(normalized_ad_hoc)
        selected_base = normalized.desired_base or normalized.fallback_first_base
        return AppliedHistoryRefreshState(
            all_meetings=meeting_history.all_meetings(),
            meeting_payload_cache=filtered_cache,
            input_files=input_files,
            ad_hoc_input_files=normalized_ad_hoc,
            visible_meetings=list(normalized.visible_meetings),
            select_base_name=selected_base,
            meta_cache=normalized.meta_cache,
        )

    @staticmethod
    def _coerce_payload(payload: HistoryRefreshPayload | dict[str, object]) -> HistoryRefreshPayload:
        if isinstance(payload, HistoryRefreshPayload):
            return payload
        data = dict(payload or {}) if isinstance(payload, dict) else {}
        known_bases = {
            str(base or "").strip()
            for base in set(data.get("known_bases", set()) or set())
            if str(base or "").strip()
        }
        pending_files = [str(path or "").strip() for path in list(data.get("pending_files", []) or []) if str(path or "").strip()]
        meta_cache = data.get("meta_cache", {})
        return HistoryRefreshPayload(
            meetings=list(data.get("meetings", []) or []),
            visible_meetings=list(data.get("visible_meetings", []) or []),
            known_bases=known_bases,
            pending_files=pending_files,
            desired_base=str(data.get("desired_base", "") or "").strip(),
            fallback_first_base=str(data.get("fallback_first_base", "") or "").strip(),
            meta_cache=dict(meta_cache) if isinstance(meta_cache, dict) else {},
        )
