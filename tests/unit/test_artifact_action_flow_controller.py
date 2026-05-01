# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.artifact_action_flow_controller import (  # noqa: E402
    ArtifactActionFlowController,
)


class TestArtifactActionFlowController(unittest.TestCase):
    def test_rerun_stage_with_current_settings_builds_start_plan(self) -> None:
        plan = ArtifactActionFlowController.rerun_stage_with_current_settings(
            "llm_processing",
            active_meeting_base_name="m-base",
            runtime_config_with_stage_enabled=lambda stage_id: {"stage": stage_id},
            runtime_stage_id_for_ui=lambda stage_id: f"runtime:{stage_id}",
        )

        self.assertTrue(plan.should_start)
        self.assertEqual(plan.force_run_from, "runtime:llm_processing")
        self.assertEqual(plan.base_name, "m-base")
        self.assertEqual(plan.runtime_config_override, {"stage": "llm_processing"})

    def test_rerun_artifact_same_settings_returns_log_plan_when_lineage_missing(self) -> None:
        plan = ArtifactActionFlowController.rerun_artifact_same_settings(
            "llm_processing",
            "A1",
            active_meeting_base_name="m-base",
            runtime_config_for_artifact_alias=lambda _stage_id, _alias: None,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        self.assertFalse(plan.should_start)
        self.assertIn("Cannot rerun artifact A1", plan.log_message)
        self.assertEqual(plan.log_stage_id, "ui")

    def test_rerun_artifact_same_settings_builds_start_plan(self) -> None:
        plan = ArtifactActionFlowController.rerun_artifact_same_settings(
            "llm_processing",
            "A1",
            active_meeting_base_name="m-base",
            runtime_config_for_artifact_alias=lambda _stage_id, _alias: {"plugin_id": "llm.demo"},
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        self.assertTrue(plan.should_start)
        self.assertEqual(plan.force_run_from, "llm_processing")
        self.assertEqual(plan.base_name, "m-base")
        self.assertEqual(plan.runtime_config_override, {"plugin_id": "llm.demo"})

    def test_cleanup_management_for_artifact_formats_log_message(self) -> None:
        plan = ArtifactActionFlowController.cleanup_management_for_artifact(
            "summary",
            "A1",
            meeting_id="meeting-1",
            run_artifact_alias_cleanup=lambda _meeting_id, _kind, _alias: {
                "suggestions": 1,
                "task_mentions": 2,
                "project_mentions": 3,
                "agenda_mentions": 4,
            },
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        self.assertTrue(plan.should_log)
        self.assertIn("artifact A1", plan.log_message)
        self.assertIn("suggestions=1", plan.log_message)
        self.assertEqual(plan.log_stage_id, "management")

    def test_cleanup_management_for_artifact_skips_when_identity_incomplete(self) -> None:
        plan = ArtifactActionFlowController.cleanup_management_for_artifact(
            "summary",
            "",
            meeting_id="meeting-1",
            run_artifact_alias_cleanup=lambda *_args: {"suggestions": 1},
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        self.assertFalse(plan.should_log)


if __name__ == "__main__":
    unittest.main()
