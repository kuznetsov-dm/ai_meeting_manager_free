import json
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.contracts import (
    KIND_ASR_SEGMENTS_JSON,
    KIND_DETECTED_LANGUAGE,
    KIND_SEGMENTS,
    KIND_TRANSCRIPT,
    PluginOutput,
)  # noqa: E402
from aimn.core.meeting_store import FileMeetingStore  # noqa: E402
from aimn.core.services.artifact_writer import ArtifactWriter  # noqa: E402
from aimn.core.services.transcription_artifacts import persist_transcription_outputs  # noqa: E402


class TestTranscriptionArtifacts(unittest.TestCase):
    def test_persists_transcription_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            store = FileMeetingStore(output_dir)
            writer = ArtifactWriter(
                output_dir,
                store,
                stage_id="transcription",
                validator=lambda *_args: None,
                event_callback=None,
            )
            payload = {"segments": [{"start": 0.0, "end": 1.0, "text": "Hi"}]}
            outputs = [
                PluginOutput(kind=KIND_TRANSCRIPT, content="Hello", content_type="text", user_visible=True),
                PluginOutput(
                    kind=KIND_ASR_SEGMENTS_JSON,
                    content=json.dumps(payload),
                    content_type="json",
                    user_visible=False,
                ),
                PluginOutput(
                    kind=KIND_DETECTED_LANGUAGE,
                    content="en",
                    content_type="text/plain",
                    user_visible=False,
                ),
                PluginOutput(kind="custom", content="note", content_type="text/plain", user_visible=False),
            ]
            result, error = persist_transcription_outputs(
                base_name="m",
                alias=None,
                outputs=outputs,
                writer=writer,
            )
            self.assertIsNone(error)
            self.assertIsNotNone(result)
            self.assertTrue((output_dir / result.transcript_relpath).exists())
            self.assertTrue((output_dir / result.segments_relpath).exists())
            kinds = {artifact.kind for artifact in result.artifacts}
            self.assertIn(KIND_TRANSCRIPT, kinds)
            self.assertIn(KIND_SEGMENTS, kinds)
            self.assertNotIn(KIND_ASR_SEGMENTS_JSON, kinds)
            self.assertIn("custom", kinds)
            self.assertEqual(result.detected_language, "en")


if __name__ == "__main__":
    unittest.main()
