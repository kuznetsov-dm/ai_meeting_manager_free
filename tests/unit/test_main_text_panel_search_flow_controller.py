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

from aimn.ui.controllers.main_text_panel_search_flow_controller import MainTextPanelSearchFlowController  # noqa: E402


class TestMainTextPanelSearchFlowController(unittest.TestCase):
    def test_highlight_request_forces_local_mode(self) -> None:
        should_highlight, query, target_mode = MainTextPanelSearchFlowController.highlight_request(" roadmap ")
        self.assertTrue(should_highlight)
        self.assertEqual(query, "roadmap")
        self.assertEqual(target_mode, "local")

    def test_submit_request_for_global_empty_query_clears(self) -> None:
        action, query = MainTextPanelSearchFlowController.submit_request(mode="global", query=" ")
        self.assertEqual(action, "clear_global")
        self.assertEqual(query, "")

    def test_mode_ui_state_hides_match_nav_for_global_mode(self) -> None:
        state = MainTextPanelSearchFlowController.mode_ui_state(
            mode="global",
            has_matches=True,
            global_results_visible=False,
        )
        self.assertFalse(bool(state.get("show_match_nav")))
        self.assertTrue(bool(state.get("reset_local_search")))


if __name__ == "__main__":
    unittest.main()
