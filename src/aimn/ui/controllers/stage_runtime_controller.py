from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass
class StageRuntimeState:
    status: str = "idle"
    progress: int | None = None
    error: str = ""
    dirty: bool = False
    started_at: float | None = None
    last_event_at: float | None = None
    last_event_type: str = ""
    last_message: str = ""


class StageRuntimeController:
    def __init__(
        self,
        *,
        stage_order: Iterable[str],
        stage_title: Callable[[str], str],
    ) -> None:
        self._stage_order = list(stage_order)
        self._stage_title = stage_title
        self._states_by_meeting: dict[str, dict[str, StageRuntimeState]] = {}

    def stage_states_for(self, base_name: str) -> dict[str, StageRuntimeState]:
        key = str(base_name or "").strip() or "__global__"
        existing = self._states_by_meeting.get(key)
        if existing:
            return existing
        created = {stage_id: StageRuntimeState() for stage_id in self._stage_order}
        self._states_by_meeting[key] = created
        return created

    def clear_meeting_states(self, base_name: str) -> None:
        key = str(base_name or "").strip()
        if not key:
            return
        self._states_by_meeting.pop(key, None)

    def current_stage_states(
        self,
        *,
        active_meeting_base_name: str,
        last_stage_base_name: str,
    ) -> dict[str, StageRuntimeState]:
        key = (
            str(active_meeting_base_name or "").strip()
            or str(last_stage_base_name or "").strip()
            or "__global__"
        )
        return self.stage_states_for(key)

    def record_stage_activity(
        self,
        event: object,
        *,
        active_meeting_base_name: str,
        last_stage_base_name: str,
    ) -> None:
        stage_id = str(getattr(event, "stage_id", "") or "").strip()
        if not stage_id:
            return
        meeting_key = str(getattr(event, "base_name", "") or "").strip()
        if not meeting_key:
            meeting_key = str(active_meeting_base_name or "").strip() or str(last_stage_base_name or "").strip()
        if not meeting_key:
            return
        state = self.stage_states_for(meeting_key).get(stage_id)
        if not state:
            return

        event_type = str(getattr(event, "event_type", "") or "")
        message = str(getattr(event, "message", "") or "")
        now = time.monotonic()
        if event_type in {"stage_started", "node_started"}:
            if state.started_at is None:
                state.started_at = now
            state.last_event_at = now
            state.last_event_type = event_type
            if state.status not in {"running", "completed", "failed", "skipped", "disabled"}:
                state.status = "running"
            if message:
                state.last_message = message
            return
        if event_type in {"stage_finished", "stage_failed", "stage_skipped"}:
            state.started_at = None
            state.last_event_at = None
            state.last_event_type = ""
            state.last_message = ""
            return
        if event_type == "node_progress":
            progress = _coerce_progress(getattr(event, "progress", None))
            if progress is not None:
                state.progress = progress
            if state.status not in {"running", "completed", "failed", "skipped", "disabled"}:
                state.status = "running"
        state.last_event_at = now
        state.last_event_type = event_type or state.last_event_type
        if message:
            state.last_message = message

    def apply_stage_status(
        self,
        *,
        stage_id: str,
        status: str,
        error: str,
        progress: int | None,
        base_name: str,
        active_meeting_base_name: str,
        last_stage_base_name: str,
    ) -> bool:
        stage_key = str(stage_id or "").strip()
        meeting_key = str(base_name or "").strip()
        if not meeting_key:
            meeting_key = str(active_meeting_base_name or "").strip() or str(last_stage_base_name or "").strip()
        state = self.stage_states_for(meeting_key).get(stage_key)
        if not state:
            return False

        mapped = {"finished": "completed"}.get(str(status or ""), str(status or ""))
        state.status = mapped
        progress_value: int | None
        try:
            progress_value = int(progress) if progress is not None else None
        except (TypeError, ValueError):
            progress_value = None
        if progress_value is not None and progress_value < 0:
            progress_value = None
        state.progress = progress_value
        state.error = str(error or "")
        if mapped == "running" and state.started_at is None:
            now = time.monotonic()
            state.started_at = now
            state.last_event_at = now
            state.last_event_type = "stage_running"
        if mapped in {"completed", "failed", "skipped"}:
            state.started_at = None
            state.last_event_at = None
            state.last_event_type = ""
            state.last_message = ""
        if mapped in {"running", "completed", "failed", "skipped"}:
            state.dirty = False
        return bool(meeting_key == active_meeting_base_name or not active_meeting_base_name)

    def mark_running_completed(self, *, base_name: str) -> None:
        base = str(base_name or "").strip()
        if not base:
            return
        for state in self.stage_states_for(base).values():
            if state.status != "running":
                continue
            state.status = "completed"
            state.progress = 100
            state.started_at = None
            state.last_event_at = None
            state.last_event_type = ""
            state.last_message = ""

    def mark_dirty(
        self,
        *,
        stage_id: str,
        active_meeting_base_name: str,
        last_stage_base_name: str,
    ) -> None:
        state = self.current_stage_states(
            active_meeting_base_name=active_meeting_base_name,
            last_stage_base_name=last_stage_base_name,
        ).get(str(stage_id or "").strip())
        if not state:
            return
        self._apply_dirty_state(state)

    def mark_dirty_from(
        self,
        *,
        stage_id: str,
        active_meeting_base_name: str,
        last_stage_base_name: str,
    ) -> None:
        wanted = str(stage_id or "").strip()
        if not wanted or wanted not in self._stage_order:
            return
        states = self.current_stage_states(
            active_meeting_base_name=active_meeting_base_name,
            last_stage_base_name=last_stage_base_name,
        )
        start_idx = self._stage_order.index(wanted)
        for sid in self._stage_order[start_idx:]:
            state = states.get(sid)
            if state:
                self._apply_dirty_state(state)

    @staticmethod
    def _apply_dirty_state(state: StageRuntimeState) -> None:
        state.dirty = True
        if state.status not in {"running"}:
            state.status = "ready"

    def pipeline_activity_text(
        self,
        *,
        active_meeting_base_name: str,
        last_stage_base_name: str,
    ) -> str:
        states = self.current_stage_states(
            active_meeting_base_name=active_meeting_base_name,
            last_stage_base_name=last_stage_base_name,
        )
        running = [(sid, state) for sid, state in states.items() if state.status == "running"]
        if not running:
            return ""
        running.sort(
            key=lambda item: (
                item[1].started_at if item[1].started_at is not None else float("inf"),
                self._stage_order.index(item[0]) if item[0] in self._stage_order else 999,
            )
        )
        stage_id, state = running[0]
        now = time.monotonic()
        elapsed = self._format_elapsed(now - state.started_at) if state.started_at else ""
        idle = self._format_elapsed(now - state.last_event_at) if state.last_event_at else ""
        parts = [f"{self._stage_title(stage_id)} running"]
        if elapsed:
            parts.append(f"elapsed {elapsed}")
        if idle:
            parts.append(f"last activity {idle} ago")
        if stage_id == "llm_processing" and (state.progress is None or state.progress == 0):
            parts.append("LLM running; progress may be unavailable")
        if state.last_message:
            parts.append(state.last_message)
        return " • ".join(parts)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = int(max(0, seconds))
        mins, sec = divmod(total, 60)
        hours, mins = divmod(mins, 60)
        if hours:
            return f"{hours}:{mins:02d}:{sec:02d}"
        return f"{mins}:{sec:02d}"


def _coerce_progress(value: object) -> int | None:
    try:
        parsed = int(value) if value is not None else None
    except Exception:
        return None
    if parsed is None:
        return None
    if parsed < 0:
        return None
    if parsed > 100:
        return 100
    return parsed
