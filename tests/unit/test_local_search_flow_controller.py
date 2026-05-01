# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPlainTextEdit

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.local_search_flow_controller import (
    LocalSearchFlowController,
    LocalSearchResetPlan,
)


class TestLocalSearchFlowController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_reset_plan_preserves_global_results_highlights_on_results_tab(self) -> None:
        plan = LocalSearchFlowController.reset_plan(
            clear_query=False,
            is_local_mode=False,
            global_results_visible=True,
            current_tab_index=0,
        )

        self.assertEqual(
            plan,
            LocalSearchResetPlan(
                clear_query=False,
                matches_text="",
                prev_enabled=False,
                next_enabled=False,
                clear_search_layer=False,
                clear_focus_layer=False,
            ),
        )

    def test_run_search_returns_match_state_and_moves_to_first_match(self) -> None:
        editor = QPlainTextEdit()
        editor.setPlainText("Alpha beta gamma beta")

        result = LocalSearchFlowController.run_search(editor, "beta")

        self.assertEqual(len(result.match_cursors), 2)
        self.assertEqual(result.match_index, 0)
        self.assertEqual(result.matches_text, "1/2")
        self.assertTrue(result.prev_enabled)
        self.assertTrue(result.next_enabled)
        self.assertEqual(result.highlight_count, 2)
        self.assertEqual(editor.textCursor().selectedText(), "beta")

    def test_step_match_cycles_to_next_result(self) -> None:
        editor = QPlainTextEdit()
        editor.setPlainText("Alpha beta gamma beta")
        run = LocalSearchFlowController.run_search(editor, "beta")

        step = LocalSearchFlowController.step_match(
            editor,
            run.match_cursors,
            run.match_index,
            1,
        )

        self.assertIsNotNone(step)
        self.assertEqual(step.match_index, 1)
        self.assertEqual(step.matches_text, "2/2")
        self.assertEqual(editor.textCursor().selectedText(), "beta")


if __name__ == "__main__":
    unittest.main()
