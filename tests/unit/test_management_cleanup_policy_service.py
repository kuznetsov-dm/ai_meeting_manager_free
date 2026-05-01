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

from aimn.core.management_cleanup_policy_service import ManagementCleanupPolicyService  # noqa: E402


class TestManagementCleanupPolicyService(unittest.TestCase):
    def test_artifact_alias_source_kinds_includes_transcript_selection(self) -> None:
        self.assertEqual(
            ManagementCleanupPolicyService.artifact_alias_source_kinds("transcript"),
            ["transcript", "transcript_selection"],
        )

    def test_build_cleanup_policy_adds_totals_and_flags(self) -> None:
        policy = ManagementCleanupPolicyService.build_cleanup_policy(
            {
                "suggestions": 2,
                "task_mentions": 1,
                "project_mentions": 0,
                "agenda_mentions": 0,
                "orphan_tasks": 1,
                "orphan_projects": 0,
                "orphan_agendas": 0,
            },
            touched_keys=("suggestions", "task_mentions"),
        )

        self.assertTrue(bool(policy["has_changes"]))
        self.assertTrue(bool(policy["has_orphans"]))
        self.assertEqual(int(policy["touched_total"]), 3)
        self.assertEqual(int(policy["orphan_total"]), 1)


if __name__ == "__main__":
    unittest.main()
