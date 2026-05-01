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

from aimn.ui.controllers.search_action_controller import SearchActionController  # noqa: E402


class TestSearchActionController(unittest.TestCase):
    def test_submit_decision_for_local_and_global(self) -> None:
        self.assertEqual(
            SearchActionController.submit_decision(mode="local", query="memo"),
            ("run_local", "memo"),
        )
        self.assertEqual(
            SearchActionController.submit_decision(mode="global", query="memo"),
            ("emit_global", "memo"),
        )
        self.assertEqual(
            SearchActionController.submit_decision(mode="global", query="   "),
            ("clear_global", ""),
        )

    def test_clear_decision_distinguishes_local_and_global(self) -> None:
        self.assertEqual(
            SearchActionController.clear_decision(mode="local", query="memo"),
            ("reset_local", True),
        )
        self.assertEqual(
            SearchActionController.clear_decision(mode="global", query="memo"),
            ("clear_global", True),
        )

    def test_highlight_decision_requires_non_empty_query(self) -> None:
        self.assertEqual(SearchActionController.highlight_decision(" memo "), (True, "memo"))
        self.assertEqual(SearchActionController.highlight_decision("   "), (False, ""))


if __name__ == "__main__":
    unittest.main()
