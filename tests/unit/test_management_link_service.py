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

from aimn.core.management_link_service import ManagementLinkService, canonical_link  # noqa: E402


class TestManagementLinkService(unittest.TestCase):
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
        self.service = ManagementLinkService(self.conn, utc_now_iso=lambda: "2026-03-29T00:00:00Z")

    def tearDown(self) -> None:
        self.conn.close()

    def test_canonical_link_orders_pairs(self) -> None:
        self.assertEqual(
            canonical_link("project", "p1", "task", "t1"),
            ("project", "p1", "task", "t1"),
        )
        self.assertEqual(
            canonical_link("task", "t1", "project", "p1"),
            ("project", "p1", "task", "t1"),
        )

    def test_link_and_unlink_entities_round_trip(self) -> None:
        self.assertTrue(
            self.service.link_entities(
                left_type="task",
                left_id="t1",
                right_type="project",
                right_id="p1",
            )
        )
        self.assertEqual(
            self.service.linked_entity_ids("task", "t1", related_type="project"),
            {"p1"},
        )
        self.assertEqual(len(self.service.list_links_for(entity_type="task", entity_id="t1")), 1)
        self.assertTrue(
            self.service.unlink_entities(
                left_type="project",
                left_id="p1",
                right_type="task",
                right_id="t1",
            )
        )
        self.assertEqual(
            self.service.linked_entity_ids("task", "t1", related_type="project"),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
