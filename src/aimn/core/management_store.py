
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from aimn.core.app_paths import get_config_dir
from aimn.core.management_cleanup_policy_service import ManagementCleanupPolicyService
from aimn.core.management_cleanup_service import ManagementCleanupService
from aimn.core.management_entity_context_service import ManagementEntityContextService
from aimn.core.management_link_service import ManagementLinkService
from aimn.core.management_suggestion_repository import ManagementSuggestionRepository, SuggestionRow


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _coerce_similarity(value: float, *, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(0.0, min(parsed, 1.0))


@dataclass(frozen=True)
class TaskRow:
    task_id: str
    title: str
    normalized: str
    status: str
    project_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProjectRow:
    project_id: str
    name: str
    normalized: str
    description: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AgendaRow:
    agenda_id: str
    title: str
    text: str
    normalized: str
    status: str
    created_at: str
    updated_at: str


class ManagementStore:
    """
    Local management store (SQLite) for Tasks / Projects / Agendas and links.

    Stored under config/ (gitignored) so it persists across runs but is not committed.
    """

    def __init__(self, app_root: Path) -> None:
        self._app_root = Path(app_root)
        base = get_config_dir(self._app_root) / "management"
        base.mkdir(parents=True, exist_ok=True)
        self._db_path = base / "management.sqlite"
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._link_service = ManagementLinkService(self._conn, utc_now_iso=_utc_now_iso)
        self._entity_context_service = ManagementEntityContextService(
            self._conn,
            linked_entity_ids=self._link_service.linked_entity_ids,
            list_links_for=self._link_service.list_links_for,
        )
        self._suggestion_repository = ManagementSuggestionRepository(
            self._conn,
            utc_now_iso=_utc_now_iso,
            normalize_text=_normalize_text,
        )
        self._cleanup_service = ManagementCleanupService(
            self._conn,
            count_rows=self._count_rows,
            orphan_entity_ids=self._entity_context_service.orphan_entity_ids,
            orphan_entity_ids_for_artifact_cleanup=(
                self._entity_context_service.orphan_entity_ids_for_artifact_cleanup
            ),
            delete_task=self.delete_task,
            delete_project=self.delete_project,
            delete_agenda=self.delete_agenda,
        )
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            return

    # ---- Tasks ----

    def create_task(
        self,
        *,
        title: str,
        project_id: str | None = None,
        meeting_id: str = "",
        source_kind: str = "manual",
        source_alias: str = "",
        original_text: str = "",
    ) -> str:
        title_text = str(title or "").strip()
        if not title_text:
            raise ValueError("empty_task_title")
        now = _utc_now_iso()
        task_id = f"task-{uuid4()}"
        normalized = _normalize_text(title_text)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO tasks(task_id, title, normalized, status, project_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, title_text, normalized, "open", None, now, now),
            )
        pid = str(project_id or "").strip()
        if pid:
            self.link_entities(left_type="task", left_id=task_id, right_type="project", right_id=pid)
        meeting = str(meeting_id or "").strip()
        if meeting:
            self._ensure_task_mention(
                task_id=task_id,
                meeting_id=meeting,
                source_kind=str(source_kind or "manual"),
                source_alias=str(source_alias or ""),
                original_text=str(original_text or "").strip() or title_text,
            )
        return task_id

    def rename_task(self, task_id: str, *, title: str) -> bool:
        tid = str(task_id or "").strip()
        title_text = str(title or "").strip()
        if not tid or not title_text:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE tasks SET title = ?, normalized = ?, updated_at = ? WHERE task_id = ?",
                (title_text, _normalize_text(title_text), now, tid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def set_task_status(self, task_id: str, *, status: str) -> bool:
        tid = str(task_id or "").strip()
        status_norm = "done" if str(status or "").strip().lower() == "done" else "open"
        if not tid:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status_norm, now, tid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def assign_task_project(self, task_id: str, *, project_id: str | None) -> bool:
        # Backward-compatible API:
        # - project_id=<id> links task<->project (many-to-many)
        # - project_id=None removes all project links for the task
        tid = str(task_id or "").strip()
        pid = str(project_id or "").strip() or None
        if not tid:
            return False
        task_exists = bool(self._conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (tid,)).fetchone())
        if not task_exists:
            return False
        if pid:
            if not self._project_exists(pid):
                return False
            self.link_entities(left_type="task", left_id=tid, right_type="project", right_id=pid)
            now = _utc_now_iso()
            with self._conn:
                self._conn.execute("UPDATE tasks SET project_id = ?, updated_at = ? WHERE task_id = ?", (pid, now, tid))
            return True

        current = self.linked_entity_ids("task", tid, related_type="project")
        for project_id_item in current:
            self.unlink_entities(left_type="task", left_id=tid, right_type="project", right_id=project_id_item)
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute("UPDATE tasks SET project_id = ?, updated_at = ? WHERE task_id = ?", (None, now, tid))
        return True

    def delete_task(self, task_id: str) -> bool:
        tid = str(task_id or "").strip()
        if not tid:
            return False
        with self._conn:
            self._conn.execute("DELETE FROM task_mentions WHERE task_id = ?", (tid,))
            self._delete_links_for_entity("task", tid)
            cur = self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (tid,))
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def upsert_task_with_mention(
        self,
        *,
        title: str,
        normalized: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        dedupe_similarity: float = 0.85,
        project_id: str | None = None,
    ) -> str:
        title_text = str(title or "").strip()
        norm = _normalize_text(normalized or title_text)
        if not title_text or not norm:
            raise ValueError("empty_task_title")

        threshold = _coerce_similarity(dedupe_similarity, default=0.85)
        existing = self._match_task(norm, threshold)
        now = _utc_now_iso()

        if existing:
            task_id = existing.task_id
            with self._conn:
                self._conn.execute(
                    "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                    (now, task_id),
                )
        else:
            task_id = f"task-{uuid4()}"
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO tasks(task_id, title, normalized, status, project_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, title_text, norm, "open", None, now, now),
                )
        pid = str(project_id or "").strip()
        if pid:
            self.link_entities(left_type="task", left_id=task_id, right_type="project", right_id=pid)

        self._ensure_task_mention(
            task_id=task_id,
            meeting_id=meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            original_text=title_text,
        )
        return task_id

    def list_tasks(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
                task_id,
                title,
                normalized,
                status,
                project_id,
                created_at,
                updated_at
            FROM tasks
            ORDER BY updated_at DESC
            """
        ).fetchall()
        out: list[dict] = []
        for task_id, title, normalized, status, _legacy_project_id, created_at, updated_at in rows:
            tid = str(task_id or "")
            meetings_list = self._meeting_ids_for("task", tid)
            project_ids = sorted(self.linked_entity_ids("task", tid, related_type="project"))
            project_id = project_ids[0] if project_ids else None
            provenance = self._mention_provenance_for("task", tid)
            out.append(
                {
                    "id": tid,
                    "title": str(title or ""),
                    "original_text": str(title or "") or None,
                    "normalized_text": str(normalized or "") or None,
                    "status": str(status or "open"),
                    "project_id": project_id,
                    "project_ids": project_ids,
                    "meetings": meetings_list,
                    **provenance,
                    "created_at": str(created_at or ""),
                    "updated_at": str(updated_at or ""),
                }
            )
        return out

    def list_tasks_for_meeting(self, meeting_id: str) -> list[dict]:
        mid = str(meeting_id or "").strip()
        if not mid:
            return []
        all_items = self.list_tasks()
        return [item for item in all_items if mid in set(item.get("meetings", []))]

    def _match_task(self, normalized: str, threshold: float) -> TaskRow | None:
        best: TaskRow | None = None
        best_score = 0.0
        rows = self._conn.execute(
            "SELECT task_id, title, normalized, status, project_id, created_at, updated_at FROM tasks WHERE status = ?",
            ("open",),
        ).fetchall()
        for row in rows:
            candidate = TaskRow(
                task_id=str(row[0]),
                title=str(row[1] or ""),
                normalized=str(row[2] or ""),
                status=str(row[3] or "open"),
                project_id=str(row[4]) if row[4] else None,
                created_at=str(row[5] or ""),
                updated_at=str(row[6] or ""),
            )
            score = SequenceMatcher(None, normalized, candidate.normalized).ratio()
            if score >= threshold and score > best_score:
                best = candidate
                best_score = score
        return best

    def _ensure_task_mention(
        self,
        *,
        task_id: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        original_text: str,
    ) -> None:
        mid = str(meeting_id or "").strip()
        sk = str(source_kind or "").strip()
        sa = str(source_alias or "").strip()
        txt = str(original_text or "").strip()
        if not mid or not sk:
            return
        now = _utc_now_iso()
        mention_id = f"mention-{uuid4()}"
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO task_mentions(
                    mention_id, task_id, meeting_id, source_kind, source_alias, original_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mention_id, str(task_id), mid, sk, sa, txt, now),
            )

    # ---- Projects ----

    def create_project(
        self,
        *,
        name: str,
        description: str = "",
        meeting_id: str = "",
        source_kind: str = "manual",
        source_alias: str = "",
        original_text: str = "",
    ) -> str:
        name_text = str(name or "").strip()
        if not name_text:
            raise ValueError("empty_project_name")
        now = _utc_now_iso()
        project_id = f"project-{uuid4()}"
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO projects(project_id, name, normalized, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, name_text, _normalize_text(name_text), str(description or ""), "active", now, now),
            )
        meeting = str(meeting_id or "").strip()
        if meeting:
            self._ensure_project_mention(
                project_id=project_id,
                meeting_id=meeting,
                source_kind=str(source_kind or "manual"),
                source_alias=str(source_alias or ""),
                original_text=str(original_text or "").strip() or name_text,
            )
        return project_id

    def rename_project(self, project_id: str, *, name: str) -> bool:
        pid = str(project_id or "").strip()
        name_text = str(name or "").strip()
        if not pid or not name_text:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET name = ?, normalized = ?, updated_at = ? WHERE project_id = ?",
                (name_text, _normalize_text(name_text), now, pid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def update_project_description(self, project_id: str, *, description: str) -> bool:
        pid = str(project_id or "").strip()
        if not pid:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET description = ?, updated_at = ? WHERE project_id = ?",
                (str(description or ""), now, pid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def set_project_status(self, project_id: str, *, status: str) -> bool:
        pid = str(project_id or "").strip()
        status_norm = "archived" if str(status or "").strip().lower() == "archived" else "active"
        if not pid:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE project_id = ?",
                (status_norm, now, pid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def delete_project(self, project_id: str) -> bool:
        pid = str(project_id or "").strip()
        if not pid:
            return False
        with self._conn:
            self._conn.execute("UPDATE tasks SET project_id = NULL WHERE project_id = ?", (pid,))
            self._conn.execute("DELETE FROM project_mentions WHERE project_id = ?", (pid,))
            self._delete_links_for_entity("project", pid)
            cur = self._conn.execute("DELETE FROM projects WHERE project_id = ?", (pid,))
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def upsert_project_with_mention(
        self,
        *,
        name: str,
        normalized: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        dedupe_similarity: float = 0.88,
        description: str = "",
    ) -> str:
        name_text = str(name or "").strip()
        norm = _normalize_text(normalized or name_text)
        if not name_text or not norm:
            raise ValueError("empty_project_name")

        threshold = _coerce_similarity(dedupe_similarity, default=0.88)
        existing = self._match_project(norm, threshold)
        now = _utc_now_iso()

        if existing:
            project_id = existing.project_id
            with self._conn:
                self._conn.execute(
                    "UPDATE projects SET updated_at = ? WHERE project_id = ?",
                    (now, project_id),
                )
        else:
            project_id = f"project-{uuid4()}"
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO projects(project_id, name, normalized, description, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, name_text, norm, str(description or ""), "active", now, now),
                )

        self._ensure_project_mention(
            project_id=project_id,
            meeting_id=meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            original_text=name_text,
        )
        return project_id

    def list_projects(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
                project_id,
                name,
                description,
                status,
                created_at,
                updated_at
            FROM projects
            ORDER BY updated_at DESC
            """
        ).fetchall()
        out: list[dict] = []
        for project_id, name, description, status, created_at, updated_at in rows:
            pid = str(project_id or "")
            meetings_list = self._meeting_ids_for("project", pid)
            task_ids = sorted(self.linked_entity_ids("project", pid, related_type="task"))
            tasks_count = len(task_ids)
            provenance = self._mention_provenance_for("project", pid)
            out.append(
                {
                    "id": pid,
                    "name": str(name or ""),
                    "description": str(description or ""),
                    "status": str(status or "active"),
                    "meetings": meetings_list,
                    "tasks": task_ids,
                    "agendas": sorted(self.linked_entity_ids("project", pid, related_type="agenda")),
                    "tasks_count": tasks_count,
                    **provenance,
                    "created_at": str(created_at or ""),
                    "updated_at": str(updated_at or ""),
                }
            )
        return out

    def list_projects_for_meeting(self, meeting_id: str) -> list[dict]:
        mid = str(meeting_id or "").strip()
        if not mid:
            return []
        all_items = self.list_projects()
        return [item for item in all_items if mid in set(item.get("meetings", []))]

    def _match_project(self, normalized: str, threshold: float) -> ProjectRow | None:
        best: ProjectRow | None = None
        best_score = 0.0
        rows = self._conn.execute(
            "SELECT project_id, name, normalized, description, status, created_at, updated_at FROM projects"
        ).fetchall()
        for row in rows:
            candidate = ProjectRow(
                project_id=str(row[0]),
                name=str(row[1] or ""),
                normalized=str(row[2] or ""),
                description=str(row[3] or ""),
                status=str(row[4] or "active"),
                created_at=str(row[5] or ""),
                updated_at=str(row[6] or ""),
            )
            score = SequenceMatcher(None, normalized, candidate.normalized).ratio()
            if score >= threshold and score > best_score:
                best = candidate
                best_score = score
        return best

    def _ensure_project_mention(
        self,
        *,
        project_id: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        original_text: str,
    ) -> None:
        mid = str(meeting_id or "").strip()
        sk = str(source_kind or "").strip()
        sa = str(source_alias or "").strip()
        txt = str(original_text or "").strip()
        if not mid or not sk:
            return
        now = _utc_now_iso()
        mention_id = f"mention-{uuid4()}"
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO project_mentions(
                    mention_id, project_id, meeting_id, source_kind, source_alias, original_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mention_id, str(project_id), mid, sk, sa, txt, now),
            )

    # ---- Agendas ----

    def create_agenda(
        self,
        *,
        title: str,
        text: str = "",
        meeting_id: str = "",
        source_kind: str = "manual",
        source_alias: str = "",
        original_text: str = "",
    ) -> str:
        title_text = str(title or "").strip()
        if not title_text:
            raise ValueError("empty_agenda_title")
        now = _utc_now_iso()
        agenda_id = f"agenda-{uuid4()}"
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO agendas(agenda_id, title, text, normalized, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (agenda_id, title_text, str(text or "").strip(), _normalize_text(title_text), "active", now, now),
            )
        meeting = str(meeting_id or "").strip()
        if meeting:
            self._ensure_agenda_mention(
                agenda_id=agenda_id,
                meeting_id=meeting,
                source_kind=str(source_kind or "manual"),
                source_alias=str(source_alias or ""),
                original_text=str(original_text or "").strip() or title_text,
            )
        return agenda_id

    def rename_agenda(self, agenda_id: str, *, title: str) -> bool:
        aid = str(agenda_id or "").strip()
        title_text = str(title or "").strip()
        if not aid or not title_text:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE agendas SET title = ?, normalized = ?, updated_at = ? WHERE agenda_id = ?",
                (title_text, _normalize_text(title_text), now, aid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def update_agenda_text(self, agenda_id: str, *, text: str) -> bool:
        aid = str(agenda_id or "").strip()
        if not aid:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE agendas SET text = ?, updated_at = ? WHERE agenda_id = ?",
                (str(text or ""), now, aid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def set_agenda_status(self, agenda_id: str, *, status: str) -> bool:
        aid = str(agenda_id or "").strip()
        status_norm = "archived" if str(status or "").strip().lower() == "archived" else "active"
        if not aid:
            return False
        now = _utc_now_iso()
        with self._conn:
            cur = self._conn.execute(
                "UPDATE agendas SET status = ?, updated_at = ? WHERE agenda_id = ?",
                (status_norm, now, aid),
            )
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def delete_agenda(self, agenda_id: str) -> bool:
        aid = str(agenda_id or "").strip()
        if not aid:
            return False
        with self._conn:
            self._conn.execute("DELETE FROM agenda_mentions WHERE agenda_id = ?", (aid,))
            self._delete_links_for_entity("agenda", aid)
            cur = self._conn.execute("DELETE FROM agendas WHERE agenda_id = ?", (aid,))
        return int(getattr(cur, "rowcount", 0) or 0) > 0

    def upsert_agenda_with_mention(
        self,
        *,
        title: str,
        text: str,
        normalized: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        dedupe_similarity: float = 0.88,
    ) -> str:
        title_text = str(title or "").strip() or "Agenda"
        text_value = str(text or "").strip()
        norm = _normalize_text(normalized or title_text)
        threshold = _coerce_similarity(dedupe_similarity, default=0.88)
        existing = self._match_agenda(norm, text_value, threshold)
        now = _utc_now_iso()

        if existing:
            agenda_id = existing.agenda_id
            with self._conn:
                self._conn.execute(
                    "UPDATE agendas SET title = ?, text = ?, normalized = ?, updated_at = ? WHERE agenda_id = ?",
                    (title_text, text_value, norm, now, agenda_id),
                )
        else:
            agenda_id = f"agenda-{uuid4()}"
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO agendas(agenda_id, title, text, normalized, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (agenda_id, title_text, text_value, norm, "active", now, now),
                )

        self._ensure_agenda_mention(
            agenda_id=agenda_id,
            meeting_id=meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            original_text=title_text,
        )
        return agenda_id

    def list_agendas(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT
                agenda_id,
                title,
                text,
                status,
                created_at,
                updated_at
            FROM agendas
            ORDER BY updated_at DESC
            """
        ).fetchall()
        out: list[dict] = []
        for agenda_id, title, text, status, created_at, updated_at in rows:
            aid = str(agenda_id or "")
            meetings_list = self._meeting_ids_for("agenda", aid)
            provenance = self._mention_provenance_for("agenda", aid)
            out.append(
                {
                    "id": aid,
                    "title": str(title or ""),
                    "text": str(text or ""),
                    "status": str(status or "active"),
                    "meetings": meetings_list,
                    "tasks": sorted(self.linked_entity_ids("agenda", aid, related_type="task")),
                    "projects": sorted(self.linked_entity_ids("agenda", aid, related_type="project")),
                    **provenance,
                    "created_at": str(created_at or ""),
                    "updated_at": str(updated_at or ""),
                }
            )
        return out

    def list_agendas_for_meeting(self, meeting_id: str) -> list[dict]:
        mid = str(meeting_id or "").strip()
        if not mid:
            return []
        all_items = self.list_agendas()
        return [item for item in all_items if mid in set(item.get("meetings", []))]

    def _match_agenda(self, normalized: str, text: str, threshold: float) -> AgendaRow | None:
        best: AgendaRow | None = None
        best_score = 0.0
        rows = self._conn.execute(
            "SELECT agenda_id, title, text, normalized, status, created_at, updated_at FROM agendas"
        ).fetchall()
        for row in rows:
            candidate = AgendaRow(
                agenda_id=str(row[0]),
                title=str(row[1] or ""),
                text=str(row[2] or ""),
                normalized=str(row[3] or ""),
                status=str(row[4] or "active"),
                created_at=str(row[5] or ""),
                updated_at=str(row[6] or ""),
            )
            title_score = SequenceMatcher(None, normalized, candidate.normalized).ratio()
            text_score = 0.0
            if text and candidate.text:
                text_score = SequenceMatcher(None, _normalize_text(text), _normalize_text(candidate.text)).ratio()
            score = max(title_score, text_score)
            if score >= threshold and score > best_score:
                best = candidate
                best_score = score
        return best

    def _ensure_agenda_mention(
        self,
        *,
        agenda_id: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        original_text: str,
    ) -> None:
        mid = str(meeting_id or "").strip()
        sk = str(source_kind or "").strip()
        sa = str(source_alias or "").strip()
        txt = str(original_text or "").strip()
        if not mid or not sk:
            return
        now = _utc_now_iso()
        mention_id = f"mention-{uuid4()}"
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO agenda_mentions(
                    mention_id, agenda_id, meeting_id, source_kind, source_alias, original_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mention_id, str(agenda_id), mid, sk, sa, txt, now),
            )

    # ---- Suggestions ----

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
        return self._suggestion_repository.upsert_suggestion(
            kind=kind,
            title=title,
            source_meeting_id=source_meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            normalized_key=normalized_key,
            description=description,
            confidence=confidence,
            reasoning_short=reasoning_short,
            evidence=evidence,
        )

    def list_suggestions(
        self,
        *,
        state: str | None = "suggested",
        meeting_id: str = "",
    ) -> list[dict]:
        return self._suggestion_repository.list_suggestions(state=state, meeting_id=meeting_id)

    def set_suggestion_state(self, suggestion_id: str, *, state: str) -> bool:
        return self._suggestion_repository.set_suggestion_state(suggestion_id, state=state)

    def approve_suggestion_into_existing(self, suggestion_id: str, *, entity_id: str) -> dict | None:
        suggestion = self._load_suggestion_row(suggestion_id)
        target_id = str(entity_id or "").strip()
        if suggestion is None or not target_id:
            return None
        if suggestion.kind == "task":
            exists = bool(self._conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (target_id,)).fetchone())
            if not exists:
                return None
            self._ensure_task_mention(
                task_id=target_id,
                meeting_id=suggestion.source_meeting_id,
                source_kind=suggestion.source_kind,
                source_alias=suggestion.source_alias,
                original_text=suggestion.title,
            )
        elif suggestion.kind == "project":
            exists = bool(self._conn.execute("SELECT 1 FROM projects WHERE project_id = ?", (target_id,)).fetchone())
            if not exists:
                return None
            self._ensure_project_mention(
                project_id=target_id,
                meeting_id=suggestion.source_meeting_id,
                source_kind=suggestion.source_kind,
                source_alias=suggestion.source_alias,
                original_text=suggestion.title,
            )
        elif suggestion.kind == "agenda":
            exists = bool(self._conn.execute("SELECT 1 FROM agendas WHERE agenda_id = ?", (target_id,)).fetchone())
            if not exists:
                return None
            self._ensure_agenda_mention(
                agenda_id=target_id,
                meeting_id=suggestion.source_meeting_id,
                source_kind=suggestion.source_kind,
                source_alias=suggestion.source_alias,
                original_text=suggestion.title,
            )
        else:
            return None
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                UPDATE management_suggestions
                SET state = ?, approved_entity_type = ?, approved_entity_id = ?, updated_at = ?
                WHERE suggestion_id = ?
                """,
                ("approved", suggestion.kind, target_id, now, suggestion.suggestion_id),
            )
        return {"entity_type": suggestion.kind, "entity_id": target_id, "suggestion_id": suggestion.suggestion_id}

    def approve_suggestion(self, suggestion_id: str) -> dict | None:
        suggestion = self._load_suggestion_row(suggestion_id)
        if suggestion is None:
            return None
        entity_id = ""
        if suggestion.kind == "task":
            entity_id = self.upsert_task_with_mention(
                title=suggestion.title,
                normalized=suggestion.normalized_key,
                meeting_id=suggestion.source_meeting_id,
                source_kind=suggestion.source_kind,
                source_alias=suggestion.source_alias,
                dedupe_similarity=0.9,
            )
        elif suggestion.kind == "project":
            entity_id = self.upsert_project_with_mention(
                name=suggestion.title,
                normalized=suggestion.normalized_key,
                meeting_id=suggestion.source_meeting_id,
                source_kind=suggestion.source_kind,
                source_alias=suggestion.source_alias,
                dedupe_similarity=0.9,
                description=suggestion.description,
            )
        elif suggestion.kind == "agenda":
            entity_id = self.upsert_agenda_with_mention(
                title=suggestion.title,
                text=suggestion.description,
                normalized=suggestion.normalized_key,
                meeting_id=suggestion.source_meeting_id,
                source_kind=suggestion.source_kind,
                source_alias=suggestion.source_alias,
                dedupe_similarity=0.9,
            )
        if not entity_id:
            return None
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                UPDATE management_suggestions
                SET state = ?, approved_entity_type = ?, approved_entity_id = ?, updated_at = ?
                WHERE suggestion_id = ?
                """,
                ("approved", suggestion.kind, entity_id, now, suggestion.suggestion_id),
            )
        return {"entity_type": suggestion.kind, "entity_id": entity_id, "suggestion_id": suggestion.suggestion_id}

    def prepare_meeting_cleanup(self, meeting_id: str) -> dict[str, object]:
        return ManagementCleanupPolicyService.build_cleanup_policy(
            self.preview_meeting_cleanup(meeting_id),
            touched_keys=("suggestions", "task_mentions", "project_mentions", "agenda_mentions", "meeting_links"),
        )

    def prepare_artifact_source_cleanup(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
    ) -> dict[str, object]:
        return ManagementCleanupPolicyService.build_cleanup_policy(
            self.preview_artifact_source_cleanup(
                meeting_id=meeting_id,
                source_kind=source_kind,
                source_alias=source_alias,
            ),
            touched_keys=("suggestions", "task_mentions", "project_mentions", "agenda_mentions"),
        )

    def prepare_artifact_alias_cleanup(
        self,
        *,
        meeting_id: str,
        artifact_kind: str,
        source_alias: str,
    ) -> dict[str, object]:
        return ManagementCleanupPolicyService.build_cleanup_policy(
            self.preview_artifact_alias_cleanup(
                meeting_id=meeting_id,
                artifact_kind=artifact_kind,
                source_alias=source_alias,
            ),
            touched_keys=("suggestions", "task_mentions", "project_mentions", "agenda_mentions"),
        )

    def preview_meeting_cleanup(self, meeting_id: str) -> dict[str, int]:
        return self._cleanup_service.preview_meeting_cleanup(meeting_id)

    def preview_artifact_alias_cleanup(
        self,
        *,
        meeting_id: str,
        artifact_kind: str,
        source_alias: str,
    ) -> dict[str, int]:
        return self._cleanup_service.preview_artifact_alias_cleanup(
            meeting_id=meeting_id,
            artifact_kind=artifact_kind,
            source_alias=source_alias,
        )

    def preview_artifact_source_cleanup(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
    ) -> dict[str, int]:
        return self._cleanup_service.preview_artifact_source_cleanup(
            meeting_id=meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
        )

    def cleanup_meeting(self, meeting_id: str, *, delete_orphan_entities: bool = False) -> dict[str, int]:
        return self._cleanup_service.cleanup_meeting(
            meeting_id,
            delete_orphan_entities=delete_orphan_entities,
        )

    def cleanup_artifact_source(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        delete_orphan_entities: bool = False,
    ) -> dict[str, int]:
        return self._cleanup_service.cleanup_artifact_source(
            meeting_id=meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            delete_orphan_entities=delete_orphan_entities,
        )

    def cleanup_artifact_alias(
        self,
        *,
        meeting_id: str,
        artifact_kind: str,
        source_alias: str,
        delete_orphan_entities: bool = False,
    ) -> dict[str, int]:
        return self._cleanup_service.cleanup_artifact_alias(
            meeting_id=meeting_id,
            artifact_kind=artifact_kind,
            source_alias=source_alias,
            delete_orphan_entities=delete_orphan_entities,
        )

    # ---- Links ----

    def link_entities(
        self,
        *,
        left_type: str,
        left_id: str,
        right_type: str,
        right_id: str,
        relation: str = "linked",
    ) -> bool:
        return self._link_service.link_entities(
            left_type=left_type,
            left_id=left_id,
            right_type=right_type,
            right_id=right_id,
            relation=relation,
        )

    def unlink_entities(
        self,
        *,
        left_type: str,
        left_id: str,
        right_type: str,
        right_id: str,
        relation: str = "linked",
    ) -> bool:
        return self._link_service.unlink_entities(
            left_type=left_type,
            left_id=left_id,
            right_type=right_type,
            right_id=right_id,
            relation=relation,
        )

    def linked_entity_ids(self, entity_type: str, entity_id: str, *, related_type: str) -> set[str]:
        return self._link_service.linked_entity_ids(
            entity_type,
            entity_id,
            related_type=related_type,
        )

    def list_links_for(self, *, entity_type: str, entity_id: str) -> list[dict]:
        return self._link_service.list_links_for(entity_type=entity_type, entity_id=entity_id)

    def _delete_links_for_entity(self, entity_type: str, entity_id: str) -> None:
        self._link_service.delete_links_for_entity(entity_type, entity_id)

    # ---- Helpers ----

    def _project_exists(self, project_id: str) -> bool:
        return self._entity_context_service.project_exists(project_id)

    def _meeting_ids_for(self, entity_type: str, entity_id: str) -> list[str]:
        return self._entity_context_service.meeting_ids_for(entity_type, entity_id)

    def _mention_provenance_for(self, entity_type: str, entity_id: str) -> dict[str, object]:
        return self._entity_context_service.mention_provenance_for(entity_type, entity_id)

    def _count_rows(self, table: str, where: str, params: tuple[object, ...]) -> int:
        row = self._conn.execute(f"SELECT COUNT(1) FROM {table} WHERE {where}", params).fetchone()
        return int(row[0] or 0) if row else 0

    def _load_suggestion_row(self, suggestion_id: str) -> SuggestionRow | None:
        return self._suggestion_repository.load_suggestion_row(suggestion_id)

    def _is_pinned(self, table: str, id_column: str, entity_id: str) -> bool:
        return self._entity_context_service._is_pinned(table, id_column, entity_id)

    def _orphan_entity_ids(self, entity_type: str, *, removing_meeting_id: str = "") -> list[str]:
        return self._entity_context_service.orphan_entity_ids(
            entity_type,
            removing_meeting_id=removing_meeting_id,
        )

    def _orphan_entity_ids_for_artifact_cleanup(
        self,
        entity_type: str,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
    ) -> list[str]:
        return self._entity_context_service.orphan_entity_ids_for_artifact_cleanup(
            entity_type,
            meeting_id,
            source_kind,
            source_alias,
        )

    # ---- Schema ----

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    status TEXT NOT NULL,
                    project_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_mentions (
                    mention_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    meeting_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_alias TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, meeting_id, source_kind, source_alias, original_text)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_mentions (
                    mention_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    meeting_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_alias TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, meeting_id, source_kind, source_alias, original_text)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agendas (
                    agenda_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    normalized TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agenda_mentions (
                    mention_id TEXT PRIMARY KEY,
                    agenda_id TEXT NOT NULL,
                    meeting_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_alias TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(agenda_id, meeting_id, source_kind, source_alias, original_text)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS management_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
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
                    updated_at TEXT NOT NULL,
                    UNIQUE(kind, normalized_key, source_meeting_id, source_kind, source_alias)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_links (
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

            self._ensure_column("tasks", "notes", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("tasks", "pinned", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("projects", "status", "TEXT NOT NULL DEFAULT 'active'")
            self._ensure_column("projects", "pinned", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("agendas", "status", "TEXT NOT NULL DEFAULT 'active'")
            self._ensure_column("agendas", "pinned", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("management_suggestions", "description", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("management_suggestions", "reasoning_short", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("management_suggestions", "confidence", "REAL NOT NULL DEFAULT 0")
            self._ensure_column("management_suggestions", "state", "TEXT NOT NULL DEFAULT 'suggested'")
            self._ensure_column("management_suggestions", "source_alias", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("management_suggestions", "evidence_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column("management_suggestions", "approved_entity_type", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("management_suggestions", "approved_entity_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("management_suggestions", "updated_at", "TEXT NOT NULL DEFAULT ''")

            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_task_mentions_task ON task_mentions(task_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_task_mentions_meeting ON task_mentions(meeting_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_project_mentions_project ON project_mentions(project_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_project_mentions_meeting ON project_mentions(meeting_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agenda_mentions_agenda ON agenda_mentions(agenda_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agenda_mentions_meeting ON agenda_mentions(meeting_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_management_suggestions_meeting ON management_suggestions(source_meeting_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_management_suggestions_state ON management_suggestions(state, kind)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_links_left ON entity_links(left_type, left_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_links_right ON entity_links(right_type, right_id)")

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        existing = self._table_columns(table)
        if column in existing:
            return
        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _table_columns(self, table: str) -> set[str]:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows if len(row) > 1}
