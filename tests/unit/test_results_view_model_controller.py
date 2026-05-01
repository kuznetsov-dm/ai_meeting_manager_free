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

from aimn.ui.controllers.results_view_model_controller import ResultsViewModelController  # noqa: E402


class TestResultsViewModelController(unittest.TestCase):
    def test_build_prepares_items_blocks_text_and_highlight_terms(self) -> None:
        model = ResultsViewModelController.build(
            query="launch memo",
            rows=[
                {
                    "title": "Demo  00:03:30  #7",
                    "preview": "Prepare the launch memo by Friday",
                    "text": "Prepare the launch memo by Friday",
                    "payload": {"meeting_id": "m-1", "segment_index": 7, "start_ms": 210000},
                    "terms": ["launch memo", "Friday"],
                }
            ],
        )

        items = list(model["items"])
        self.assertEqual(len(items), 1)
        self.assertIn("Demo", items[0].title)
        self.assertIn("launch memo", model["text"])
        self.assertEqual(model["active_blocks"], [(0, len("Prepare the launch memo by Friday\n\n"), {"meeting_id": "m-1", "segment_index": 7, "start_ms": 210000}, 0)])
        self.assertIn("launch memo", model["highlight_terms"])


if __name__ == "__main__":
    unittest.main()
