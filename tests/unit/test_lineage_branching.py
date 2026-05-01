import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.fingerprinting import compute_fingerprint
from aimn.core.lineage import apply_branching, ensure_branched_mode
from aimn.core.meeting_store import FileMeetingStore
from aimn.domain.meeting import (  # noqa: E402
    ArtifactRef,
    LineageNode,
    MeetingManifest,
    NodeInputs,
    NodeTool,
    SCHEMA_VERSION,
    SourceInfo,
    StorageInfo,
)


def _make_manifest() -> MeetingManifest:
    return MeetingManifest(
        schema_version=SCHEMA_VERSION,
        meeting_id="260101-0000_test",
        base_name="260101-0000_test",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        storage=StorageInfo(),
        source=SourceInfo(),
    )


def _add_node(
    manifest: MeetingManifest,
    alias: str,
    stage_id: str,
    fingerprint: str,
    *,
    cacheable: bool = True,
    artifacts: list[ArtifactRef] | None = None,
    parent_nodes: list[str] | None = None,
) -> None:
    manifest.nodes[alias] = LineageNode(
        stage_id=stage_id,
        tool=NodeTool(plugin_id="test", version="1"),
        params={},
        inputs=NodeInputs(parent_nodes=parent_nodes or []),
        fingerprint=fingerprint,
        cacheable=cacheable,
        artifacts=artifacts or [],
        created_at="2026-01-01T00:00:00Z",
    )


class TestLineageBranching(unittest.TestCase):
    def test_switches_on_conflict(self) -> None:
        manifest = _make_manifest()
        _add_node(manifest, "tgen1", "transcription", "fp-1")

        branched = ensure_branched_mode(manifest, "transcription", "fp-2")

        self.assertTrue(branched)
        self.assertEqual(manifest.naming_mode, "branched")

    def test_no_switch_for_same_fingerprint(self) -> None:
        manifest = _make_manifest()
        _add_node(manifest, "tgen1", "transcription", "fp-1")

        branched = ensure_branched_mode(manifest, "transcription", "fp-1")

        self.assertFalse(branched)
        self.assertEqual(manifest.naming_mode, "single")

    def test_ignores_non_cacheable_nodes(self) -> None:
        manifest = _make_manifest()
        _add_node(manifest, "tgen1", "transcription", "fp-1", cacheable=False)

        branched = ensure_branched_mode(manifest, "transcription", "fp-2")

        self.assertFalse(branched)
        self.assertEqual(manifest.naming_mode, "single")

    def test_skips_management_stage(self) -> None:
        manifest = _make_manifest()
        _add_node(manifest, "mgen1", "management", "fp-1")

        branched = ensure_branched_mode(manifest, "management", "fp-2")

        self.assertFalse(branched)
        self.assertEqual(manifest.naming_mode, "single")

    def test_realigns_transcription_artifacts_on_branch(self) -> None:
        manifest = _make_manifest()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            store = FileMeetingStore(output_dir)
            transcript_relpath = store.resolve_artifact_path(
                manifest.base_name,
                None,
                "transcript",
                "txt",
            )
            segments_relpath = store.resolve_artifact_path(
                manifest.base_name,
                None,
                "segments",
                "json",
            )
            (output_dir / transcript_relpath).write_text("hello", encoding="utf-8")
            (output_dir / segments_relpath).write_text("[]", encoding="utf-8")
            manifest.transcript_relpath = transcript_relpath
            manifest.segments_relpath = segments_relpath
            _add_node(
                manifest,
                "tgen1",
                "transcription",
                "fp-1",
                artifacts=[
                    ArtifactRef(kind="transcript", path=transcript_relpath),
                    ArtifactRef(kind="segments", path=segments_relpath),
                ],
            )

            branched = apply_branching(
                manifest,
                "transcription",
                "fp-2",
                force_branch=True,
                output_dir=output_dir,
            )

            self.assertTrue(branched)
            self.assertEqual(manifest.naming_mode, "branched")
            expected_transcript = store.resolve_artifact_path(
                manifest.base_name,
                "tgen1",
                "transcript",
                "txt",
            )
            expected_segments = store.resolve_artifact_path(
                manifest.base_name,
                "tgen1",
                "segments",
                "json",
            )
            self.assertEqual(manifest.transcript_relpath, expected_transcript)
            self.assertEqual(manifest.segments_relpath, expected_segments)
            self.assertTrue((output_dir / expected_transcript).exists())
            self.assertTrue((output_dir / expected_segments).exists())

    def test_realigns_aliases_when_parent_branches(self) -> None:
        manifest = _make_manifest()
        _add_node(manifest, "tgen1", "transcription", "fp-1")
        _add_node(manifest, "tgen2", "transcription", "fp-2")
        manifest.naming_mode = "branched"

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            store = FileMeetingStore(output_dir)
            edited_relpath = store.resolve_artifact_path(
                manifest.base_name,
                None,
                "edited",
                "md",
            )
            (output_dir / edited_relpath).write_text("ok", encoding="utf-8")
            _add_node(
                manifest,
                "sgen1",
                "text_processing",
                "fp-3",
                parent_nodes=["tgen1"],
                artifacts=[ArtifactRef(kind="edited", path=edited_relpath)],
            )

            apply_branching(
                manifest,
                "text_processing",
                "fp-4",
                output_dir=output_dir,
            )

            self.assertIn("tgen1-sgen1", manifest.nodes)
            self.assertNotIn("sgen1", manifest.nodes)
            expected_path = store.resolve_artifact_path(
                manifest.base_name,
                "tgen1-sgen1",
                "edited",
                "md",
            )
            node = manifest.nodes["tgen1-sgen1"]
            self.assertEqual(node.inputs.parent_nodes, ["tgen1"])
            self.assertEqual(node.artifacts[0].path, expected_path)
            self.assertTrue((output_dir / expected_path).exists())

    def test_llm_prompt_signature_changes_force_branching(self) -> None:
        manifest = _make_manifest()
        fp1 = compute_fingerprint(
            "llm_processing",
            "llm.openrouter",
            "1.0.0",
            {"plugin_id": "llm.openrouter", "model_id": "meta-llama/llama-3.3-70b-instruct:free", "prompt_signature": "sig_a"},
            ["src_fp"],
        )
        fp2 = compute_fingerprint(
            "llm_processing",
            "llm.openrouter",
            "1.0.0",
            {"plugin_id": "llm.openrouter", "model_id": "meta-llama/llama-3.3-70b-instruct:free", "prompt_signature": "sig_b"},
            ["src_fp"],
        )
        _add_node(manifest, "aior1", "llm_processing", fp1)
        branched = ensure_branched_mode(manifest, "llm_processing", fp2)
        self.assertTrue(branched)
        self.assertEqual(manifest.naming_mode, "branched")


if __name__ == "__main__":
    unittest.main()
