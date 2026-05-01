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

from aimn.ui.controllers.transcript_menu_controller import TranscriptMenuController  # noqa: E402


class TestTranscriptMenuController(unittest.TestCase):
    def test_selection_action_specs_cover_all_manual_create_actions(self) -> None:
        specs = TranscriptMenuController.selection_action_specs()

        self.assertEqual([item.action_name for item in specs], ["task", "project", "agenda"])

    def test_suggestion_action_specs_cover_approve_hide_and_create_actions(self) -> None:
        specs = TranscriptMenuController.suggestion_action_specs()

        self.assertEqual(
            [item.action_name for item in specs],
            ["approve", "hide", "create_task", "create_project", "create_agenda"],
        )

    def test_selection_menu_bundle_builds_payload_and_specs(self) -> None:
        bundle = TranscriptMenuController.selection_menu_bundle(
            stage_id="transcription",
            alias="T05",
            kind="transcript",
            selected_text="Prepare launch memo",
            evidence={"segment_index_start": 2},
        )

        assert bundle is not None
        self.assertEqual(bundle.payload["selected_text"], "Prepare launch memo")
        self.assertEqual(bundle.payload["evidence"]["segment_index_start"], 2)
        self.assertEqual([item.action_name for item in bundle.action_specs], ["task", "project", "agenda"])
        self.assertEqual(bundle.separator_indexes, ())

    def test_suggestion_menu_bundle_builds_payload_and_separator_indexes(self) -> None:
        bundle = TranscriptMenuController.suggestion_menu_bundle(
            suggestion_id="s-1",
            suggestion_kind="task",
            selected_text="Prepare launch memo",
            stage_id="management",
            alias="A1",
            kind="transcript",
            evidence={"start_ms": 1000},
        )

        assert bundle is not None
        self.assertEqual(bundle.payload["suggestion_id"], "s-1")
        self.assertEqual(bundle.payload["suggestion_kind"], "task")
        self.assertEqual(bundle.payload["evidence"]["start_ms"], 1000)
        self.assertEqual(bundle.separator_indexes, (2,))

    def test_menu_bundle_rejects_empty_core_fields(self) -> None:
        self.assertIsNone(
            TranscriptMenuController.selection_menu_bundle(
                stage_id="transcription",
                alias="T05",
                kind="transcript",
                selected_text="",
                evidence={},
            )
        )
        self.assertIsNone(
            TranscriptMenuController.suggestion_menu_bundle(
                suggestion_id="",
                suggestion_kind="task",
                selected_text="Prepare launch memo",
                stage_id="management",
                alias="A1",
                kind="transcript",
                evidence={},
            )
        )


if __name__ == "__main__":
    unittest.main()
