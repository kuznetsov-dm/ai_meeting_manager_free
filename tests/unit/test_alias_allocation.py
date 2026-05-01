import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.node_registry import allocate_alias  # noqa: E402
from aimn.domain.meeting import (  # noqa: E402
    MeetingManifest,
    SCHEMA_VERSION,
    SourceInfo,
    StorageInfo,
    LineageNode,
    NodeInputs,
    NodeTool,
)


class TestAliasAllocation(unittest.TestCase):
    def test_allocates_next_alias_for_stage(self) -> None:
        meeting = MeetingManifest(
            schema_version=SCHEMA_VERSION,
            meeting_id="250101-0000_abcd",
            base_name="250101-0000_meeting",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
            storage=StorageInfo(),
            source=SourceInfo(),
        )
        meeting.nodes["sgen1"] = LineageNode(
            stage_id="text_processing",
            tool=NodeTool(plugin_id="text_processing.minutes_heuristic_v2", version="0.1.0"),
            params={},
            inputs=NodeInputs(source_ids=[], parent_nodes=[]),
            fingerprint="fp1",
            artifacts=[],
        )
        meeting.nodes["sgen2"] = LineageNode(
            stage_id="text_processing",
            tool=NodeTool(plugin_id="text_processing.minutes_heuristic_v2", version="0.1.0"),
            params={},
            inputs=NodeInputs(source_ids=[], parent_nodes=[]),
            fingerprint="fp2",
            artifacts=[],
        )
        alias = allocate_alias(meeting, "text_processing", {}, [])
        self.assertEqual(alias, "sgen3")


if __name__ == "__main__":
    unittest.main()
