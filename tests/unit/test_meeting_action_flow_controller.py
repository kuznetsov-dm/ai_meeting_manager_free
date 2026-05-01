# ruff: noqa: E402

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

from aimn.ui.controllers.meeting_action_flow_controller import (
    MeetingActionFlowController,
    MeetingDeleteFlowCallbacks,
    MeetingExportFlowCallbacks,
    MeetingRenameFlowCallbacks,
    MeetingRerunFlowCallbacks,
    MeetingRerunSelection,
)


class TestMeetingActionFlowController(unittest.TestCase):
    def test_delete_meeting_clears_active_state_after_confirmed_delete(self) -> None:
        events: list[tuple[str, object]] = []
        active_state = {"base": "m-base"}

        result = MeetingActionFlowController.delete_meeting(
            "m-base",
            callbacks=MeetingDeleteFlowCallbacks(
                load_meeting=lambda _base: SimpleNamespace(meeting_id="mid-1"),
                is_active_base=lambda candidate: active_state["base"] == candidate,
                clear_audio_path=lambda: events.append(("audio", "")),
                confirm_delete=lambda: True,
                cleanup_meeting_for_delete=lambda meeting_id: events.append(("cleanup", meeting_id)) or True,
                delete_meeting_files=lambda base: events.append(("delete", base)),
                clear_meeting_states=lambda base: events.append(("clear_states", base)),
                invalidate_payload_cache=lambda base: events.append(("invalidate", base)),
                clear_active_meeting=lambda: active_state.__setitem__("base", ""),
                refresh_history=lambda: events.append(("history", None)),
                refresh_pipeline_ui=lambda: events.append(("pipeline", None)),
                log_delete_preview_error=lambda _base, _exc: events.append(("delete_preview_error", None)),
                log_clear_audio_error=lambda _base, _exc: events.append(("audio_error", None)),
            ),
        )

        self.assertTrue(result)
        self.assertEqual(active_state["base"], "")
        self.assertEqual(
            events,
            [
                ("audio", ""),
                ("cleanup", "mid-1"),
                ("delete", "m-base"),
                ("clear_states", "m-base"),
                ("invalidate", "m-base"),
                ("history", None),
                ("pipeline", None),
            ],
        )

    def test_delete_meeting_stops_when_cleanup_rejects(self) -> None:
        events: list[tuple[str, object]] = []

        result = MeetingActionFlowController.delete_meeting(
            "m-base",
            callbacks=MeetingDeleteFlowCallbacks(
                load_meeting=lambda _base: SimpleNamespace(meeting_id="mid-1"),
                is_active_base=lambda _candidate: False,
                clear_audio_path=lambda: events.append(("audio", "")),
                confirm_delete=lambda: True,
                cleanup_meeting_for_delete=lambda meeting_id: events.append(("cleanup", meeting_id)) or False,
                delete_meeting_files=lambda base: events.append(("delete", base)),
                clear_meeting_states=lambda base: events.append(("clear_states", base)),
                invalidate_payload_cache=lambda base: events.append(("invalidate", base)),
                clear_active_meeting=lambda: events.append(("clear_active", None)),
                refresh_history=lambda: events.append(("history", None)),
                refresh_pipeline_ui=lambda: events.append(("pipeline", None)),
                log_delete_preview_error=lambda _base, _exc: events.append(("delete_preview_error", None)),
                log_clear_audio_error=lambda _base, _exc: events.append(("audio_error", None)),
            ),
        )

        self.assertFalse(result)
        self.assertEqual(events, [("cleanup", "mid-1")])

    def test_rename_meeting_warns_when_load_fails(self) -> None:
        warnings: list[str] = []

        result = MeetingActionFlowController.rename_meeting(
            "m-base",
            callbacks=MeetingRenameFlowCallbacks(
                load_meeting=lambda _base: (_ for _ in ()).throw(RuntimeError("load failed")),
                meeting_display_title=lambda _meeting: "Current",
                meeting_topic_suggestions=lambda _base, _meeting: [],
                prompt_new_title=lambda _current_title, _suggestions: "New",
                rename_policy=lambda: ("metadata_only", False),
                confirm_source_rename=lambda: False,
                is_active_base=lambda _candidate: False,
                is_last_stage_base=lambda _candidate: False,
                clear_audio_path=lambda: None,
                rename_meeting=lambda _base, _title, _mode, _rename_source: "new-base",
                set_active_meeting_base=lambda _new_base: None,
                set_last_stage_base=lambda _new_base: None,
                invalidate_payload_cache=lambda _base: None,
                refresh_history=lambda _new_base: None,
                refresh_pipeline_ui=lambda: None,
                warn_load_failed=lambda exc: warnings.append(str(exc)),
                warn_target_exists=lambda exc: warnings.append(f"exists:{exc}"),
                warn_source_not_allowed=lambda exc: warnings.append(f"source:{exc}"),
                warn_generic=lambda exc: warnings.append(f"generic:{exc}"),
            ),
        )

        self.assertFalse(result)
        self.assertEqual(warnings, ["load failed"])

    def test_rename_meeting_updates_active_and_last_stage_on_success(self) -> None:
        invalidated: list[str] = []
        refreshed: list[str] = []
        active_state = {"base": "m-base"}
        last_state = {"base": "m-base"}

        result = MeetingActionFlowController.rename_meeting(
            "m-base",
            callbacks=MeetingRenameFlowCallbacks(
                load_meeting=lambda _base: SimpleNamespace(meeting_id="mid-1"),
                meeting_display_title=lambda _meeting: "Current",
                meeting_topic_suggestions=lambda _base, _meeting: ["Suggestion"],
                prompt_new_title=lambda _current_title, _suggestions: "New Title",
                rename_policy=lambda: ("full_with_source", True),
                confirm_source_rename=lambda: True,
                is_active_base=lambda candidate: active_state["base"] == candidate,
                is_last_stage_base=lambda candidate: last_state["base"] == candidate,
                clear_audio_path=lambda: None,
                rename_meeting=lambda _base, _title, mode, rename_source: (
                    "m-new" if mode == "full_with_source" and rename_source else "bad"
                ),
                set_active_meeting_base=lambda new_base: active_state.__setitem__("base", new_base),
                set_last_stage_base=lambda new_base: last_state.__setitem__("base", new_base),
                invalidate_payload_cache=lambda base: invalidated.append(base),
                refresh_history=lambda new_base: refreshed.append(new_base),
                refresh_pipeline_ui=lambda: refreshed.append("pipeline"),
                warn_load_failed=lambda _exc: refreshed.append("warn_load"),
                warn_target_exists=lambda _exc: refreshed.append("warn_exists"),
                warn_source_not_allowed=lambda _exc: refreshed.append("warn_source"),
                warn_generic=lambda _exc: refreshed.append("warn_generic"),
            ),
        )

        self.assertTrue(result)
        self.assertEqual(active_state["base"], "m-new")
        self.assertEqual(last_state["base"], "m-new")
        self.assertEqual(invalidated, ["m-base", "m-new"])
        self.assertEqual(refreshed, ["m-new", "pipeline"])

    def test_rerun_meeting_starts_pipeline_from_selected_stage(self) -> None:
        events: list[tuple[str, str, bool]] = []

        result = MeetingActionFlowController.rerun_meeting(
            "m-base",
            callbacks=MeetingRerunFlowCallbacks(
                prompt_stage=lambda: MeetingRerunSelection(stage_id="transcription"),
                runtime_stage_id_for_ui=lambda stage_id: f"runtime:{stage_id}",
                start_pipeline=lambda force_run_from, base_name, force_run: events.append((force_run_from, base_name, force_run)),
            ),
        )

        self.assertTrue(result)
        self.assertEqual(events, [("runtime:transcription", "m-base", False)])

    def test_rerun_meeting_can_request_force_replace_downstream(self) -> None:
        events: list[tuple[str, str, bool]] = []

        result = MeetingActionFlowController.rerun_meeting(
            "m-base",
            callbacks=MeetingRerunFlowCallbacks(
                prompt_stage=lambda: MeetingRerunSelection(
                    stage_id="llm_processing",
                    force_replace_downstream=True,
                ),
                runtime_stage_id_for_ui=lambda stage_id: stage_id,
                start_pipeline=lambda force_run_from, base_name, force_run: events.append((force_run_from, base_name, force_run)),
            ),
        )

        self.assertTrue(result)
        self.assertEqual(events, [("llm_processing", "m-base", True)])

    def test_export_meeting_warns_when_no_targets_available(self) -> None:
        events: list[tuple[str, str]] = []

        result = MeetingActionFlowController.export_meeting(
            "m-base",
            "meeting-key",
            targets=[],
            callbacks=MeetingExportFlowCallbacks(
                warn_no_targets=lambda: events.append(("warn_no_targets", "")),
                choose_target=lambda _targets: None,
                choose_mode=lambda: "",
                run_meeting_export=lambda *_args: None,
                show_info=lambda title, message: events.append((title, message)),
                show_warning=lambda title, message: events.append((title, message)),
            ),
        )

        self.assertFalse(result)
        self.assertEqual(events, [("warn_no_targets", "")])

    def test_export_meeting_runs_selected_target_and_shows_info(self) -> None:
        calls: list[tuple[str, str, str, str, str]] = []
        shown: list[tuple[str, str]] = []
        targets = [
            {"plugin_id": "p1", "action_id": "a1", "label": "Alpha"},
            {"plugin_id": "p2", "action_id": "a2", "label": "Beta"},
        ]

        result = MeetingActionFlowController.export_meeting(
            "m-base",
            "meeting-key",
            targets=targets,
            callbacks=MeetingExportFlowCallbacks(
                warn_no_targets=lambda: shown.append(("warn_no_targets", "")),
                choose_target=lambda available: dict(available[1]),
                choose_mode=lambda: "selective",
                run_meeting_export=lambda plugin_id, action_id, base_name, meeting_key, mode: calls.append(
                    (plugin_id, action_id, base_name, meeting_key, mode)
                )
                or SimpleNamespace(level="info", title="Done", message="ok"),
                show_info=lambda title, message: shown.append((title, message)),
                show_warning=lambda title, message: shown.append((title, message)),
            ),
        )

        self.assertTrue(result)
        self.assertEqual(calls, [("p2", "a2", "m-base", "meeting-key", "selective")])
        self.assertEqual(shown, [("Done", "ok")])

    def test_export_meeting_shows_warning_for_non_info_outcome(self) -> None:
        shown: list[tuple[str, str]] = []

        result = MeetingActionFlowController.export_meeting(
            "m-base",
            "meeting-key",
            targets=[{"plugin_id": "p1", "action_id": "a1", "label": "Alpha"}],
            callbacks=MeetingExportFlowCallbacks(
                warn_no_targets=lambda: shown.append(("warn_no_targets", "")),
                choose_target=lambda available: dict(available[0]),
                choose_mode=lambda: "full",
                run_meeting_export=lambda *_args: SimpleNamespace(
                    level="warning",
                    title="Failed",
                    message="boom",
                ),
                show_info=lambda title, message: shown.append((title, message)),
                show_warning=lambda title, message: shown.append((title, message)),
            ),
        )

        self.assertFalse(result)
        self.assertEqual(shown, [("Failed", "boom")])


if __name__ == "__main__":
    unittest.main()
