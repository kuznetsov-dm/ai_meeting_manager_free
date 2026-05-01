from __future__ import annotations

from pathlib import Path
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from aimn.core.meeting_store import FileMeetingStore
from aimn.core.index_types import IndexHit, IndexProvider, IndexQuery


class SqliteIndexProvider(IndexProvider):
    def __init__(self, db_path: Path | str, output_dir: Path | str) -> None:
        self.db_path = Path(db_path)
        self.output_dir = Path(output_dir)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    def on_artifact_written(self, meeting_id: str, alias: Optional[str], kind: str, relpath: str) -> None:
        content = self._read_text(relpath)
        if content is None:
            return
        alias_value = alias or ""
        updated_at = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO artifacts (meeting_id, alias, kind, relpath, content, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_id, alias, kind, relpath)
                DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at
                """,
                (meeting_id, alias_value, kind, relpath, content, updated_at),
            )

    def on_meeting_saved(self, meeting_id: str) -> None:
        store = FileMeetingStore(self.output_dir)
        meeting = None
        for base_name in store.list_meetings():
            try:
                candidate = store.load(base_name)
            except Exception:
                continue
            if candidate.meeting_id == meeting_id:
                meeting = candidate
                break
        if not meeting:
            return
        try:
            with self._conn:
                self._conn.execute("DELETE FROM artifacts WHERE meeting_id = ?", (meeting_id,))
        except sqlite3.Error as exc:
            logging.getLogger("aimn.index").warning("index_meeting_reset error=%s", exc)
            self._reset_schema()
            with self._conn:
                self._conn.execute("DELETE FROM artifacts WHERE meeting_id = ?", (meeting_id,))
        for alias, node in meeting.nodes.items():
            for artifact in node.artifacts:
                self.on_artifact_written(meeting.meeting_id, alias, artifact.kind, artifact.path)

    def search(self, query: IndexQuery) -> Iterable[IndexHit]:
        if not query.query:
            return []
        sql = (
            "SELECT meeting_id, alias, kind, relpath, "
            "snippet(artifacts_fts, 0, '[', ']', '...', 10) AS snippet, "
            "bm25(artifacts_fts) AS score "
            "FROM artifacts_fts WHERE artifacts_fts MATCH ?"
        )
        params: list[object] = [query.query]
        if query.meeting_id:
            sql += " AND meeting_id = ?"
            params.append(query.meeting_id)
        if query.alias:
            sql += " AND alias = ?"
            params.append(query.alias)
        if query.kind:
            sql += " AND kind = ?"
            params.append(query.kind)
        sql += " LIMIT 50"
        rows = self._conn.execute(sql, params).fetchall()
        hits = []
        for meeting_id, alias, kind, relpath, snippet, score in rows:
            hits.append(
                IndexHit(
                    meeting_id=str(meeting_id),
                    alias=str(alias) if alias else None,
                    kind=str(kind),
                    snippet=str(snippet),
                    score=float(score),
                )
            )
        return hits

    def get_text(self, meeting_id: str, alias: Optional[str], kind: str) -> str:
        alias_value = alias or ""
        row = self._conn.execute(
            """
            SELECT content FROM artifacts
            WHERE meeting_id = ? AND alias = ? AND kind = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (meeting_id, alias_value, kind),
        ).fetchone()
        return str(row[0]) if row else ""

    def rebuild(self, meeting_id: Optional[str] = None) -> None:
        store = FileMeetingStore(self.output_dir)
        try:
            if meeting_id:
                with self._conn:
                    self._conn.execute("DELETE FROM artifacts WHERE meeting_id = ?", (meeting_id,))
            else:
                with self._conn:
                    self._conn.execute("DELETE FROM artifacts")
        except sqlite3.Error as exc:
            logging.getLogger("aimn.index").warning(
                "index_rebuild_reset error=%s", exc
            )
            self._reset_schema()
            if meeting_id:
                with self._conn:
                    self._conn.execute("DELETE FROM artifacts WHERE meeting_id = ?", (meeting_id,))
            else:
                with self._conn:
                    self._conn.execute("DELETE FROM artifacts")
        for base_name in store.list_meetings():
            try:
                meeting = store.load(base_name)
            except Exception as exc:
                logging.getLogger("aimn.index").warning(
                    "index_rebuild_meeting_failed base_name=%s error=%s", base_name, exc
                )
                continue
            if meeting_id and meeting.meeting_id != meeting_id:
                continue
            for alias, node in meeting.nodes.items():
                for artifact in node.artifacts:
                    self.on_artifact_written(meeting.meeting_id, alias, artifact.kind, artifact.path)

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    relpath TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(meeting_id, alias, kind, relpath)
                )
                """
            )
            expected_cols = ["content", "meeting_id", "alias", "kind", "relpath"]
            existing_cols = [
                row[1] for row in self._conn.execute("PRAGMA table_info(artifacts_fts)").fetchall()
            ]
            if existing_cols and existing_cols != expected_cols:
                self._conn.execute("DROP TRIGGER IF EXISTS artifacts_ai")
                self._conn.execute("DROP TRIGGER IF EXISTS artifacts_ad")
                self._conn.execute("DROP TRIGGER IF EXISTS artifacts_au")
                self._conn.execute("DROP TABLE IF EXISTS artifacts_fts")
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts
                USING fts5(content, meeting_id, alias, kind, relpath)
                """
            )
            self._conn.execute("DROP TRIGGER IF EXISTS artifacts_ai")
            self._conn.execute("DROP TRIGGER IF EXISTS artifacts_ad")
            self._conn.execute("DROP TRIGGER IF EXISTS artifacts_au")
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS artifacts_ai
                AFTER INSERT ON artifacts BEGIN
                    INSERT INTO artifacts_fts(rowid, content, meeting_id, alias, kind, relpath)
                    VALUES (new.id, new.content, new.meeting_id, new.alias, new.kind, new.relpath);
                END
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS artifacts_ad
                AFTER DELETE ON artifacts BEGIN
                    INSERT INTO artifacts_fts(artifacts_fts, rowid, content, meeting_id, alias, kind, relpath)
                    VALUES('delete', old.id, old.content, old.meeting_id, old.alias, old.kind, old.relpath);
                END
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS artifacts_au
                AFTER UPDATE ON artifacts BEGIN
                    INSERT INTO artifacts_fts(artifacts_fts, rowid, content, meeting_id, alias, kind, relpath)
                    VALUES('delete', old.id, old.content, old.meeting_id, old.alias, old.kind, old.relpath);
                    INSERT INTO artifacts_fts(rowid, content, meeting_id, alias, kind, relpath)
                    VALUES (new.id, new.content, new.meeting_id, new.alias, new.kind, new.relpath);
                END
                """
            )

    def _read_text(self, relpath: str) -> Optional[str]:
        path = self.output_dir / relpath
        if not path.exists():
            return None
        if path.suffix.lower() not in {".txt", ".md", ".json"}:
            return None
        if path.stat().st_size > 1_000_000:
            return None
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

    def _reset_schema(self) -> None:
        with self._conn:
            self._conn.execute("DROP TRIGGER IF EXISTS artifacts_ai")
            self._conn.execute("DROP TRIGGER IF EXISTS artifacts_ad")
            self._conn.execute("DROP TRIGGER IF EXISTS artifacts_au")
            self._conn.execute("DROP TABLE IF EXISTS artifacts_fts")
            self._conn.execute("DROP TABLE IF EXISTS artifacts")
        self._ensure_schema()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            return


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
