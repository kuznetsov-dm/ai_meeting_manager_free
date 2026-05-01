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

from aimn.ui.controllers.search_mode_controller import SearchModeController  # noqa: E402


class TestSearchModeController(unittest.TestCase):
    def test_normalize_modes_maps_legacy_modes_to_global_and_keeps_local(self) -> None:
        modes = SearchModeController.normalize_modes(["simple", "local", "smart", "global"])

        self.assertEqual(modes, ["global", "local"])

    def test_normalized_mode_defaults_to_local(self) -> None:
        self.assertEqual(SearchModeController.normalized_mode("smart"), "global")
        self.assertEqual(SearchModeController.normalized_mode(""), "local")

    def test_ui_state_for_local_and_global(self) -> None:
        local_state = SearchModeController.ui_state(
            mode="local",
            has_matches=True,
            global_results_visible=True,
        )
        self.assertTrue(local_state["show_match_nav"])
        self.assertTrue(local_state["match_nav_enabled"])
        self.assertTrue(local_state["clear_global_results"])

        global_state = SearchModeController.ui_state(
            mode="global",
            has_matches=True,
            global_results_visible=False,
        )
        self.assertFalse(global_state["show_match_nav"])
        self.assertFalse(global_state["clear_global_results"])
        self.assertTrue(global_state["reset_local_search"])


if __name__ == "__main__":
    unittest.main()
