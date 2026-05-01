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

from aimn.core.services.pipeline_service import (  # noqa: E402
    _aggregate_llm_model_outcomes,
    _sync_active_transcription_alias,
    _sync_active_llm_alias,
    _parse_llm_model_outcome,
)
from aimn.domain.meeting import ArtifactRef, LineageNode, MeetingManifest, NodeInputs, NodeTool, SourceInfo, StorageInfo  # noqa: E402


class TestPipelineServiceModelOutcomes(unittest.TestCase):
    def test_parse_llm_model_outcome(self) -> None:
        item = _parse_llm_model_outcome(
            'llm_model_outcome:{"plugin_id":"llm.openrouter","model_id":"m1","summary_quality":"usable","failure_code":""}'
        )

        self.assertEqual(
            item,
            {
                "plugin_id": "llm.openrouter",
                "model_id": "m1",
                "summary_quality": "usable",
                "failure_code": "",
            },
        )

    def test_aggregate_prefers_usable_over_failed_for_same_model(self) -> None:
        rows = _aggregate_llm_model_outcomes(
            [
                {
                    "plugin_id": "llm.openrouter",
                    "model_id": "m1",
                    "summary_quality": "failed",
                    "failure_code": "timeout",
                },
                {
                    "plugin_id": "llm.openrouter",
                    "model_id": "m1",
                    "summary_quality": "usable",
                    "failure_code": "",
                },
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["availability_status"], "ready")
        self.assertEqual(rows[0]["summary_quality"], "usable")
        self.assertEqual(rows[0]["failure_code"], "")

    def test_aggregate_marks_degraded_as_limited(self) -> None:
        rows = _aggregate_llm_model_outcomes(
            [
                {
                    "plugin_id": "llm.ollama",
                    "model_id": "llama3.2",
                    "summary_quality": "degraded",
                    "failure_code": "llm_degraded_summary_artifact",
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["availability_status"], "limited")
        self.assertEqual(rows[0]["summary_quality"], "degraded")

    def test_sync_active_transcription_alias_prefers_current_transcript_relpath(self) -> None:
        meeting = MeetingManifest(
            schema_version="1.0",
            meeting_id="260101-0000_demo",
            base_name="260101-0000_demo_file",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            storage=StorageInfo(),
            source=SourceInfo(),
            transcript_relpath="260101-0000_demo_file__twhtnau2.transcript.txt",
            active_aliases={"transcription": "twhtnau1"},
            nodes={
                "twhtnau1": LineageNode(
                    stage_id="transcription",
                    tool=NodeTool(plugin_id="transcription.whisperadvanced", version="0.1.0"),
                    params={"model": "tiny"},
                    inputs=NodeInputs(source_ids=["sha1:src"], parent_nodes=[]),
                    fingerprint="sha1:one",
                    artifacts=[
                        ArtifactRef(
                            kind="transcript",
                            path="260101-0000_demo_file__twhtnau1.transcript.txt",
                            content_type="text",
                            user_visible=True,
                        )
                    ],
                ),
                "twhtnau2": LineageNode(
                    stage_id="transcription",
                    tool=NodeTool(plugin_id="transcription.whisperadvanced", version="0.1.0"),
                    params={"model": "tiny"},
                    inputs=NodeInputs(source_ids=["sha1:src"], parent_nodes=[]),
                    fingerprint="sha1:two",
                    artifacts=[
                        ArtifactRef(
                            kind="transcript",
                            path="260101-0000_demo_file__twhtnau2.transcript.txt",
                            content_type="text",
                            user_visible=True,
                        )
                    ],
                ),
            },
        )

        _sync_active_transcription_alias(meeting)

        self.assertEqual(meeting.active_aliases.get("transcription"), "twhtnau2")

    def test_sync_active_llm_alias_prefers_latest_summary_node(self) -> None:
        meeting = MeetingManifest(
            schema_version="1.0",
            meeting_id="260101-0000_demo",
            base_name="260101-0000_demo_file",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            storage=StorageInfo(),
            source=SourceInfo(),
            active_aliases={"llm_processing": "oldsum"},
            nodes={
                "oldsum": LineageNode(
                    stage_id="llm_processing",
                    created_at="2026-01-01T00:01:00Z",
                    tool=NodeTool(plugin_id="llm.zai", version="0.1.0"),
                    params={"model": "a"},
                    inputs=NodeInputs(source_ids=["sha1:src"], parent_nodes=[]),
                    fingerprint="sha1:one",
                    artifacts=[
                        ArtifactRef(
                            kind="summary",
                            path="260101-0000_demo_file__oldsum.summary.md",
                            content_type="text/markdown",
                            user_visible=True,
                        )
                    ],
                ),
                "newsum": LineageNode(
                    stage_id="llm_processing",
                    created_at="2026-01-01T00:02:00Z",
                    tool=NodeTool(plugin_id="llm.llama_cli", version="0.1.0"),
                    params={"model": "b"},
                    inputs=NodeInputs(source_ids=["sha1:src"], parent_nodes=[]),
                    fingerprint="sha1:two",
                    artifacts=[
                        ArtifactRef(
                            kind="summary",
                            path="260101-0000_demo_file__newsum.summary.md",
                            content_type="text/markdown",
                            user_visible=True,
                        )
                    ],
                ),
            },
        )

        _sync_active_llm_alias(meeting)

        self.assertEqual(meeting.active_aliases.get("llm_processing"), "newsum")


if __name__ == "__main__":
    unittest.main()
