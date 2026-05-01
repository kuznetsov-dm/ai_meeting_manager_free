from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class SuggestionRow:
    suggestion_id: str
    kind: str
    title: str
    description: str
    normalized_key: str
    confidence: float
    reasoning_short: str
    state: str
    source_meeting_id: str
    source_kind: str
    source_alias: str
    evidence_json: str
    approved_entity_type: str
    approved_entity_id: str
    created_at: str
    updated_at: str


class ManagementSuggestionRepository:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        utc_now_iso: Callable[[], str],
        normalize_text: Callable[[str], str],
    ) -> None:
        self._conn = conn
        self._utc_now_iso = utc_now_iso
        self._normalize_text = normalize_text

    def upsert_suggestion(
        self,
        *,
        kind: str,
        title: str,
        source_meeting_id: str,
        source_kind: str,
        source_alias: str,
        normalized_key: str = "",
        description: str = "",
        confidence: float = 0.0,
        reasoning_short: str = "",
        evidence: list[dict] | None = None,
    ) -> str:
        kind_value = str(kind or "").strip().lower()
        title_value = str(title or "").strip()
        meeting_id = str(source_meeting_id or "").strip()
        source_kind_value = str(source_kind or "").strip()
        source_alias_value = str(source_alias or "").strip()
        normalized = self._normalize_text(normalized_key or title_value)
        if kind_value not in {"task", "project", "agenda"}:
            raise ValueError("unsupported_suggestion_kind")
        if not title_value or not meeting_id or not source_kind_value or not normalized:
            raise ValueError("invalid_suggestion")
        now = self._utc_now_iso()
        evidence_json = json.dumps(list(evidence or []), ensure_ascii=True)
        row = self._conn.execute(
            """
            SELECT
                suggestion_id, state, approved_entity_type, approved_entity_id
            FROM management_suggestions
            WHERE kind = ? AND normalized_key = ? AND source_meeting_id = ? AND source_kind = ? AND source_alias = ?
            """,
            (kind_value, normalized, meeting_id, source_kind_value, source_alias_value),
        ).fetchone()
        if row:
            suggestion_id = str(row[0] or "")
            state = str(row[1] or "suggested")
            approved_entity_type = str(row[2] or "")
            approved_entity_id = str(row[3] or "")
            with self._conn:
                self._conn.execute(
                    """
                    UPDATE management_suggestions
                    SET title = ?, description = ?, confidence = ?, reasoning_short = ?, evidence_json = ?,
                        state = ?, approved_entity_type = ?, approved_entity_id = ?, updated_at = ?
                    WHERE suggestion_id = ?
                    """,
                    (
                        title_value,
                        str(description or ""),
                        float(confidence or 0.0),
                        str(reasoning_short or ""),
                        evidence_json,
                        state,
                        approved_entity_type,
                        approved_entity_id,
                        now,
                        suggestion_id,
                    ),
                )
            return suggestion_id

        suggestion_id = f"mgmt-sug-{uuid4()}"
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO management_suggestions(
                    suggestion_id, kind, title, description, normalized_key, confidence, reasoning_short,
                    state, source_meeting_id, source_kind, source_alias, evidence_json,
                    approved_entity_type, approved_entity_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    suggestion_id,
                    kind_value,
                    title_value,
                    str(description or ""),
                    normalized,
                    float(confidence or 0.0),
                    str(reasoning_short or ""),
                    "suggested",
                    meeting_id,
                    source_kind_value,
                    source_alias_value,
                    evidence_json,
                    "",
                    "",
                    now,
                    now,
                ),
            )
        return suggestion_id

    def list_suggestions(
        self,
        *,
        state: str | None = "suggested",
        meeting_id: str = "",
    ) -> list[dict]:
        where: list[str] = []
        params: list[object] = []
        state_value = str(state or "").strip().lower()
        meeting_value = str(meeting_id or "").strip()
        if state_value:
            where.append("state = ?")
            params.append(state_value)
        if meeting_value:
            where.append("source_meeting_id = ?")
            params.append(meeting_value)
        sql = """
            SELECT
                suggestion_id, kind, title, description, normalized_key, confidence, reasoning_short, state,
                source_meeting_id, source_kind, source_alias, evidence_json,
                approved_entity_type, approved_entity_id, created_at, updated_at
            FROM management_suggestions
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, confidence DESC"
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        out: list[dict] = []
        for row in rows:
            evidence_json = str(row[11] or "[]")
            try:
                evidence = json.loads(evidence_json)
            except Exception:
                evidence = []
            out.append(
                {
                    "id": str(row[0] or ""),
                    "kind": str(row[1] or ""),
                    "title": str(row[2] or ""),
                    "description": str(row[3] or ""),
                    "normalized_key": str(row[4] or ""),
                    "confidence": float(row[5] or 0.0),
                    "reasoning_short": str(row[6] or ""),
                    "state": str(row[7] or "suggested"),
                    "source_meeting_id": str(row[8] or ""),
                    "source_kind": str(row[9] or ""),
                    "source_alias": str(row[10] or ""),
                    "evidence": evidence if isinstance(evidence, list) else [],
                    "approved_entity_type": str(row[12] or ""),
                    "approved_entity_id": str(row[13] or ""),
                    "created_at": str(row[14] or ""),
                    "updated_at": str(row[15] or ""),
                }
            )
        return out

    def set_suggestion_state(self, suggestion_id: str, *, state: str) -> bool:
        sid = str(suggestion_id or "").strip()
        state_value = str(state or "").strip().lower()
        if not sid or state_value not in {"suggested", "approved", "rejected", "hidden", "stale"}:
            return False
        with self._conn:
            cur = self._conn.execute(
                "UPDATE management_suggestions SET state = ?, updated_at = ? WHERE suggestion_id = ?",
                (state_value, self._utc_now_iso(), sid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def load_suggestion_row(self, suggestion_id: str) -> SuggestionRow | None:
        sid = str(suggestion_id or "").strip()
        if not sid:
            return None
        row = self._conn.execute(
            """
            SELECT
                suggestion_id, kind, title, description, normalized_key, confidence, reasoning_short, state,
                source_meeting_id, source_kind, source_alias, evidence_json,
                approved_entity_type, approved_entity_id, created_at, updated_at
            FROM management_suggestions
            WHERE suggestion_id = ?
            """,
            (sid,),
        ).fetchone()
        if not row:
            return None
        return SuggestionRow(
            suggestion_id=str(row[0] or ""),
            kind=str(row[1] or ""),
            title=str(row[2] or ""),
            description=str(row[3] or ""),
            normalized_key=str(row[4] or ""),
            confidence=float(row[5] or 0.0),
            reasoning_short=str(row[6] or ""),
            state=str(row[7] or "suggested"),
            source_meeting_id=str(row[8] or ""),
            source_kind=str(row[9] or ""),
            source_alias=str(row[10] or ""),
            evidence_json=str(row[11] or "[]"),
            approved_entity_type=str(row[12] or ""),
            approved_entity_id=str(row[13] or ""),
            created_at=str(row[14] or ""),
            updated_at=str(row[15] or ""),
        )
