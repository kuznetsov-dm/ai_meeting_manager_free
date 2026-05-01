import sqlite3
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

from aimn.core.management_cleanup_service import ManagementCleanupService  # noqa: E402


class TestManagementCleanupService(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE management_suggestions (suggestion_id TEXT PRIMARY KEY, source_meeting_id TEXT, source_kind TEXT, source_alias TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE task_mentions (task_id TEXT, meeting_id TEXT, source_kind TEXT, source_alias TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE project_mentions (project_id TEXT, meeting_id TEXT, source_kind TEXT, source_alias TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE agenda_mentions (agenda_id TEXT, meeting_id TEXT, source_kind TEXT, source_alias TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE entity_links (left_type TEXT, left_id TEXT, right_type TEXT, right_id TEXT)"
        )
        self.deleted: list[tuple[str, str]] = []
        self.orphan_map: dict[tuple[str, str], list[str]] = {}
        self.artifact_orphan_map: dict[tuple[str, str, str, str], list[str]] = {}
        self.service = ManagementCleanupService(
            self.conn,
            count_rows=self._count_rows,
            orphan_entity_ids=self._orphan_entity_ids,
            orphan_entity_ids_for_artifact_cleanup=self._orphan_entity_ids_for_artifact_cleanup,
            delete_task=lambda entity_id: self.deleted.append(("task", entity_id)) or True,
            delete_project=lambda entity_id: self.deleted.append(("project", entity_id)) or True,
            delete_agenda=lambda entity_id: self.deleted.append(("agenda", entity_id)) or True,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def _count_rows(self, table: str, where: str, params: tuple[object, ...]) -> int:
        row = self.conn.execute(f"SELECT COUNT(1) FROM {table} WHERE {where}", params).fetchone()
        return int(row[0] or 0) if row else 0

    def _orphan_entity_ids(self, entity_type: str, *, removing_meeting_id: str = "") -> list[str]:
        return list(self.orphan_map.get((entity_type, removing_meeting_id), []))

    def _orphan_entity_ids_for_artifact_cleanup(
        self,
        entity_type: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
    ) -> list[str]:
        return list(self.artifact_orphan_map.get((entity_type, meeting_id, source_kind, source_alias), []))

    def test_preview_artifact_alias_cleanup_accumulates_transcript_variants(self) -> None:
        self.conn.executemany(
            "INSERT INTO task_mentions(task_id, meeting_id, source_kind, source_alias) VALUES (?, ?, ?, ?)",
            [("t1", "m1", "transcript", "A1"), ("t2", "m1", "transcript_selection", "A1")],
        )
        self.artifact_orphan_map[("task", "m1", "transcript", "A1")] = ["t1"]
        self.artifact_orphan_map[("task", "m1", "transcript_selection", "A1")] = ["t2"]

        preview = self.service.preview_artifact_alias_cleanup(
            meeting_id="m1",
            artifact_kind="transcript",
            source_alias="A1",
        )

        self.assertEqual(preview["task_mentions"], 2)
        self.assertEqual(preview["orphan_tasks"], 2)

    def test_cleanup_meeting_deletes_orphans_when_requested(self) -> None:
        self.conn.execute(
            "INSERT INTO management_suggestions(suggestion_id, source_meeting_id, source_kind, source_alias) VALUES ('s1', 'm1', 'summary', 'A1')"
        )
        self.conn.execute(
            "INSERT INTO agenda_mentions(agenda_id, meeting_id, source_kind, source_alias) VALUES ('a1', 'm1', 'summary', 'A1')"
        )
        self.orphan_map[("agenda", "m1")] = ["a1"]

        result = self.service.cleanup_meeting("m1", delete_orphan_entities=True)

        self.assertEqual(result["suggestions"], 1)
        self.assertEqual(result["agenda_mentions"], 1)
        self.assertEqual(result["deleted_orphan_agendas"], 1)
        self.assertEqual(self.deleted, [("agenda", "a1")])


if __name__ == "__main__":
    unittest.main()
