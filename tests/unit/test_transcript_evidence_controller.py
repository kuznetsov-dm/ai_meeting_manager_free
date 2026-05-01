import sys
import unittest
from pathlib import Path

from PySide6.QtGui import QTextCursor, QTextDocument

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.transcript_evidence_controller import (  # noqa: E402
    TranscriptEvidenceController,
)


class TestTranscriptEvidenceController(unittest.TestCase):
    def test_load_segments_records_reads_dict_payload_and_caches(self) -> None:
        calls: list[str] = []

        def provider(relpath: str) -> str:
            calls.append(relpath)
            return '{"records":[{"index":1,"text":"Alpha"},{"index":2,"text":"Beta"}]}'

        controller = TranscriptEvidenceController(provider)

        first = controller.load_segments_records("segments.json")
        second = controller.load_segments_records("segments.json")

        self.assertEqual(len(first), 2)
        self.assertEqual(first, second)
        self.assertEqual(calls, ["segments.json"])

    def test_transcript_suggestions_for_alias_filters_non_matching_evidence(self) -> None:
        suggestions = [
            {
                "id": "s-1",
                "kind": "task",
                "evidence": [
                    {"source": "transcript", "alias": "T05", "text": "Alpha"},
                    {"source": "summary", "alias": "v1", "text": "Ignored"},
                ],
            },
            {
                "id": "s-2",
                "kind": "project",
                "evidence": [{"source": "transcript", "alias": "T06", "text": "Beta"}],
            },
        ]

        rows = TranscriptEvidenceController.transcript_suggestions_for_alias(suggestions, "T05")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "s-1")
        self.assertEqual(len(rows[0]["transcript_evidence"]), 1)
        self.assertEqual(rows[0]["transcript_evidence"][0]["alias"], "T05")

    def test_selection_evidence_payload_spans_multiple_segments(self) -> None:
        document = QTextDocument("Alpha line\nBeta line\nGamma line")
        cursor = QTextCursor(document)
        start = document.toPlainText().index("Beta")
        end = document.toPlainText().index("Gamma") + len("Gamma line")
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        ranges = [(0, 10), (11, 20), (21, 31)]
        records = [
            {"index": 0, "start_ms": 0, "end_ms": 1000, "speaker": "A"},
            {"index": 1, "start_ms": 1000, "end_ms": 2000, "speaker": "B"},
            {"index": 2, "start_ms": 2000, "end_ms": 3000, "speaker": "C"},
        ]

        payload = TranscriptEvidenceController.selection_evidence_payload(cursor, ranges, records)

        self.assertEqual(payload["segment_index_start"], 1)
        self.assertEqual(payload["segment_index_end"], 2)
        self.assertEqual(payload["start_ms"], 1000)
        self.assertEqual(payload["end_ms"], 3000)
        self.assertEqual(payload["speaker"], "B")

    def test_find_segment_row_by_timestamp_uses_segment_window(self) -> None:
        records = [
            {"index": 7, "start_ms": 210000, "end_ms": 216000},
            {"index": 8, "start_ms": 216001, "end_ms": 225000},
        ]

        row = TranscriptEvidenceController.find_segment_row_by_timestamp(records, 216.5)

        self.assertEqual(row, 1)

    def test_build_transcript_suggestion_spans_prefers_shorter_matching_window(self) -> None:
        records = [
            {"index": 7, "text": "Let's have Ivan prepare the"},
            {"index": 8, "text": "launch memo by Friday and send it around"},
            {"index": 9, "text": "Then we will review budget risks"},
        ]
        ranges = [(0, 28), (29, 70), (71, 102)]
        suggestions = [
            {
                "id": "s-1",
                "kind": "task",
                "title": "Prepare launch memo by Friday",
                "confidence": 0.9,
                "transcript_evidence": [
                    {
                        "segment_index_start": 7,
                        "segment_index_end": 9,
                        "text": "Prepare launch memo by Friday",
                    }
                ],
            }
        ]

        spans = TranscriptEvidenceController.build_transcript_suggestion_spans(records, ranges, suggestions)

        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0].left, spans[0].right), (29, 70))


if __name__ == "__main__":
    unittest.main()
