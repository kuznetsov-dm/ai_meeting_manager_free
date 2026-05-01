import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.services.artifact_store_service import ArtifactStoreService
from aimn.domain.meeting import MeetingManifest


class TestArtifactStoreService(unittest.TestCase):
    def test_top_level_artifacts_do_not_clobber_lineage_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            service = ArtifactStoreService(app_root)
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            meeting = MeetingManifest.model_validate(
                {
                    "schema_version": "1.0",
                    "meeting_id": "260101-0000_deadbeef",
                    "base_name": "260101-0000_demo",
                    "created_at": now,
                    "updated_at": now,
                    "storage": {"backend": "files", "output_dir_rel": "."},
                    "source": {"items": []},
                    "nodes": {
                        "twhsmau1": {
                            "stage_id": "transcription",
                            "tool": {"plugin_id": "transcription.whisperadvanced", "version": "1.0"},
                            "params": {},
                            "inputs": {"source_ids": [], "parent_nodes": []},
                            "fingerprint": "sha1:x",
                            "cacheable": True,
                            "created_at": now,
                            "artifacts": [
                                {
                                    "kind": "transcript",
                                    "path": "260101-0000_demo__twhsmau1.transcript.txt",
                                    "content_type": "text",
                                    "user_visible": True,
                                    "meta": {},
                                }
                            ],
                        }
                    },
                    "transcript_relpath": "260101-0000_demo__twhsmau1.transcript.txt",
                }
            )

            artifacts = service.list_artifacts(meeting, include_internal=True)
            transcript = [a for a in artifacts if a.kind == "transcript"]
            self.assertEqual(len(transcript), 1)
            self.assertEqual(transcript[0].stage_id, "transcription")
            self.assertEqual(transcript[0].alias, "twhsmau1")


if __name__ == "__main__":
    unittest.main()

