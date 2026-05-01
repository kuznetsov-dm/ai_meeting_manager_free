from __future__ import annotations

import sqlite3
from collections.abc import Callable

from aimn.core.management_cleanup_policy_service import ManagementCleanupPolicyService


class ManagementCleanupService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        count_rows: Callable[[str, str, tuple[object, ...]], int],
        orphan_entity_ids: Callable[[str], list[str]] | Callable[..., list[str]],
        orphan_entity_ids_for_artifact_cleanup: Callable[[str, str, str, str], list[str]],
        delete_task: Callable[[str], bool],
        delete_project: Callable[[str], bool],
        delete_agenda: Callable[[str], bool],
    ) -> None:
        self._conn = conn
        self._count_rows = count_rows
        self._orphan_entity_ids = orphan_entity_ids
        self._orphan_entity_ids_for_artifact_cleanup = orphan_entity_ids_for_artifact_cleanup
        self._delete_task = delete_task
        self._delete_project = delete_project
        self._delete_agenda = delete_agenda

    def preview_meeting_cleanup(self, meeting_id: str) -> dict[str, int]:
        mid = str(meeting_id or "").strip()
        if not mid:
            return ManagementCleanupPolicyService.empty_meeting_preview()
        suggestions = self._count_rows("management_suggestions", "source_meeting_id = ?", (mid,))
        task_mentions = self._count_rows("task_mentions", "meeting_id = ?", (mid,))
        project_mentions = self._count_rows("project_mentions", "meeting_id = ?", (mid,))
        agenda_mentions = self._count_rows("agenda_mentions", "meeting_id = ?", (mid,))
        meeting_links = self._count_rows(
            "entity_links",
            "(left_type = ? AND left_id = ?) OR (right_type = ? AND right_id = ?)",
            ("meeting", mid, "meeting", mid),
        )
        return {
            "suggestions": suggestions,
            "task_mentions": task_mentions,
            "project_mentions": project_mentions,
            "agenda_mentions": agenda_mentions,
            "meeting_links": meeting_links,
            "orphan_tasks": len(self._orphan_entity_ids("task", removing_meeting_id=mid)),
            "orphan_projects": len(self._orphan_entity_ids("project", removing_meeting_id=mid)),
            "orphan_agendas": len(self._orphan_entity_ids("agenda", removing_meeting_id=mid)),
        }

    def preview_artifact_alias_cleanup(
        self,
        *,
        meeting_id: str,
        artifact_kind: str,
        source_alias: str,
    ) -> dict[str, int]:
        mid = str(meeting_id or "").strip()
        kind = str(artifact_kind or "").strip().lower()
        alias = str(source_alias or "").strip()
        if not mid or not alias:
            return ManagementCleanupPolicyService.empty_artifact_preview()
        source_kinds = ManagementCleanupPolicyService.artifact_alias_source_kinds(kind)
        preview = ManagementCleanupPolicyService.empty_artifact_preview()
        orphan_tasks: set[str] = set()
        orphan_projects: set[str] = set()
        orphan_agendas: set[str] = set()
        for source_kind in source_kinds:
            preview["suggestions"] += self._count_rows(
                "management_suggestions",
                "source_meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, source_kind, alias),
            )
            preview["task_mentions"] += self._count_rows(
                "task_mentions",
                "meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, source_kind, alias),
            )
            preview["project_mentions"] += self._count_rows(
                "project_mentions",
                "meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, source_kind, alias),
            )
            preview["agenda_mentions"] += self._count_rows(
                "agenda_mentions",
                "meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, source_kind, alias),
            )
            orphan_tasks.update(
                self._orphan_entity_ids_for_artifact_cleanup("task", mid, source_kind, alias)
            )
            orphan_projects.update(
                self._orphan_entity_ids_for_artifact_cleanup("project", mid, source_kind, alias)
            )
            orphan_agendas.update(
                self._orphan_entity_ids_for_artifact_cleanup("agenda", mid, source_kind, alias)
            )
        preview["orphan_tasks"] = len(orphan_tasks)
        preview["orphan_projects"] = len(orphan_projects)
        preview["orphan_agendas"] = len(orphan_agendas)
        return preview

    def preview_artifact_source_cleanup(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
    ) -> dict[str, int]:
        mid = str(meeting_id or "").strip()
        kind = str(source_kind or "").strip()
        alias = str(source_alias or "").strip()
        if not mid or not kind:
            return ManagementCleanupPolicyService.empty_artifact_preview()
        return {
            "suggestions": self._count_rows(
                "management_suggestions",
                "source_meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, kind, alias),
            ),
            "task_mentions": self._count_rows(
                "task_mentions",
                "meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, kind, alias),
            ),
            "project_mentions": self._count_rows(
                "project_mentions",
                "meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, kind, alias),
            ),
            "agenda_mentions": self._count_rows(
                "agenda_mentions",
                "meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, kind, alias),
            ),
            "orphan_tasks": len(self._orphan_entity_ids_for_artifact_cleanup("task", mid, kind, alias)),
            "orphan_projects": len(
                self._orphan_entity_ids_for_artifact_cleanup("project", mid, kind, alias)
            ),
            "orphan_agendas": len(
                self._orphan_entity_ids_for_artifact_cleanup("agenda", mid, kind, alias)
            ),
        }

    def cleanup_meeting(self, meeting_id: str, *, delete_orphan_entities: bool = False) -> dict[str, int]:
        mid = str(meeting_id or "").strip()
        if not mid:
            return {}
        orphan_tasks = self._orphan_entity_ids("task", removing_meeting_id=mid) if delete_orphan_entities else []
        orphan_projects = (
            self._orphan_entity_ids("project", removing_meeting_id=mid) if delete_orphan_entities else []
        )
        orphan_agendas = self._orphan_entity_ids("agenda", removing_meeting_id=mid) if delete_orphan_entities else []
        counts = self.preview_meeting_cleanup(mid)
        with self._conn:
            self._conn.execute("DELETE FROM management_suggestions WHERE source_meeting_id = ?", (mid,))
            self._conn.execute("DELETE FROM task_mentions WHERE meeting_id = ?", (mid,))
            self._conn.execute("DELETE FROM project_mentions WHERE meeting_id = ?", (mid,))
            self._conn.execute("DELETE FROM agenda_mentions WHERE meeting_id = ?", (mid,))
            self._conn.execute(
                "DELETE FROM entity_links WHERE (left_type = ? AND left_id = ?) OR (right_type = ? AND right_id = ?)",
                ("meeting", mid, "meeting", mid),
            )
        if delete_orphan_entities:
            for entity_id in orphan_tasks:
                self._delete_task(entity_id)
            for entity_id in orphan_projects:
                self._delete_project(entity_id)
            for entity_id in orphan_agendas:
                self._delete_agenda(entity_id)
        counts["deleted_orphan_tasks"] = len(orphan_tasks)
        counts["deleted_orphan_projects"] = len(orphan_projects)
        counts["deleted_orphan_agendas"] = len(orphan_agendas)
        return counts

    def cleanup_artifact_source(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        delete_orphan_entities: bool = False,
    ) -> dict[str, int]:
        mid = str(meeting_id or "").strip()
        sk = str(source_kind or "").strip()
        sa = str(source_alias or "").strip()
        if not mid or not sk:
            return {}
        orphan_tasks = (
            self._orphan_entity_ids_for_artifact_cleanup("task", mid, sk, sa)
            if delete_orphan_entities
            else []
        )
        orphan_projects = (
            self._orphan_entity_ids_for_artifact_cleanup("project", mid, sk, sa)
            if delete_orphan_entities
            else []
        )
        orphan_agendas = (
            self._orphan_entity_ids_for_artifact_cleanup("agenda", mid, sk, sa)
            if delete_orphan_entities
            else []
        )
        with self._conn:
            suggestions_cur = self._conn.execute(
                """
                DELETE FROM management_suggestions
                WHERE source_meeting_id = ? AND source_kind = ? AND source_alias = ?
                """,
                (mid, sk, sa),
            )
            task_cur = self._conn.execute(
                "DELETE FROM task_mentions WHERE meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, sk, sa),
            )
            project_cur = self._conn.execute(
                "DELETE FROM project_mentions WHERE meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, sk, sa),
            )
            agenda_cur = self._conn.execute(
                "DELETE FROM agenda_mentions WHERE meeting_id = ? AND source_kind = ? AND source_alias = ?",
                (mid, sk, sa),
            )
        if delete_orphan_entities:
            for entity_id in orphan_tasks:
                self._delete_task(entity_id)
            for entity_id in orphan_projects:
                self._delete_project(entity_id)
            for entity_id in orphan_agendas:
                self._delete_agenda(entity_id)
        return {
            "suggestions": int(getattr(suggestions_cur, "rowcount", 0) or 0),
            "task_mentions": int(getattr(task_cur, "rowcount", 0) or 0),
            "project_mentions": int(getattr(project_cur, "rowcount", 0) or 0),
            "agenda_mentions": int(getattr(agenda_cur, "rowcount", 0) or 0),
            "deleted_orphan_tasks": len(orphan_tasks),
            "deleted_orphan_projects": len(orphan_projects),
            "deleted_orphan_agendas": len(orphan_agendas),
        }

    def cleanup_artifact_alias(
        self,
        *,
        meeting_id: str,
        artifact_kind: str,
        source_alias: str,
        delete_orphan_entities: bool = False,
    ) -> dict[str, int]:
        mid = str(meeting_id or "").strip()
        kind = str(artifact_kind or "").strip().lower()
        alias = str(source_alias or "").strip()
        if not mid or not alias:
            return {}
        source_kinds = ManagementCleanupPolicyService.artifact_alias_source_kinds(kind)
        total = {
            "suggestions": 0,
            "task_mentions": 0,
            "project_mentions": 0,
            "agenda_mentions": 0,
            "deleted_orphan_tasks": 0,
            "deleted_orphan_projects": 0,
            "deleted_orphan_agendas": 0,
        }
        orphan_tasks: set[str] = set()
        orphan_projects: set[str] = set()
        orphan_agendas: set[str] = set()
        for source_kind in source_kinds:
            if delete_orphan_entities:
                orphan_tasks.update(
                    self._orphan_entity_ids_for_artifact_cleanup("task", mid, source_kind, alias)
                )
                orphan_projects.update(
                    self._orphan_entity_ids_for_artifact_cleanup("project", mid, source_kind, alias)
                )
                orphan_agendas.update(
                    self._orphan_entity_ids_for_artifact_cleanup("agenda", mid, source_kind, alias)
                )
            result = self.cleanup_artifact_source(
                meeting_id=mid,
                source_kind=source_kind,
                source_alias=alias,
                delete_orphan_entities=False,
            )
            for key, value in result.items():
                total[key] = int(total.get(key, 0) or 0) + int(value or 0)
        if delete_orphan_entities:
            for entity_id in orphan_tasks:
                self._delete_task(entity_id)
            for entity_id in orphan_projects:
                self._delete_project(entity_id)
            for entity_id in orphan_agendas:
                self._delete_agenda(entity_id)
            total["deleted_orphan_tasks"] = len(orphan_tasks)
            total["deleted_orphan_projects"] = len(orphan_projects)
            total["deleted_orphan_agendas"] = len(orphan_agendas)
        return total
