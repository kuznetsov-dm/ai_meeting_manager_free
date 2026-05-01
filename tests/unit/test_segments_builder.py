import json
import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.services.segments_builder import build_segments_from_asr  # noqa: E402


class TestSegmentsBuilder(unittest.TestCase):
    def test_build_segments_from_asr_parses_records(self) -> None:
        payload = {
            "segments": [
                {"start": 0.0, "end": 1.25, "text": "Hello", "speaker": "A", "confidence": 0.9}
            ]
        }
        segments_index, records = build_segments_from_asr(json.dumps(payload))
        self.assertEqual(len(segments_index), 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "Hello")

    def test_build_segments_from_asr_falls_back_to_transcript(self) -> None:
        payload = {"segments": []}
        segments_index, records = build_segments_from_asr(
            json.dumps(payload),
            fallback_transcript="Fallback text",
        )
        self.assertEqual(len(segments_index), 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "Fallback text")

    def test_build_segments_from_asr_empty_without_fallback(self) -> None:
        payload = {"segments": []}
        segments_index, records = build_segments_from_asr(json.dumps(payload))
        self.assertEqual(segments_index, [])
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
