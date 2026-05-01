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

from aimn.ui.controllers.meeting_context_menu_controller import (  # noqa: E402
    MeetingContextMenuController,
)


class TestMeetingContextMenuController(unittest.TestCase):
    def test_build_stage_actions_returns_rerun_only(self) -> None:
        specs = MeetingContextMenuController.build_stage_actions(
            rerun_label="Rerun stage",
            pipeline_running=False,
            has_active_meeting=True,
        )

        self.assertEqual([(spec.action, spec.enabled) for spec in specs], [("rerun_stage", True)])

    def test_build_stage_actions_disables_items_while_pipeline_running(self) -> None:
        specs = MeetingContextMenuController.build_stage_actions(
            rerun_label="Rerun stage",
            pipeline_running=True,
            has_active_meeting=True,
        )

        self.assertEqual([(spec.action, spec.enabled) for spec in specs], [("rerun_stage", False)])

    def test_build_artifact_actions_respects_active_meeting_and_meeting_id(self) -> None:
        specs = MeetingContextMenuController.build_artifact_actions(
            rerun_same_label="Rerun same",
            rerun_stage_label="Rerun stage",
            cleanup_management_label="Cleanup",
            pipeline_running=False,
            has_active_meeting=False,
            has_meeting_id=True,
        )

        self.assertEqual(
            [(spec.action, spec.enabled) for spec in specs],
            [
                ("rerun_same", False),
                ("rerun_stage", False),
                ("cleanup_management", True),
            ],
        )

    def test_build_artifact_actions_returns_core_actions_only(self) -> None:
        specs = MeetingContextMenuController.build_artifact_actions(
            rerun_same_label="Rerun same",
            rerun_stage_label="Rerun stage",
            cleanup_management_label="Cleanup",
            pipeline_running=False,
            has_active_meeting=True,
            has_meeting_id=False,
        )

        self.assertEqual(
            [(spec.action, spec.enabled) for spec in specs],
            [
                ("rerun_same", True),
                ("rerun_stage", True),
                ("cleanup_management", False),
            ],
        )


if __name__ == "__main__":
    unittest.main()
