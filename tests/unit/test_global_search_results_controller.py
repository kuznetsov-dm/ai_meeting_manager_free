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

from aimn.ui.controllers.global_search_results_controller import (  # noqa: E402
    GlobalSearchResultsController,
)


class TestGlobalSearchResultsController(unittest.TestCase):
    def test_build_rows_filters_non_actionable_and_dedupes_anchor(self) -> None:
        rows = GlobalSearchResultsController.build_rows(
            "launch memo",
            [
                {
                    "meeting_id": "m-1",
                    "meeting_label": "Demo",
                    "stage_id": "transcription",
                    "alias": "T05",
                    "kind": "transcript",
                    "segment_index": 7,
                    "start_ms": 210000,
                    "snippet": "Prepare the [launch memo] by Friday",
                },
                {
                    "meeting_id": "m-1",
                    "meeting_label": "Demo",
                    "stage_id": "transcription",
                    "alias": "T05",
                    "kind": "transcript",
                    "segment_index": 7,
                    "start_ms": 210000,
                    "snippet": "Prepare the [launch memo] by Friday",
                },
                {
                    "meeting_id": "m-2",
                    "stage_id": "summary",
                    "alias": "v1",
                    "kind": "summary",
                    "snippet": "No anchor",
                },
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertIn("Demo", rows[0]["title"])
        self.assertIn("#7", rows[0]["title"])
        self.assertEqual(rows[0]["payload"]["meeting_id"], "m-1")

    def test_result_excerpt_prefers_context_window(self) -> None:
        excerpt = GlobalSearchResultsController.result_excerpt_from_hit(
            {
                "context": "Intro. Prepare the launch memo by Friday. Outro.",
                "snippet": "[launch memo]",
            },
            terms=["launch", "memo"],
        )

        self.assertIn("Prepare the launch memo by Friday.", excerpt)
        self.assertNotEqual(excerpt, "launch memo")

    def test_marked_terms_from_snippet_extracts_bracketed_tokens(self) -> None:
        terms = GlobalSearchResultsController.marked_terms_from_snippet(
            "Alpha [launch memo] beta [Friday]"
        )

        self.assertEqual(terms, ["launch memo", "Friday"])


if __name__ == "__main__":
    unittest.main()
