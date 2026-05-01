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

from aimn.core.management_suggestion_repository import ManagementSuggestionRepository  # noqa: E402


class TestManagementSuggestionRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """
            CREATE TABLE management_suggestions (
                suggestion_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                normalized_key TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                reasoning_short TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'suggested',
                source_meeting_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_alias TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                approved_entity_type TEXT NOT NULL DEFAULT '',
                approved_entity_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.repo = ManagementSuggestionRepository(
            self.conn,
            utc_now_iso=lambda: "2026-03-29T00:00:00Z",
            normalize_text=lambda value: " ".join(str(value or "").strip().lower().split()),
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_upsert_suggestion_updates_existing_row_and_preserves_identity(self) -> None:
        suggestion_id = self.repo.upsert_suggestion(
            kind="project",
            title="Website refresh",
            normalized_key="Website refresh",
            source_meeting_id="m1",
            source_kind="summary",
            source_alias="A1",
            confidence=0.2,
        )

        same_id = self.repo.upsert_suggestion(
            kind="project",
            title="Website refresh updated",
            normalized_key="website refresh",
            source_meeting_id="m1",
            source_kind="summary",
            source_alias="A1",
            confidence=0.9,
            evidence=[{"text": "explicit scope"}],
        )

        row = self.repo.load_suggestion_row(suggestion_id)
        self.assertEqual(same_id, suggestion_id)
        self.assertIsNotNone(row)
        self.assertEqual(row.title, "Website refresh updated")
        self.assertEqual(row.confidence, 0.9)

    def test_list_and_set_state_round_trip(self) -> None:
        suggestion_id = self.repo.upsert_suggestion(
            kind="task",
            title="Send recap",
            source_meeting_id="m2",
            source_kind="manual",
            source_alias="",
        )

        self.assertTrue(self.repo.set_suggestion_state(suggestion_id, state="hidden"))
        rows = self.repo.list_suggestions(state="hidden", meeting_id="m2")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], suggestion_id)
        self.assertEqual(rows[0]["state"], "hidden")


if __name__ == "__main__":
    unittest.main()
