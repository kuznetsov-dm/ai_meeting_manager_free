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

from aimn.ui.controllers.global_search_request_controller import GlobalSearchRequestController  # noqa: E402


class TestGlobalSearchRequestController(unittest.TestCase):
    def test_normalize_request_marks_empty_query_for_clear(self) -> None:
        request = GlobalSearchRequestController.normalize_request(
            query="",
            mode="global",
            normalized_mode="global",
        )
        self.assertTrue(request["should_clear"])

    def test_normalize_request_marks_non_global_mode_for_clear(self) -> None:
        request = GlobalSearchRequestController.normalize_request(
            query="roadmap",
            mode="local",
            normalized_mode="local",
        )
        self.assertTrue(request["should_clear"])

    def test_stale_detection_compares_request_ids(self) -> None:
        self.assertTrue(
            GlobalSearchRequestController.is_stale(
                done_request_id=1,
                current_request_id=2,
            )
        )
        self.assertFalse(
            GlobalSearchRequestController.is_stale(
                done_request_id=3,
                current_request_id=3,
            )
        )


if __name__ == "__main__":
    unittest.main()
