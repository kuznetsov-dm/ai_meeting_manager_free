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

from aimn.ui.controllers.transcript_evidence_controller import TranscriptSuggestionSpan  # noqa: E402
from aimn.ui.controllers.transcript_view_model_controller import TranscriptViewModelController  # noqa: E402


class TestTranscriptViewModelController(unittest.TestCase):
    def test_build_segment_items_formats_label_and_payload(self) -> None:
        items = TranscriptViewModelController.build_segment_items(
            [
                {
                    "index": 7,
                    "start_ms": 210000,
                    "end_ms": 216000,
                    "speaker": "Ivan",
                    "text": "Let's have Ivan prepare the launch memo by Friday",
                }
            ],
            [(0, 51)],
            format_ms=lambda ms: "00:03:30",
        )

        self.assertEqual(len(items), 1)
        self.assertIn("00:03:30", items[0].label)
        self.assertIn("Ivan", items[0].label)
        self.assertEqual(items[0].payload["segment_index"], 7)
        self.assertEqual(items[0].payload["text_range"], (0, 51))

    def test_suggestion_span_at_position_prefers_smallest_matching_span(self) -> None:
        span = TranscriptViewModelController.suggestion_span_at_position(
            [
                TranscriptSuggestionSpan("a", "task", "A", 0, 20, 0.7, "A", {}),
                TranscriptSuggestionSpan("b", "task", "B", 5, 10, 0.6, "B", {}),
            ],
            7,
        )

        self.assertIsNotNone(span)
        self.assertEqual(span.suggestion_id, "b")


if __name__ == "__main__":
    unittest.main()
