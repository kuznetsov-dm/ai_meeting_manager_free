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

from aimn.ui.controllers.transcript_interaction_controller import TranscriptInteractionController  # noqa: E402


class TestTranscriptInteractionController(unittest.TestCase):
    def test_global_search_open_args_requires_meeting_and_kind(self) -> None:
        args = TranscriptInteractionController.global_search_open_args(
            {
                "meeting_id": "m-1",
                "stage_id": "transcription",
                "alias": "T05",
                "kind": "transcript",
                "segment_index": 7,
                "start_ms": 210000,
            }
        )

        self.assertEqual(args, ("m-1", "transcription", "T05", "transcript", 7, 210000))
        self.assertIsNone(TranscriptInteractionController.global_search_open_args({"meeting_id": "m-1"}))

    def test_transcript_selection_payload_normalizes_values(self) -> None:
        payload = TranscriptInteractionController.transcript_selection_payload(
            stage_id="transcription",
            alias="T05",
            kind="transcript",
            selected_text="Alpha",
            evidence={"segment_index_start": 7},
        )

        self.assertEqual(payload["selected_text"], "Alpha")
        self.assertEqual(payload["evidence"]["segment_index_start"], 7)

    def test_transcript_suggestion_payload_preserves_ids_and_evidence(self) -> None:
        payload = TranscriptInteractionController.transcript_suggestion_payload(
            suggestion_id="s-1",
            suggestion_kind="task",
            selected_text="Prepare memo",
            stage_id="transcription",
            alias="T05",
            kind="transcript",
            evidence={"start_ms": 210000},
        )

        self.assertEqual(payload["suggestion_id"], "s-1")
        self.assertEqual(payload["suggestion_kind"], "task")
        self.assertEqual(payload["evidence"]["start_ms"], 210000)


if __name__ == "__main__":
    unittest.main()
