# ruff: noqa: E402, I001

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

from aimn.ui.controllers.pipeline_ui_state_controller import PipelineUiStateController


class TestPipelineUiStateController(unittest.TestCase):
    def test_pipeline_meta_includes_run_hint_and_registry(self) -> None:
        text = PipelineUiStateController.pipeline_meta(
            selected_stage_id="",
            config_source="preset",
            config_path="config/settings.json",
            overrides=["a", "b"],
            pipeline_preset="default",
            plugin_registry={"source": "plugins.json", "path": "config/plugins.json"},
            active_meeting_base_name="meeting-1",
            active_meeting_source_path="input.wav",
            active_meeting_status="raw",
            input_files=["input.wav"],
            default_rerun_stage="transcription",
        )

        self.assertIn("Pipeline preset: default (preset)", text)
        self.assertIn("Plugin registry: plugins.json (config/plugins.json)", text)
        self.assertIn("Run from stage 'transcription' for meeting meeting-1", text)

    def test_can_run_pipeline_false_when_runner_active(self) -> None:
        result = PipelineUiStateController.can_run_pipeline(
            stages=[],
            pipeline_running=True,
            selected_stage_id="",
            active_meeting_base_name="",
            active_meeting_source_path="",
            input_files=[],
        )
        self.assertFalse(result)

    def test_can_run_pipeline_false_for_disabled_selected_stage(self) -> None:
        stages = [SimpleNamespace(stage_id="transcription", status="disabled")]
        result = PipelineUiStateController.can_run_pipeline(
            stages=stages,
            pipeline_running=False,
            selected_stage_id="transcription",
            active_meeting_base_name="meeting-1",
            active_meeting_source_path="input.wav",
            input_files=[],
        )
        self.assertFalse(result)

    def test_can_run_pipeline_false_when_transcription_not_ready_for_batch(self) -> None:
        stages = [SimpleNamespace(stage_id="transcription", status="idle")]
        result = PipelineUiStateController.can_run_pipeline(
            stages=stages,
            pipeline_running=False,
            selected_stage_id="",
            active_meeting_base_name="",
            active_meeting_source_path="",
            input_files=["one.wav", "two.wav"],
        )
        self.assertFalse(result)

    def test_build_refresh_state_combines_meta_and_button_flags(self) -> None:
        stages = [SimpleNamespace(stage_id="transcription", status="ready")]

        state = PipelineUiStateController.build_refresh_state(
            stages=stages,
            pipeline_running=True,
            pipeline_paused=True,
            selected_stage_id="",
            config_source="preset",
            config_path="config/settings.json",
            overrides=["a"],
            pipeline_preset="default",
            plugin_registry={"source": "plugins.json", "path": "config/plugins.json"},
            active_meeting_base_name="meeting-1",
            active_meeting_source_path="input.wav",
            active_meeting_status="raw",
            input_files=["input.wav"],
            default_rerun_stage="transcription",
        )

        self.assertEqual(state.stages, stages)
        self.assertIn("Pipeline preset: default (preset)", state.meta)
        self.assertFalse(state.run_enabled)
        self.assertTrue(state.pause_enabled)
        self.assertTrue(state.stop_enabled)
        self.assertTrue(state.paused)


if __name__ == "__main__":
    unittest.main()
