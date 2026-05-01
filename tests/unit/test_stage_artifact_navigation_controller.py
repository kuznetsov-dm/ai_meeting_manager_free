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

from aimn.ui.controllers.stage_artifact_navigation_controller import (  # noqa: E402
    StageArtifactNavigationController,
)


class TestStageArtifactNavigationController(unittest.TestCase):
    def test_stage_and_artifact_kind_mappings_are_consistent(self) -> None:
        self.assertEqual(StageArtifactNavigationController.artifact_kind_for_stage("transcription"), "transcript")
        self.assertEqual(StageArtifactNavigationController.artifact_kind_for_stage("text_processing"), "edited")
        self.assertEqual(StageArtifactNavigationController.artifact_kind_for_stage("llm_processing"), "summary")
        self.assertEqual(StageArtifactNavigationController.stage_id_for_artifact_kind("summary"), "llm_processing")
        self.assertEqual(StageArtifactNavigationController.stage_id_for_artifact_kind("edited"), "text_processing")

    def test_ui_and_runtime_stage_id_translation(self) -> None:
        self.assertEqual(StageArtifactNavigationController.ui_stage_id("text_processing"), "text_processing")
        self.assertEqual(StageArtifactNavigationController.ui_stage_id("transcription"), "transcription")
        self.assertEqual(
            StageArtifactNavigationController.runtime_stage_id_for_ui("llm_processing"),
            "llm_processing",
        )
        self.assertEqual(
            StageArtifactNavigationController.runtime_stage_id_for_ui("transcription"),
            "transcription",
        )

    def test_open_stage_artifact_plan_selects_kind_when_artifact_exists(self) -> None:
        plan = StageArtifactNavigationController.open_stage_artifact_plan(
            stage_id="llm_processing",
            active_meeting_base_name="m-base",
            active_artifacts=[SimpleNamespace(kind="summary"), SimpleNamespace(kind="transcript")],
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        self.assertEqual(plan.select_kind, "summary")
        self.assertEqual(plan.log_message, "")

    def test_open_stage_artifact_plan_returns_log_when_kind_missing(self) -> None:
        plan = StageArtifactNavigationController.open_stage_artifact_plan(
            stage_id="llm_processing",
            active_meeting_base_name="m-base",
            active_artifacts=[SimpleNamespace(kind="transcript")],
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        self.assertEqual(plan.select_kind, "")
        self.assertIn("No 'summary' artifacts", plan.log_message)

    def test_open_stage_artifact_plan_skips_without_active_meeting(self) -> None:
        plan = StageArtifactNavigationController.open_stage_artifact_plan(
            stage_id="llm_processing",
            active_meeting_base_name="",
            active_artifacts=[SimpleNamespace(kind="summary")],
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        self.assertEqual(plan.select_kind, "")
        self.assertEqual(plan.log_message, "")


if __name__ == "__main__":
    unittest.main()
