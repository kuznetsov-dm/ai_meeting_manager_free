from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from aimn.core.app_paths import get_app_root, get_output_dir
from aimn.core.contracts import KIND_AUDIO, KIND_SEGMENTS, KIND_TRANSCRIPT
from aimn.core.search_query import normalize_search_query


@dataclass(frozen=True)
class SearchHit:
    meeting_id: str
    stage_id: str
    alias: str
    kind: str
    relpath: str
    snippet: str
    score: float
    segment_index: int = -1
    start_ms: int = -1
    end_ms: int = -1
    content: str = ""
    context: str = ""


def _snippet_around_query(text: str, query: str, *, radius: int = 160) -> str:
    source = str(text or "")
    q = str(query or "").strip()
    if not source:
        return ""
    if not q:
        return source[:320]
    match = re.search(re.escape(q), source, flags=re.IGNORECASE)
    if not match:
        return source[:320]
    start = max(0, int(match.start()) - int(radius))
    end = min(len(source), int(match.end()) + int(radius))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(source) else ""
    return (
        f"{prefix}"
        f"{source[start:match.start()]}"
        f"[{source[match.start():match.end()]}]"
        f"{source[match.end():end]}"
        f"{suffix}"
    )


class SqliteFtsSearchIndex:
    def __init__(self, *, app_root: Path, index_relpath: str) -> None:
        self._app_root = Path(app_root)
        self._output_dir = get_output_dir(self._app_root)
        self._db_path = (self._output_dir / index_relpath).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def on_artifact_written(self, meeting_id: str, stage_id: str, alias: str, kind: str, relpath: str) -> None:
        mid = str(meeting_id or "").strip()
        sid = str(stage_id or "").strip() or "meeting"
        al = str(alias or "")
        k = str(kind or "").strip()
        rp = str(relpath or "").strip()
        if not mid or not k or not rp:
            return
        if k == KIND_AUDIO:
            return
        if k == KIND_SEGMENTS:
            records = self._read_segments_records(rp)
            if not records:
                return
            updated_at = _utc_now_iso()
            with self._connect() as conn:
                # Replace segment set atomically for this artifact scope to avoid stale tail rows.
                conn.execute(
                    """
                    DELETE FROM segments
                    WHERE meeting_id = ? AND stage_id = ? AND alias = ? AND kind = ?
                    """,
                    (mid, sid, al, KIND_TRANSCRIPT),
                )
                for rec in records:
                    text = str(rec.get("text") or "").strip()
                    if not text:
                        continue
                    try:
                        seg_index = int(rec.get("index") if rec.get("index") is not None else 0)
                    except Exception:
                        seg_index = 0
                    try:
                        start_ms = int(rec.get("start_ms") or 0)
                    except Exception:
                        start_ms = 0
                    try:
                        end_ms = int(rec.get("end_ms") or 0)
                    except Exception:
                        end_ms = 0
                    conn.execute(
                        """
                        INSERT INTO segments (
                            meeting_id, stage_id, alias, kind, segments_relpath,
                            segment_index, start_ms, end_ms, content, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(meeting_id, stage_id, alias, kind, segment_index)
                        DO UPDATE SET
                            segments_relpath=excluded.segments_relpath,
                            start_ms=excluded.start_ms,
                            end_ms=excluded.end_ms,
                            content=excluded.content,
                            updated_at=excluded.updated_at
                        """,
                        (
                            mid,
                            sid,
                            al,
                            KIND_TRANSCRIPT,
                            rp,
                            int(seg_index),
                            int(start_ms),
                            int(end_ms),
                            text,
                            updated_at,
                        ),
                    )
            return

        content = self._read_text(rp)
        if content is None:
            return
        updated_at = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (meeting_id, stage_id, alias, kind, relpath, content, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(meeting_id, stage_id, alias, kind, relpath)
                DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at
                """,
                (mid, sid, al, k, rp, content, updated_at),
            )

    def search(
        self,
        query: str,
        *,
        meeting_id: str = "",
        kind: str = "",
        stage_id: str = "",
        alias: str = "",
        limit: int = 50,
    ) -> list[SearchHit]:
        q = normalize_search_query(query)
        if not q:
            return []
        mid = str(meeting_id or "").strip()
        k = str(kind or "").strip()
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        limit_int = max(1, min(int(limit or 50), 200))

        try:
            hits = self._search_fts(q, meeting_id=mid, kind=k, stage_id=sid, alias=al, limit=limit_int)
            if not hits:
                # Some local FTS configurations/tokenizers can miss non-latin tokens.
                # Fallback to LIKE to keep "word inclusion" search reliable.
                hits = self._search_like(q, meeting_id=mid, kind=k, stage_id=sid, alias=al, limit=limit_int)
        except sqlite3.Error:
            # Fallback for malformed MATCH syntax / tokenizer quirks: LIKE-based search.
            try:
                hits = self._search_like(q, meeting_id=mid, kind=k, stage_id=sid, alias=al, limit=limit_int)
            except sqlite3.Error:
                # Keep the UX non-blocking even when the local index is stale/corrupt.
                hits = []
        hits.sort(key=lambda h: float(h.score))
        return hits[:limit_int]

    def _search_fts(
        self,
        query: str,
        *,
        meeting_id: str,
        kind: str,
        stage_id: str,
        alias: str,
        limit: int,
    ) -> list[SearchHit]:
        hits: list[SearchHit] = []

        with self._connect(readonly=True) as conn:
            # Segment-level search for transcripts.
            if not kind or kind == KIND_TRANSCRIPT:
                seg_sql = (
                    "SELECT s.meeting_id, s.stage_id, s.alias, s.kind, s.segments_relpath, "
                    "s.segment_index, s.start_ms, s.end_ms, "
                    "snippet(segments_fts, 0, '[', ']', '...', 10) AS snippet, "
                    "bm25(segments_fts) AS score, s.content "
                    "FROM segments_fts "
                    "JOIN segments s ON s.id = segments_fts.rowid "
                    "WHERE segments_fts MATCH ?"
                )
                seg_params: list[object] = [query]
                if meeting_id:
                    seg_sql += " AND s.meeting_id = ?"
                    seg_params.append(meeting_id)
                if stage_id:
                    seg_sql += " AND s.stage_id = ?"
                    seg_params.append(stage_id)
                if alias:
                    seg_sql += " AND s.alias = ?"
                    seg_params.append(alias)
                seg_sql += " ORDER BY bm25(segments_fts) LIMIT ?"
                seg_params.append(limit)
                for row in conn.execute(seg_sql, seg_params).fetchall():
                    current_mid = str(row[0] or "")
                    current_sid = str(row[1] or "")
                    current_alias = str(row[2] or "")
                    current_seg_index = int(row[5] if row[5] is not None else -1)
                    hits.append(
                        SearchHit(
                            meeting_id=current_mid,
                            stage_id=current_sid,
                            alias=current_alias,
                            kind=str(row[3] or ""),
                            relpath=str(row[4] or ""),
                            segment_index=current_seg_index,
                            start_ms=int(row[6] if row[6] is not None else -1),
                            end_ms=int(row[7] if row[7] is not None else -1),
                            snippet=str(row[8] or ""),
                            score=float(row[9]),
                            content=str(row[10] or ""),
                            context=self._segment_context(
                                conn,
                                meeting_id=current_mid,
                                stage_id=current_sid,
                                alias=current_alias,
                                segment_index=current_seg_index,
                            ),
                        )
                    )

            # Artifact-level search.
            art_sql = (
                "SELECT a.meeting_id, a.stage_id, a.alias, a.kind, a.relpath, "
                "snippet(artifacts_fts, 0, '[', ']', '...', 10) AS snippet, "
                "bm25(artifacts_fts) AS score, a.content "
                "FROM artifacts_fts "
                "JOIN artifacts a ON a.id = artifacts_fts.rowid "
                "WHERE artifacts_fts MATCH ?"
            )
            art_params: list[object] = [query]
            if meeting_id:
                art_sql += " AND a.meeting_id = ?"
                art_params.append(meeting_id)
            if stage_id:
                art_sql += " AND a.stage_id = ?"
                art_params.append(stage_id)
            if alias:
                art_sql += " AND a.alias = ?"
                art_params.append(alias)
            if kind:
                art_sql += " AND a.kind = ?"
                art_params.append(kind)
            art_sql += " ORDER BY bm25(artifacts_fts) LIMIT ?"
            art_params.append(limit)
            for row in conn.execute(art_sql, art_params).fetchall():
                hits.append(
                    SearchHit(
                        meeting_id=str(row[0]),
                        stage_id=str(row[1] or ""),
                        alias=str(row[2] or ""),
                        kind=str(row[3] or ""),
                        relpath=str(row[4] or ""),
                        snippet=str(row[5] or ""),
                        score=float(row[6]),
                        content=str(row[7] or ""),
                    )
                )
        return hits

    def _search_like(
        self,
        query: str,
        *,
        meeting_id: str,
        kind: str,
        stage_id: str,
        alias: str,
        limit: int,
    ) -> list[SearchHit]:
        token = f"%{str(query or '').lower()}%"
        hits: list[SearchHit] = []
        with self._connect(readonly=True) as conn:
            if not kind or kind == KIND_TRANSCRIPT:
                seg_sql = (
                    "SELECT meeting_id, stage_id, alias, kind, segments_relpath, "
                    "segment_index, start_ms, end_ms, content "
                    "FROM segments WHERE lower(content) LIKE ?"
                )
                seg_params: list[object] = [token]
                if meeting_id:
                    seg_sql += " AND meeting_id = ?"
                    seg_params.append(meeting_id)
                if stage_id:
                    seg_sql += " AND stage_id = ?"
                    seg_params.append(stage_id)
                if alias:
                    seg_sql += " AND alias = ?"
                    seg_params.append(alias)
                seg_sql += " ORDER BY rowid DESC LIMIT ?"
                seg_params.append(limit)
                for row in conn.execute(seg_sql, seg_params).fetchall():
                    text = str(row[8] or "")
                    current_mid = str(row[0] or "")
                    current_sid = str(row[1] or "")
                    current_alias = str(row[2] or "")
                    current_seg_index = int(row[5] if row[5] is not None else -1)
                    hits.append(
                        SearchHit(
                            meeting_id=current_mid,
                            stage_id=current_sid,
                            alias=current_alias,
                            kind=str(row[3] or ""),
                            relpath=str(row[4] or ""),
                            segment_index=current_seg_index,
                            start_ms=int(row[6] if row[6] is not None else -1),
                            end_ms=int(row[7] if row[7] is not None else -1),
                            snippet=_snippet_around_query(text, query),
                            score=1_000_000.0,
                            content=text,
                            context=self._segment_context(
                                conn,
                                meeting_id=current_mid,
                                stage_id=current_sid,
                                alias=current_alias,
                                segment_index=current_seg_index,
                            ),
                        )
                    )
            art_sql = (
                "SELECT meeting_id, stage_id, alias, kind, relpath, content "
                "FROM artifacts WHERE lower(content) LIKE ?"
            )
            art_params: list[object] = [token]
            if meeting_id:
                art_sql += " AND meeting_id = ?"
                art_params.append(meeting_id)
            if stage_id:
                art_sql += " AND stage_id = ?"
                art_params.append(stage_id)
            if alias:
                art_sql += " AND alias = ?"
                art_params.append(alias)
            if kind:
                art_sql += " AND kind = ?"
                art_params.append(kind)
            art_sql += " ORDER BY rowid DESC LIMIT ?"
            art_params.append(limit)
            for row in conn.execute(art_sql, art_params).fetchall():
                text = str(row[5] or "")
                hits.append(
                    SearchHit(
                        meeting_id=str(row[0] or ""),
                        stage_id=str(row[1] or ""),
                        alias=str(row[2] or ""),
                        kind=str(row[3] or ""),
                        relpath=str(row[4] or ""),
                        snippet=_snippet_around_query(text, query),
                        score=1_000_000.0,
                        content=text,
                    )
                )

        return hits

    def document_count(self) -> int:
        try:
            with self._connect(readonly=True) as conn:
                row_a = conn.execute("SELECT COUNT(1) FROM artifacts").fetchone()
                row_s = conn.execute("SELECT COUNT(1) FROM segments").fetchone()
            return int((row_a[0] if row_a else 0) + (row_s[0] if row_s else 0))
        except Exception:
            return 0

    def _segment_context(
        self,
        conn: sqlite3.Connection,
        *,
        meeting_id: str,
        stage_id: str,
        alias: str,
        segment_index: int,
        before: int = 1,
        after: int = 1,
    ) -> str:
        center = int(segment_index)
        if center < 0:
            return ""
        left = max(0, center - max(0, int(before)))
        right = center + max(0, int(after))
        rows = conn.execute(
            """
            SELECT content
            FROM segments
            WHERE meeting_id = ? AND stage_id = ? AND alias = ? AND kind = ?
              AND segment_index BETWEEN ? AND ?
            ORDER BY segment_index ASC
            """,
            (meeting_id, stage_id, alias, KIND_TRANSCRIPT, int(left), int(right)),
        ).fetchall()
        lines = [str(row[0] or "").strip() for row in rows]
        lines = [line for line in lines if line]
        return "\n".join(lines).strip()

    def get_text(self, meeting_id: str, alias: str, kind: str) -> str:
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                """
                SELECT content FROM artifacts
                WHERE meeting_id = ? AND alias = ? AND kind = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (meeting_id, alias or "", kind),
            ).fetchone()
        return str(row[0]) if row else ""

    def rebuild(self, *, meeting_id: str = "") -> None:
        meetings = self._list_meetings()
        try:
            with self._connect() as conn:
                if meeting_id:
                    conn.execute("DELETE FROM artifacts WHERE meeting_id = ?", (meeting_id,))
                    conn.execute("DELETE FROM segments WHERE meeting_id = ?", (meeting_id,))
                else:
                    conn.execute("DELETE FROM artifacts")
                    conn.execute("DELETE FROM segments")
        except sqlite3.Error:
            # Recover from stale/corrupt trigger+FTS state by recreating the index file.
            self._recreate_database()
        for meta in meetings:
            if meeting_id and meta.get("meeting_id") != meeting_id:
                continue
            mid = str(meta.get("meeting_id") or "").strip()
            if not mid:
                continue
            for alias, stage_id, kind, relpath in _meeting_artifacts(meta):
                self.on_artifact_written(mid, stage_id, alias, kind, relpath)

    # ---- internals ----

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        path = str(self._db_path)
        if readonly:
            # URI form required for mode=ro.
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        else:
            conn = sqlite3.connect(path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _recreate_database(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{self._db_path}{suffix}")
            try:
                target.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                continue
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            existing_art_cols = [row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()]
            if existing_art_cols and "stage_id" not in set(existing_art_cols):
                conn.execute("DROP TRIGGER IF EXISTS artifacts_ai")
                conn.execute("DROP TRIGGER IF EXISTS artifacts_ad")
                conn.execute("DROP TRIGGER IF EXISTS artifacts_au")
                conn.execute("DROP TABLE IF EXISTS artifacts_fts")
                conn.execute("DROP TABLE IF EXISTS artifacts")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    stage_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    relpath TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(meeting_id, stage_id, alias, kind, relpath)
                )
                """
            )
            expected_cols = ["content", "meeting_id", "stage_id", "alias", "kind", "relpath"]
            existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(artifacts_fts)").fetchall()]
            if existing_cols and existing_cols != expected_cols:
                conn.execute("DROP TRIGGER IF EXISTS artifacts_ai")
                conn.execute("DROP TRIGGER IF EXISTS artifacts_ad")
                conn.execute("DROP TRIGGER IF EXISTS artifacts_au")
                conn.execute("DROP TABLE IF EXISTS artifacts_fts")

            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts
                USING fts5(content, meeting_id, stage_id, alias, kind, relpath)
                """
            )
            conn.execute("DROP TRIGGER IF EXISTS artifacts_ai")
            conn.execute("DROP TRIGGER IF EXISTS artifacts_ad")
            conn.execute("DROP TRIGGER IF EXISTS artifacts_au")
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS artifacts_ai
                AFTER INSERT ON artifacts BEGIN
                    INSERT INTO artifacts_fts(rowid, content, meeting_id, stage_id, alias, kind, relpath)
                    VALUES (new.id, new.content, new.meeting_id, new.stage_id, new.alias, new.kind, new.relpath);
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS artifacts_ad
                AFTER DELETE ON artifacts BEGIN
                    DELETE FROM artifacts_fts WHERE rowid = old.id;
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS artifacts_au
                AFTER UPDATE ON artifacts BEGIN
                    DELETE FROM artifacts_fts WHERE rowid = old.id;
                    INSERT INTO artifacts_fts(rowid, content, meeting_id, stage_id, alias, kind, relpath)
                    VALUES (new.id, new.content, new.meeting_id, new.stage_id, new.alias, new.kind, new.relpath);
                END
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    stage_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    segments_relpath TEXT NOT NULL,
                    segment_index INTEGER NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(meeting_id, stage_id, alias, kind, segment_index)
                )
                """
            )
            existing_seg_cols = [row[1] for row in conn.execute("PRAGMA table_info(segments)").fetchall()]
            if existing_seg_cols and "segments_relpath" not in set(existing_seg_cols):
                conn.execute("DROP TRIGGER IF EXISTS segments_ai")
                conn.execute("DROP TRIGGER IF EXISTS segments_ad")
                conn.execute("DROP TRIGGER IF EXISTS segments_au")
                conn.execute("DROP TABLE IF EXISTS segments_fts")
                conn.execute("DROP TABLE IF EXISTS segments")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS segments (
                        id INTEGER PRIMARY KEY,
                        meeting_id TEXT NOT NULL,
                        stage_id TEXT NOT NULL,
                        alias TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        segments_relpath TEXT NOT NULL,
                        segment_index INTEGER NOT NULL,
                        start_ms INTEGER NOT NULL,
                        end_ms INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(meeting_id, stage_id, alias, kind, segment_index)
                    )
                    """
                )
            expected_seg_cols = [
                "content",
                "meeting_id",
                "stage_id",
                "alias",
                "kind",
                "segment_index",
                "start_ms",
                "segments_relpath",
            ]
            existing_seg_cols = [row[1] for row in conn.execute("PRAGMA table_info(segments_fts)").fetchall()]
            if existing_seg_cols and existing_seg_cols != expected_seg_cols:
                conn.execute("DROP TRIGGER IF EXISTS segments_ai")
                conn.execute("DROP TRIGGER IF EXISTS segments_ad")
                conn.execute("DROP TRIGGER IF EXISTS segments_au")
                conn.execute("DROP TABLE IF EXISTS segments_fts")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts
                USING fts5(content, meeting_id, stage_id, alias, kind, segment_index, start_ms, segments_relpath)
                """
            )
            conn.execute("DROP TRIGGER IF EXISTS segments_ai")
            conn.execute("DROP TRIGGER IF EXISTS segments_ad")
            conn.execute("DROP TRIGGER IF EXISTS segments_au")
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS segments_ai
                AFTER INSERT ON segments BEGIN
                    INSERT INTO segments_fts(
                        rowid, content, meeting_id, stage_id, alias, kind, segment_index, start_ms, segments_relpath
                    )
                    VALUES (
                        new.id, new.content, new.meeting_id, new.stage_id, new.alias, new.kind,
                        new.segment_index, new.start_ms, new.segments_relpath
                    );
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS segments_ad
                AFTER DELETE ON segments BEGIN
                    DELETE FROM segments_fts WHERE rowid = old.id;
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS segments_au
                AFTER UPDATE ON segments BEGIN
                    DELETE FROM segments_fts WHERE rowid = old.id;
                    INSERT INTO segments_fts(
                        rowid, content, meeting_id, stage_id, alias, kind, segment_index, start_ms, segments_relpath
                    )
                    VALUES(
                        new.id, new.content, new.meeting_id, new.stage_id, new.alias, new.kind,
                        new.segment_index, new.start_ms, new.segments_relpath
                    );
                END
                """
            )

    def _read_text(self, relpath: str) -> Optional[str]:
        try:
            path = (self._output_dir / relpath).resolve()
        except Exception:
            return None
        if not str(path).startswith(str(self._output_dir.resolve())):
            return None
        if not path.exists():
            return None
        if path.suffix.lower() not in {".txt", ".md", ".json"}:
            return None
        try:
            if path.stat().st_size > 1_000_000:
                return None
        except Exception:
            return None
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

    def _read_segments_records(self, relpath: str) -> list[dict]:
        raw = self._read_text(relpath)
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            candidate = payload.get("records") or payload.get("segments") or []
            if isinstance(candidate, list):
                return [r for r in candidate if isinstance(r, dict)]
        return []

    def _list_meetings(self) -> list[dict]:
        if not self._output_dir.exists():
            return []
        items: list[dict] = []
        for path in self._output_dir.glob("*__MEETING.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logging.getLogger("aimn.search").warning("meeting_parse_failed path=%s error=%s", path, exc)
                continue
            if isinstance(raw, dict):
                items.append(raw)
        return items


def _meeting_artifacts(meeting_meta: dict) -> Iterable[tuple[str, str, str, str]]:
    # Node artifacts.
    nodes = meeting_meta.get("nodes")
    if isinstance(nodes, dict):
        for alias, node in nodes.items():
            if not isinstance(node, dict):
                continue
            stage_id = str(node.get("stage_id", "") or "").strip() or "meeting"
            artifacts = node.get("artifacts")
            if not isinstance(artifacts, list):
                continue
            for art in artifacts:
                if not isinstance(art, dict):
                    continue
                kind = str(art.get("kind", "")).strip()
                relpath = str(art.get("path", "")).strip()
                user_visible = art.get("user_visible")
                if user_visible is False and kind != KIND_SEGMENTS:
                    continue
                if kind and relpath:
                    yield str(alias or ""), stage_id, kind, relpath

    # Top-level convenience fields (when present).
    top = [
        (KIND_TRANSCRIPT, meeting_meta.get("transcript_relpath")),
        (KIND_AUDIO, meeting_meta.get("audio_relpath")),
    ]
    for kind, relpath in top:
        rel = str(relpath or "").strip()
        if rel and kind != KIND_AUDIO:
            yield "", "meeting", kind, rel


def resolve_app_root() -> Path:
    raw = os.environ.get("AIMN_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return get_app_root()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
