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

from aimn.ui.controllers.main_text_panel_global_results_controller import (  # noqa: E402
    MainTextPanelGlobalResultsController,
)


class TestMainTextPanelGlobalResultsController(unittest.TestCase):
    def test_apply_results_builds_visible_rows(self) -> None:
        state = MainTextPanelGlobalResultsController.apply_results(
            query="roadmap",
            hits=[{"meeting_id": "m1"}],
            answer="answer",
            build_rows=lambda query, hits: [{"query": query, "count": len(hits)}],
        )

        self.assertTrue(state.changed)
        self.assertTrue(state.visible)
        self.assertEqual(state.rows, [{"query": "roadmap", "count": 1}])

    def test_clear_results_reports_no_change_when_already_empty(self) -> None:
        state = MainTextPanelGlobalResultsController.clear_results(
            visible=False,
            query="",
            hits=[],
            answer="",
        )

        self.assertFalse(state.changed)
        self.assertFalse(state.visible)
        self.assertEqual(state.query, "")


if __name__ == "__main__":
    unittest.main()
