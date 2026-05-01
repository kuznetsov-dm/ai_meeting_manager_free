from __future__ import annotations

from collections.abc import Callable


class ManagementNavigationController:
    @staticmethod
    def build_pending_navigation(
        payload: dict[str, object] | None,
        *,
        resolve_meeting_base: Callable[[str], str],
    ) -> dict[str, object] | None:
        data = dict(payload or {})
        meeting_key = str(data.get("meeting_id", "") or data.get("base_name", "") or "").strip()
        if not meeting_key:
            return None
        base = str(resolve_meeting_base(meeting_key) or "").strip()
        if not base:
            return None
        source_kind = str(data.get("source_kind", "") or "").strip().lower()
        kind = source_kind if source_kind in {"transcript", "edited", "summary"} else "transcript"
        return {
            "base_name": base,
            "kind": kind,
            "alias": str(data.get("source_alias", "") or "").strip(),
            "query": str(data.get("query", "") or "").strip(),
            "segment_index": int(data.get("segment_index", -1) or -1),
            "start_ms": int(data.get("start_ms", -1) or -1),
        }

    @staticmethod
    def apply_pending_navigation(
        payload: dict[str, object] | None,
        *,
        selected_base: str,
        text_panel: object,
    ) -> bool:
        data = dict(payload or {})
        base = str(data.get("base_name", "") or "").strip()
        if base != str(selected_base or "").strip():
            return False
        kind = str(data.get("kind", "") or "").strip() or "transcript"
        alias = str(data.get("alias", "") or "").strip()
        query = str(data.get("query", "") or "").strip()
        segment_index = int(data.get("segment_index", -1) or -1)
        start_ms = int(data.get("start_ms", -1) or -1)

        text_panel.select_artifact_kind(kind)
        if alias:
            text_panel.select_version(alias=alias, kind=kind)
        if kind == "transcript" and (segment_index >= 0 or start_ms >= 0):
            text_panel.jump_to_transcript_segment(
                segment_index=segment_index,
                start_ms=start_ms,
                alias=alias,
                kind=kind,
            )
        if query:
            text_panel.highlight_query(query)
        return True

    @staticmethod
    def route_navigation_request(
        payload: dict[str, object] | None,
        *,
        resolve_meeting_base: Callable[[str], str],
        active_meeting_base_name: str,
        has_active_manifest: bool,
        select_history: Callable[[str], None],
        apply_pending: Callable[[str], None],
        select_meeting: Callable[[str], None],
    ) -> dict[str, object] | None:
        pending = ManagementNavigationController.build_pending_navigation(
            payload,
            resolve_meeting_base=resolve_meeting_base,
        )
        if not pending:
            return None
        base = str(pending.get("base_name", "") or "").strip()
        if not base:
            return None
        try:
            select_history(base)
        except RuntimeError:
            pass
        if str(active_meeting_base_name or "").strip() == base and bool(has_active_manifest):
            apply_pending(base)
        else:
            select_meeting(base)
        return pending
