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

from aimn.ui.controllers.artifact_view_data_controller import ArtifactViewDataController  # noqa: E402


class TestArtifactViewDataController(unittest.TestCase):
    def test_resolve_segments_relpath_prefers_stage_alias_key(self) -> None:
        relpath = ArtifactViewDataController.resolve_segments_relpath(
            stage_id="transcription",
            alias="T05",
            segments_relpaths={
                "transcription:T05": "segments/by_stage.json",
                "T05": "segments/by_alias.json",
            },
        )

        self.assertEqual(relpath, "segments/by_stage.json")

    def test_build_transcript_artifact_data_returns_none_without_records(self) -> None:
        data = ArtifactViewDataController.build_transcript_artifact_data(
            stage_id="transcription",
            alias="T05",
            relpath="transcript.txt",
            segments_relpaths={"T05": "segments.json"},
            load_segments_records=lambda _relpath: [],
            load_artifact_text=lambda _relpath: "Transcript",
            transcript_suggestions_for_alias=lambda _alias: [],
            build_segment_text_ranges=lambda _text, _records: [],
            build_transcript_suggestion_spans=lambda _records, _ranges, _suggestions: [],
        )

        self.assertIsNone(data)

    def test_build_transcript_artifact_data_collects_records_ranges_and_spans(self) -> None:
        records = [{"index": 7, "text": "Alpha"}]
        data = ArtifactViewDataController.build_transcript_artifact_data(
            stage_id="transcription",
            alias="T05",
            relpath="transcript.txt",
            segments_relpaths={"T05": "segments.json"},
            load_segments_records=lambda _relpath: records,
            load_artifact_text=lambda _relpath: "Alpha",
            transcript_suggestions_for_alias=lambda _alias: [{"id": "s-1"}],
            build_segment_text_ranges=lambda _text, _records: [(0, 5)],
            build_transcript_suggestion_spans=lambda _records, _ranges, _suggestions: ["span-1"],
        )

        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data.transcript_text, "Alpha")
        self.assertEqual(data.records, records)
        self.assertEqual(data.ranges, [(0, 5)])
        self.assertEqual(data.suggestion_spans, ["span-1"])


if __name__ == "__main__":
    unittest.main()
