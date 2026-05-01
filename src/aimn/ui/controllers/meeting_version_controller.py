from __future__ import annotations


class MeetingVersionController:
    def __init__(
        self,
        *,
        artifact_service,
        meeting_service,
    ) -> None:
        self._artifact_service = artifact_service
        self._meeting_service = meeting_service

    def pin_alias(self, *, base_name: str, stage_id: str, alias: str):
        base = str(base_name or "").strip()
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        if not base or not sid or not al:
            return None
        try:
            meeting = self._artifact_service.load_meeting(base)
        except Exception:
            return None
        pinned = getattr(meeting, "pinned_aliases", None)
        if not isinstance(pinned, dict):
            pinned = {}
        pinned[sid] = al
        meeting.pinned_aliases = pinned
        try:
            self._meeting_service.touch_updated(meeting)
        except Exception:
            pass
        try:
            self._artifact_service.save_meeting(meeting)
        except Exception:
            return None
        return meeting

    def unpin_alias(self, *, base_name: str, stage_id: str):
        base = str(base_name or "").strip()
        sid = str(stage_id or "").strip()
        if not base or not sid:
            return None
        try:
            meeting = self._artifact_service.load_meeting(base)
        except Exception:
            return None
        pinned = getattr(meeting, "pinned_aliases", None)
        if not isinstance(pinned, dict):
            pinned = {}
        if sid not in pinned:
            return None
        pinned.pop(sid, None)
        meeting.pinned_aliases = pinned
        try:
            self._meeting_service.touch_updated(meeting)
        except Exception:
            pass
        try:
            self._artifact_service.save_meeting(meeting)
        except Exception:
            return None
        return meeting

    def set_active_alias(self, *, base_name: str, stage_id: str, alias: str):
        base = str(base_name or "").strip()
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        if not base or not sid or not al:
            return None
        try:
            meeting = self._artifact_service.load_meeting(base)
        except Exception:
            return None
        active = getattr(meeting, "active_aliases", None)
        if not isinstance(active, dict):
            active = {}
        if active.get(sid) == al:
            return None
        active[sid] = al
        meeting.active_aliases = active
        try:
            self._artifact_service.save_meeting(meeting)
        except Exception:
            return None
        return meeting
