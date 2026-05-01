import json
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

from aimn.plugins.interfaces import Artifact, ArtifactMeta, HookContext  # noqa: E402
from plugins.management.unified.unified import hook_unified_management  # noqa: E402


class TestManagementTranscriptEvidence(unittest.TestCase):
    def test_summary_task_candidates_can_bind_to_transcript_segments(self) -> None:
        summary_text = "\n".join(
            [
                "## Action Items",
                "- Create launch plan, confirm owner, attach slide deck",
            ]
        )
        segments_payload = json.dumps(
            [
                {
                    "index": 0,
                    "start_ms": 0,
                    "end_ms": 4000,
                    "text": "We need to create the launch plan and confirm the owner tomorrow.",
                },
                {
                    "index": 1,
                    "start_ms": 4000,
                    "end_ms": 8000,
                    "text": "After that we should attach the slide deck to the ticket.",
                },
            ]
        )
        transcript_text = (
            "We need to create the launch plan and confirm the owner tomorrow.\n"
            "After that we should attach the slide deck to the ticket."
        )
        output_dir = repo_root / ".codex_tmp_test" / "management_transcript_evidence"
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = HookContext(
            plugin_id="management.unified",
            meeting_id="m-transcript-evidence",
            alias="mg-evidence",
            plugin_config={},
            _output_dir=str(output_dir),
            _schema_resolver=lambda kind: (
                __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                    content_type="json",
                    user_visible=True,
                )
                if str(kind) == "management_suggestions"
                else None
            ),
            _get_artifact=lambda kind: {
                "summary": Artifact(
                    meta=ArtifactMeta(kind="summary", path="m__S01.summary.md", content_type="text/markdown"),
                    content=summary_text,
                ),
                "segments": Artifact(
                    meta=ArtifactMeta(kind="segments", path="m__T01.segments.json", content_type="application/json"),
                    content=segments_payload,
                ),
                "transcript": Artifact(
                    meta=ArtifactMeta(kind="transcript", path="m__T01.transcript.txt", content_type="text/plain"),
                    content=transcript_text,
                ),
            }.get(str(kind), None),
        )

        hook_unified_management(ctx)
        built = ctx.build_result()
        payload = json.loads(built.outputs[0].content)

        self.assertEqual(len(payload), 1)
        evidence = payload[0]["evidence"][0]
        self.assertEqual(evidence["source"], "transcript")
        self.assertEqual(evidence["segment_index"], 0)
        self.assertEqual(evidence["segment_index_start"], 0)
        self.assertEqual(evidence["segment_index_end"], 0)


if __name__ == "__main__":
    unittest.main()
