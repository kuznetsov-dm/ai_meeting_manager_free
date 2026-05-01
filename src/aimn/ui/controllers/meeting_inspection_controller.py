from __future__ import annotations

from collections.abc import Callable


class MeetingInspectionController:
    @staticmethod
    def resolve_inspection_meeting(
        *,
        active_meeting_base_name: str,
        active_meeting_manifest: object | None,
        load_meeting: Callable[[str], object],
    ) -> object | None:
        base = str(active_meeting_base_name or "").strip()
        if not base:
            return None
        if active_meeting_manifest is not None:
            return active_meeting_manifest
        try:
            return load_meeting(base)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return None

    @staticmethod
    def normalize_selection(*, stage_id: str, alias: str, kind: str) -> tuple[str, str, str]:
        return (
            str(stage_id or "").strip(),
            str(alias or "").strip(),
            str(kind or "").strip(),
        )

    @staticmethod
    def should_render_selection(*, active_meeting_base_name: str, stage_id: str, alias: str) -> bool:
        return bool(
            str(active_meeting_base_name or "").strip()
            and str(stage_id or "").strip()
            and str(alias or "").strip()
        )
