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

from aimn.ui.controllers.transcript_navigation_controller import (  # noqa: E402
    TranscriptNavigationController,
)


class TestTranscriptNavigationController(unittest.TestCase):
    def test_row_for_transcript_target_prefers_segment_index(self) -> None:
        row = TranscriptNavigationController.row_for_transcript_target(
            [
                {"segment_index": 6, "start_ms": 1000, "end_ms": 2000},
                {"segment_index": 7, "start_ms": 2001, "end_ms": 3000},
            ],
            segment_index=7,
            start_ms=2500,
        )

        self.assertEqual(row, 1)

    def test_row_for_transcript_target_falls_back_to_timestamp_range(self) -> None:
        row = TranscriptNavigationController.row_for_transcript_target(
            [
                {"start_ms": 1000, "end_ms": 2000},
                {"start_ms": 2001, "end_ms": 3000},
            ],
            start_ms=2600,
        )

        self.assertEqual(row, 1)

    def test_row_for_position_uses_active_blocks(self) -> None:
        row = TranscriptNavigationController.row_for_position(
            [
                (0, 10, {"id": "a"}, 0),
                (11, 25, {"id": "b"}, 1),
            ],
            15,
        )

        self.assertEqual(row, 1)


if __name__ == "__main__":
    unittest.main()
