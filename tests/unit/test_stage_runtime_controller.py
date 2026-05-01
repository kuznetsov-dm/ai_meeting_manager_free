import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.stage_runtime_controller import StageRuntimeController


def _stage_title(stage_id: str) -> str:
    return {
        "media_convert": "Convert",
        "transcription": "Transcription",
        "llm_processing": "AI Processing",
        "management": "Management",
        "service": "Service",
    }.get(stage_id, stage_id)


class TestStageRuntimeController(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = StageRuntimeController(
            stage_order=["media_convert", "transcription", "llm_processing", "management", "service"],
            stage_title=_stage_title,
        )

    def test_apply_stage_status_updates_runtime_state(self) -> None:
        affected = self.controller.apply_stage_status(
            stage_id="llm_processing",
            status="running",
            error="",
            progress=-1,
            base_name="meeting-1",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        self.assertTrue(affected)
        state = self.controller.stage_states_for("meeting-1")["llm_processing"]
        self.assertEqual(state.status, "running")
        self.assertIsNone(state.progress)
        self.assertIsNotNone(state.started_at)

    def test_record_stage_activity_keeps_last_message(self) -> None:
        self.controller.apply_stage_status(
            stage_id="transcription",
            status="running",
            error="",
            progress=1,
            base_name="meeting-1",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        event = SimpleNamespace(
            stage_id="transcription",
            event_type="plugin_notice",
            message="decoder switched",
            base_name="meeting-1",
        )
        self.controller.record_stage_activity(
            event,
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        state = self.controller.stage_states_for("meeting-1")["transcription"]
        self.assertEqual(state.last_message, "decoder switched")
        self.assertEqual(state.last_event_type, "plugin_notice")

    def test_pipeline_activity_text_prefers_running_stage(self) -> None:
        self.controller.apply_stage_status(
            stage_id="llm_processing",
            status="running",
            error="",
            progress=0,
            base_name="meeting-1",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        text = self.controller.pipeline_activity_text(
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        self.assertIn("AI Processing running", text)
        self.assertIn("LLM running; progress may be unavailable", text)

    def test_mark_dirty_sets_ready_outside_running(self) -> None:
        self.controller.apply_stage_status(
            stage_id="management",
            status="idle",
            error="",
            progress=0,
            base_name="meeting-1",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        self.controller.mark_dirty(
            stage_id="management",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        state = self.controller.stage_states_for("meeting-1")["management"]
        self.assertTrue(state.dirty)
        self.assertEqual(state.status, "ready")

    def test_mark_running_completed_finalizes_states(self) -> None:
        self.controller.apply_stage_status(
            stage_id="service",
            status="running",
            error="",
            progress=30,
            base_name="meeting-1",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        self.controller.mark_running_completed(base_name="meeting-1")
        state = self.controller.stage_states_for("meeting-1")["service"]
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.progress, 100)
        self.assertIsNone(state.started_at)

    def test_mark_dirty_from_marks_following_stages(self) -> None:
        self.controller.mark_dirty_from(
            stage_id="transcription",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        states = self.controller.stage_states_for("meeting-1")
        self.assertFalse(states["media_convert"].dirty)
        self.assertTrue(states["transcription"].dirty)
        self.assertTrue(states["llm_processing"].dirty)
        self.assertTrue(states["management"].dirty)
        self.assertTrue(states["service"].dirty)
        self.assertEqual(states["service"].status, "ready")

    def test_clear_meeting_states_drops_stale_runtime_for_recreated_meeting(self) -> None:
        self.controller.mark_dirty_from(
            stage_id="transcription",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        self.controller.clear_meeting_states("meeting-1")
        states = self.controller.stage_states_for("meeting-1")
        self.assertFalse(any(state.dirty for state in states.values()))
        self.assertTrue(all(state.status == "idle" for state in states.values()))

    def test_apply_stage_status_prefers_event_base_name_over_active_meeting(self) -> None:
        # Active meeting in UI is different from the meeting that emitted the status event.
        affected = self.controller.apply_stage_status(
            stage_id="llm_processing",
            status="running",
            error="",
            progress=80,
            base_name="meeting-2",
            active_meeting_base_name="meeting-1",
            last_stage_base_name="meeting-2",
        )
        self.assertFalse(affected)
        active_state = self.controller.stage_states_for("meeting-1")["llm_processing"]
        event_state = self.controller.stage_states_for("meeting-2")["llm_processing"]
        self.assertEqual(active_state.status, "idle")
        self.assertEqual(event_state.status, "running")
        self.assertEqual(event_state.progress, 80)

    def test_record_node_started_sets_running_activity(self) -> None:
        event = SimpleNamespace(
            stage_id="transcription",
            event_type="node_started",
            message="node asr started",
            base_name="meeting-1",
        )
        self.controller.record_stage_activity(
            event,
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        state = self.controller.stage_states_for("meeting-1")["transcription"]
        self.assertEqual(state.status, "running")
        self.assertEqual(state.last_event_type, "node_started")
        self.assertEqual(state.last_message, "node asr started")
        self.assertIsNotNone(state.started_at)

    def test_record_node_progress_updates_progress(self) -> None:
        event = SimpleNamespace(
            stage_id="llm_processing",
            event_type="node_progress",
            message="token stream",
            progress=55,
            base_name="meeting-1",
        )
        self.controller.record_stage_activity(
            event,
            active_meeting_base_name="meeting-1",
            last_stage_base_name="",
        )
        state = self.controller.stage_states_for("meeting-1")["llm_processing"]
        self.assertEqual(state.status, "running")
        self.assertEqual(state.progress, 55)
        self.assertEqual(state.last_event_type, "node_progress")


if __name__ == "__main__":
    unittest.main()
