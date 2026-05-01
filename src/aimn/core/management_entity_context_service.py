from __future__ import annotations

import sqlite3
from collections.abc import Callable


class ManagementEntityContextService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        linked_entity_ids: Callable[[str, str], set[str]] | Callable[..., set[str]],
        list_links_for: Callable[..., list[dict]],
    ) -> None:
        self._conn = conn
        self._linked_entity_ids = linked_entity_ids
        self._list_links_for = list_links_for

    def project_exists(self, project_id: str) -> bool:
        pid = str(project_id or "").strip()
        if not pid:
            return False
        row = self._conn.execute("SELECT 1 FROM projects WHERE project_id = ?", (pid,)).fetchone()
        return bool(row)

    def meeting_ids_for(self, entity_type: str, entity_id: str) -> list[str]:
        etype = str(entity_type or "").strip().lower()
        eid = str(entity_id or "").strip()
        if not etype or not eid:
            return []

        rows = []
        if etype == "task":
            rows = self._conn.execute(
                "SELECT DISTINCT meeting_id FROM task_mentions WHERE task_id = ?",
                (eid,),
            ).fetchall()
        elif etype == "project":
            rows = self._conn.execute(
                "SELECT DISTINCT meeting_id FROM project_mentions WHERE project_id = ?",
                (eid,),
            ).fetchall()
        elif etype == "agenda":
            rows = self._conn.execute(
                "SELECT DISTINCT meeting_id FROM agenda_mentions WHERE agenda_id = ?",
                (eid,),
            ).fetchall()
        meeting_ids = {str(row[0]) for row in rows if row and str(row[0] or "").strip()}

        linked = self._linked_entity_ids(etype, eid, related_type="meeting")
        for mid in linked:
            if str(mid or "").strip():
                meeting_ids.add(str(mid).strip())
        return sorted(meeting_ids)

    def mention_provenance_for(self, entity_type: str, entity_id: str) -> dict[str, object]:
        etype = str(entity_type or "").strip().lower()
        eid = str(entity_id or "").strip()
        table_map = {
            "task": ("task_mentions", "task_id"),
            "project": ("project_mentions", "project_id"),
            "agenda": ("agenda_mentions", "agenda_id"),
        }
        table_info = table_map.get(etype)
        if not table_info or not eid:
            return {
                "mention_count": 0,
                "manual_mentions": 0,
                "ai_mentions": 0,
                "source_kinds": [],
            }
        table, id_column = table_info
        rows = self._conn.execute(
            f"SELECT source_kind FROM {table} WHERE {id_column} = ?",
            (eid,),
        ).fetchall()
        source_kinds: list[str] = []
        manual_mentions = 0
        ai_mentions = 0
        manual_like = {"manual", "transcript_selection"}
        for row in rows:
            kind = str(row[0] or "").strip()
            if not kind:
                continue
            source_kinds.append(kind)
            if kind in manual_like:
                manual_mentions += 1
            else:
                ai_mentions += 1
        return {
            "mention_count": len(source_kinds),
            "manual_mentions": manual_mentions,
            "ai_mentions": ai_mentions,
            "source_kinds": sorted(set(source_kinds)),
        }

    def orphan_entity_ids(self, entity_type: str, *, removing_meeting_id: str = "") -> list[str]:
        etype = str(entity_type or "").strip().lower()
        removing_mid = str(removing_meeting_id or "").strip()
        configs = {
            "task": ("tasks", "task_id"),
            "project": ("projects", "project_id"),
            "agenda": ("agendas", "agenda_id"),
        }
        table_info = configs.get(etype)
        if not table_info:
            return []
        table, id_column = table_info
        rows = self._conn.execute(f"SELECT {id_column} FROM {table}").fetchall()
        out: list[str] = []
        for row in rows:
            entity_id = str(row[0] or "").strip()
            if not entity_id:
                continue
            meetings = [mid for mid in self.meeting_ids_for(etype, entity_id) if mid and mid != removing_mid]
            if meetings:
                continue
            if self._list_links_for(entity_type=etype, entity_id=entity_id):
                continue
            if self._is_pinned(table, id_column, entity_id):
                continue
            out.append(entity_id)
        return out

    def orphan_entity_ids_for_artifact_cleanup(
        self,
        entity_type: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
    ) -> list[str]:
        etype = str(entity_type or "").strip().lower()
        meeting = str(meeting_id or "").strip()
        kind = str(source_kind or "").strip()
        alias = str(source_alias or "").strip()
        mention_info = {
            "task": ("task_mentions", "task_id", "tasks", "task_id"),
            "project": ("project_mentions", "project_id", "projects", "project_id"),
            "agenda": ("agenda_mentions", "agenda_id", "agendas", "agenda_id"),
        }.get(etype)
        if not mention_info or not meeting or not kind:
            return []
        mention_table, mention_entity_id, entity_table, entity_id_column = mention_info
        rows = self._conn.execute(
            f"""
            SELECT DISTINCT {mention_entity_id}
            FROM {mention_table}
            WHERE meeting_id = ? AND source_kind = ? AND source_alias = ?
            """,
            (meeting, kind, alias),
        ).fetchall()
        out: list[str] = []
        for row in rows:
            entity_id = str(row[0] or "").strip()
            if not entity_id:
                continue
            remaining = self._conn.execute(
                f"""
                SELECT 1
                FROM {mention_table}
                WHERE {mention_entity_id} = ?
                  AND NOT (meeting_id = ? AND source_kind = ? AND source_alias = ?)
                LIMIT 1
                """,
                (entity_id, meeting, kind, alias),
            ).fetchone()
            if remaining:
                continue
            if self._list_links_for(entity_type=etype, entity_id=entity_id):
                continue
            if self._is_pinned(entity_table, entity_id_column, entity_id):
                continue
            out.append(entity_id)
        return out

    def _is_pinned(self, table: str, id_column: str, entity_id: str) -> bool:
        row = self._conn.execute(f"SELECT pinned FROM {table} WHERE {id_column} = ?", (entity_id,)).fetchone()
        return bool(row and int(row[0] or 0) != 0)
