from __future__ import annotations

from typing import Callable


class MeetingSelectionController:
    @staticmethod
    def load_selection_payload(
        *,
        base_name: str,
        load_meeting: Callable[[str], object],
        list_artifacts: Callable[[object, bool], list[object]],
        load_management_suggestions: Callable[[str], list[dict]] | None = None,
        all_meetings: list[object],
        stage_order: list[str],
    ) -> dict:
        base = str(base_name or "").strip()
        if not base:
            return {"meeting": None}
        meeting = load_meeting(base)

        allowed = {"transcript", "edited", "summary"}
        artifacts_all = list(list_artifacts(meeting, True) or [])
        active_artifacts = [
            item
            for item in artifacts_all
            if str(getattr(item, "kind", "") or "") in allowed and bool(getattr(item, "user_visible", False))
        ]
        meeting_id = str(getattr(meeting, "meeting_id", "") or "")
        management_suggestions = (
            list(load_management_suggestions(meeting_id) or [])
            if callable(load_management_suggestions) and meeting_id
            else []
        )

        segments_relpaths: dict[str, str] = {}
        for item in artifacts_all:
            if str(getattr(item, "kind", "") or "") != "segments":
                continue
            alias = str(getattr(item, "alias", "") or "").strip()
            stage_id = str(getattr(item, "stage_id", "") or "").strip()
            relpath = str(getattr(item, "relpath", "") or "").strip()
            if not alias or not relpath:
                continue
            if stage_id:
                segments_relpaths[f"{stage_id}:{alias}"] = relpath
            segments_relpaths.setdefault(alias, relpath)

        meeting_choices = [
            (str(getattr(item, "meeting_id", "") or ""), str(getattr(item, "base_name", "") or ""))
            for item in (all_meetings or [])
        ]
        meeting_choices = [(mid, label) for mid, label in meeting_choices if mid]
        kinds = sorted(
            {
                str(getattr(item, "kind", "") or "").strip()
                for item in (active_artifacts or [])
                if str(getattr(item, "kind", "") or "").strip()
            }
        )
        nodes = getattr(meeting, "nodes", {}) or {}
        stages = sorted({str(getattr(node, "stage_id", "") or "").strip() for node in nodes.values() if node})
        aliases = sorted([str(alias or "") for alias in nodes.keys() if str(alias or "").strip()])

        return {
            "meeting": meeting,
            "active_artifacts": active_artifacts,
            "segments_relpaths": segments_relpaths,
            "management_suggestions": management_suggestions,
            "audio_relpath": str(getattr(meeting, "audio_relpath", "") or "").strip(),
            "pinned_aliases": getattr(meeting, "pinned_aliases", {}) or {},
            "active_aliases": getattr(meeting, "active_aliases", {}) or {},
            "preferred_kind": "transcript" if any(a.kind == "transcript" for a in active_artifacts) else "",
            "search_context": {
                "meetings": meeting_choices,
                "current_meeting_id": meeting_id,
                "kinds": kinds or ["transcript", "edited", "summary"],
                "stages": stages or ["meeting"] + list(stage_order),
                "aliases": aliases,
            },
        }
