from __future__ import annotations

import sqlite3
from collections.abc import Callable
from uuid import uuid4


def canonical_link(
    left_type: str,
    left_id: str,
    right_type: str,
    right_id: str,
) -> tuple[str, str, str, str] | None:
    lt = str(left_type or "").strip().lower()
    li = str(left_id or "").strip()
    rt = str(right_type or "").strip().lower()
    ri = str(right_id or "").strip()
    if not lt or not li or not rt or not ri:
        return None
    if lt == rt and li == ri:
        return None
    pair_left = (lt, li)
    pair_right = (rt, ri)
    if pair_left <= pair_right:
        return lt, li, rt, ri
    return rt, ri, lt, li


class ManagementLinkService:
    def __init__(self, conn: sqlite3.Connection, *, utc_now_iso: Callable[[], str]) -> None:
        self._conn = conn
        self._utc_now_iso = utc_now_iso

    def link_entities(
        self,
        *,
        left_type: str,
        left_id: str,
        right_type: str,
        right_id: str,
        relation: str = "linked",
    ) -> bool:
        canonical = canonical_link(left_type, left_id, right_type, right_id)
        if not canonical:
            return False
        lt, li, rt, ri = canonical
        rel = str(relation or "linked").strip() or "linked"
        now = self._utc_now_iso()
        link_id = f"link-{uuid4()}"
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO entity_links(
                    link_id, left_type, left_id, right_type, right_id, relation, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (link_id, lt, li, rt, ri, rel, now),
            )
        return True

    def unlink_entities(
        self,
        *,
        left_type: str,
        left_id: str,
        right_type: str,
        right_id: str,
        relation: str = "linked",
    ) -> bool:
        canonical = canonical_link(left_type, left_id, right_type, right_id)
        if not canonical:
            return False
        lt, li, rt, ri = canonical
        rel = str(relation or "linked").strip() or "linked"
        with self._conn:
            cur = self._conn.execute(
                """
                DELETE FROM entity_links
                WHERE left_type = ? AND left_id = ? AND right_type = ? AND right_id = ? AND relation = ?
                """,
                (lt, li, rt, ri, rel),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def linked_entity_ids(self, entity_type: str, entity_id: str, *, related_type: str) -> set[str]:
        etype = str(entity_type or "").strip().lower()
        eid = str(entity_id or "").strip()
        rtype = str(related_type or "").strip().lower()
        if not etype or not eid or not rtype:
            return set()

        rows = self._conn.execute(
            """
            SELECT left_type, left_id, right_type, right_id
            FROM entity_links
            WHERE (left_type = ? AND left_id = ? AND right_type = ?)
               OR (right_type = ? AND right_id = ? AND left_type = ?)
            """,
            (etype, eid, rtype, etype, eid, rtype),
        ).fetchall()
        out: set[str] = set()
        for left_type, left_id, right_type, right_id in rows:
            if str(left_type) == etype and str(left_id) == eid and str(right_type) == rtype:
                out.add(str(right_id))
                continue
            if str(right_type) == etype and str(right_id) == eid and str(left_type) == rtype:
                out.add(str(left_id))
        return out

    def list_links_for(self, *, entity_type: str, entity_id: str) -> list[dict]:
        etype = str(entity_type or "").strip().lower()
        eid = str(entity_id or "").strip()
        if not etype or not eid:
            return []
        rows = self._conn.execute(
            """
            SELECT link_id, left_type, left_id, right_type, right_id, relation, created_at
            FROM entity_links
            WHERE (left_type = ? AND left_id = ?) OR (right_type = ? AND right_id = ?)
            ORDER BY created_at DESC
            """,
            (etype, eid, etype, eid),
        ).fetchall()
        out: list[dict] = []
        for link_id, left_type, left_id, right_type, right_id, relation, created_at in rows:
            if str(left_type) == etype and str(left_id) == eid:
                related_type = str(right_type)
                related_id = str(right_id)
            else:
                related_type = str(left_type)
                related_id = str(left_id)
            out.append(
                {
                    "link_id": str(link_id),
                    "entity_type": etype,
                    "entity_id": eid,
                    "related_type": related_type,
                    "related_id": related_id,
                    "relation": str(relation or "linked"),
                    "created_at": str(created_at or ""),
                }
            )
        return out

    def delete_links_for_entity(self, entity_type: str, entity_id: str) -> None:
        etype = str(entity_type or "").strip().lower()
        eid = str(entity_id or "").strip()
        if not etype or not eid:
            return
        self._conn.execute(
            "DELETE FROM entity_links WHERE (left_type = ? AND left_id = ?) OR (right_type = ? AND right_id = ?)",
            (etype, eid, etype, eid),
        )
