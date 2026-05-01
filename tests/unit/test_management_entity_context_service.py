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

from aimn.core.management_entity_context_service import ManagementEntityContextService  # noqa: E402
from aimn.core.management_link_service import ManagementLinkService  # noqa: E402


class TestManagementEntityContextService(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """
            CREATE TABLE entity_links (
                link_id TEXT PRIMARY KEY,
                left_type TEXT NOT NULL,
                left_id TEXT NOT NULL,
                right_type TEXT NOT NULL,
                right_id TEXT NOT NULL,
                relation TEXT NOT NULL DEFAULT 'linked',
                created_at TEXT NOT NULL,
                UNIQUE(left_type, left_id, right_type, right_id, relation)
            )
            """
        )
        self.conn.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY, pinned INTEGER NOT NULL DEFAULT 0)")
        self.conn.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, pinned INTEGER NOT NULL DEFAULT 0)")
        self.conn.execute("CREATE TABLE agendas (agenda_id TEXT PRIMARY KEY, pinned INTEGER NOT NULL DEFAULT 0)")
        self.conn.execute(
            "CREATE TABLE task_mentions (task_id TEXT NOT NULL, meeting_id TEXT NOT NULL, source_kind TEXT NOT NULL, source_alias TEXT NOT NULL)"
        )
        self.conn.execute(
            "CREATE TABLE project_mentions (project_id TEXT NOT NULL, meeting_id TEXT NOT NULL, source_kind TEXT NOT NULL, source_alias TEXT NOT NULL)"
        )
        self.conn.execute(
            "CREATE TABLE agenda_mentions (agenda_id TEXT NOT NULL, meeting_id TEXT NOT NULL, source_kind TEXT NOT NULL, source_alias TEXT NOT NULL)"
        )
        self.link_service = ManagementLinkService(self.conn, utc_now_iso=lambda: "2026-03-29T00:00:00Z")
        self.service = ManagementEntityContextService(
            self.conn,
            linked_entity_ids=self.link_service.linked_entity_ids,
            list_links_for=self.link_service.list_links_for,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_meeting_ids_and_provenance_include_mentions_and_links(self) -> None:
        self.conn.execute("INSERT INTO tasks(task_id, pinned) VALUES ('t1', 0)")
        self.conn.execute(
            "INSERT INTO task_mentions(task_id, meeting_id, source_kind, source_alias) VALUES ('t1', 'm1', 'manual', '')"
        )
        self.conn.execute(
            "INSERT INTO task_mentions(task_id, meeting_id, source_kind, source_alias) VALUES ('t1', 'm2', 'summary', 'A1')"
        )
        self.link_service.link_entities(
            left_type="task",
            left_id="t1",
            right_type="meeting",
            right_id="m3",
        )

        self.assertEqual(self.service.meeting_ids_for("task", "t1"), ["m1", "m2", "m3"])
        self.assertEqual(
            self.service.mention_provenance_for("task", "t1"),
            {
                "mention_count": 2,
                "manual_mentions": 1,
                "ai_mentions": 1,
                "source_kinds": ["manual", "summary"],
            },
        )

    def test_orphan_entity_ids_skip_linked_and_pinned_entities(self) -> None:
        self.conn.executemany(
            "INSERT INTO projects(project_id, pinned) VALUES (?, ?)",
            [("p1", 0), ("p2", 1), ("p3", 0)],
        )
        self.conn.execute(
            "INSERT INTO project_mentions(project_id, meeting_id, source_kind, source_alias) VALUES ('p3', 'm-keep', 'manual', '')"
        )
        self.link_service.link_entities(
            left_type="project",
            left_id="p1",
            right_type="task",
            right_id="t-linked",
        )

        self.assertEqual(self.service.orphan_entity_ids("project"), [])
        self.assertEqual(self.service.orphan_entity_ids("project", removing_meeting_id="m-keep"), ["p3"])

    def test_orphan_entity_ids_for_artifact_cleanup_only_return_last_unlinked_unpinned_mentions(self) -> None:
        self.conn.executemany(
            "INSERT INTO tasks(task_id, pinned) VALUES (?, ?)",
            [("t1", 0), ("t2", 0), ("t3", 1)],
        )
        self.conn.executemany(
            "INSERT INTO task_mentions(task_id, meeting_id, source_kind, source_alias) VALUES (?, ?, ?, ?)",
            [
                ("t1", "m1", "summary", "A1"),
                ("t2", "m1", "summary", "A1"),
                ("t2", "m1", "summary", "A2"),
                ("t3", "m1", "summary", "A1"),
            ],
        )
        self.link_service.link_entities(
            left_type="task",
            left_id="t1",
            right_type="project",
            right_id="p-linked",
        )

        self.assertEqual(
            self.service.orphan_entity_ids_for_artifact_cleanup("task", "m1", "summary", "A1"),
            [],
        )

        self.link_service.unlink_entities(
            left_type="task",
            left_id="t1",
            right_type="project",
            right_id="p-linked",
        )
        self.assertEqual(
            self.service.orphan_entity_ids_for_artifact_cleanup("task", "m1", "summary", "A1"),
            ["t1"],
        )


if __name__ == "__main__":
    unittest.main()
