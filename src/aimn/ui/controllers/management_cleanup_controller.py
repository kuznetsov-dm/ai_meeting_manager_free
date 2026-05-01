from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox, QWidget

from aimn.core.api import ManagementStore

QuestionFn = Callable[[QWidget | None, str, str, int, int], int]
InformationFn = Callable[[QWidget | None, str, str], object]
StoreFactory = Callable[[], ManagementStore]
TranslateFn = Callable[[str, str], str]
FormatFn = Callable[..., str]


class ManagementCleanupController:
    def __init__(
        self,
        *,
        app_root: Path,
        parent: QWidget | None,
        tr: TranslateFn,
        fmt: FormatFn,
        store_factory: StoreFactory | None = None,
        question: QuestionFn = QMessageBox.question,
        information: InformationFn = QMessageBox.information,
    ) -> None:
        self._app_root = app_root
        self._parent = parent
        self._tr = tr
        self._fmt = fmt
        self._store_factory = store_factory or (lambda: ManagementStore(app_root))
        self._question = question
        self._information = information

    def run_meeting_cleanup(self, meeting_id: str) -> dict[str, int] | None:
        mid = str(meeting_id or "").strip()
        if not mid:
            return None
        return self._run_cleanup(
            policy_loader=lambda store: store.prepare_meeting_cleanup(mid),
            cleanup_runner=lambda store, delete_orphans: store.cleanup_meeting(
                mid,
                delete_orphan_entities=delete_orphans,
            ),
            empty_title=("cleanup_meeting.empty.title", "Nothing to clean"),
            empty_message=(
                "cleanup_meeting.empty.message",
                "No Management suggestions, meeting mentions, or links were found for the focused meeting.",
            ),
            confirm_title=("cleanup_meeting.title", "Clean Management data for this meeting?"),
            confirm_message=(
                "cleanup_meeting.message",
                "This will remove pending suggestions and meeting mentions for the focused meeting.\n\n"
                "Suggestions: {suggestions}\nTask mentions: {tasks}\nProject mentions: {projects}\n"
                "Agenda mentions: {agendas}\nMeeting links: {links}",
            ),
            orphan_title=("cleanup_meeting.orphans.title", "Also delete orphan AI entities?"),
            orphan_message=(
                "cleanup_meeting.orphans.message",
                "After removing this meeting's mentions, some AI-created entities will have no remaining meetings or links.\n\n"
                "Also delete those orphan entities?\n\nTasks: {tasks}\nProjects: {projects}\nAgendas: {agendas}",
            ),
            done_title=("cleanup_meeting.done.title", "Management cleanup completed"),
            done_message=(
                "cleanup_meeting.done.message",
                "Removed suggestions: {suggestions}\nTask mentions: {tasks}\nProject mentions: {projects}\n"
                "Agenda mentions: {agendas}\nMeeting links: {links}\n\nDeleted orphan tasks: {deleted_tasks}\n"
                "Deleted orphan projects: {deleted_projects}\nDeleted orphan agendas: {deleted_agendas}",
            ),
            confirm_params={},
            include_meeting_links=True,
        )

    def run_artifact_source_cleanup(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str = "",
        suggestion_id: str = "",
    ) -> dict[str, int] | None:
        mid = str(meeting_id or "").strip()
        kind = str(source_kind or "").strip()
        alias = str(source_alias or "").strip()
        sid = str(suggestion_id or "").strip()
        if not mid or not kind:
            return None
        return self._run_cleanup(
            policy_loader=lambda store: store.prepare_artifact_source_cleanup(
                meeting_id=mid,
                source_kind=kind,
                source_alias=alias,
            ),
            cleanup_runner=lambda store, delete_orphans: self._cleanup_artifact_source(
                store=store,
                meeting_id=mid,
                source_kind=kind,
                source_alias=alias,
                suggestion_id=sid,
                delete_orphans=delete_orphans,
            ),
            empty_title=("cleanup_source.empty.title", "Nothing to clean"),
            empty_message=(
                "cleanup_source.empty.message",
                "No Management suggestions or mentions were found for this suggestion source.",
            ),
            confirm_title=("cleanup_source.title", "Clean this suggestion source?"),
            confirm_message=(
                "cleanup_source.message",
                "This will remove all Management suggestions and mentions produced from the same source.\n\n"
                "Source kind: {source_kind}\nSource alias: {source_alias}\n\nSuggestions: {suggestions}\n"
                "Task mentions: {tasks}\nProject mentions: {projects}\nAgenda mentions: {agendas}",
            ),
            orphan_title=("cleanup_source.orphans.title", "Also delete orphan AI entities?"),
            orphan_message=(
                "cleanup_source.orphans.message",
                "After removing this source, some AI-created entities will have no remaining meetings or links.\n\n"
                "Also delete those orphan entities?\n\nTasks: {tasks}\nProjects: {projects}\nAgendas: {agendas}",
            ),
            done_title=("cleanup_source.done.title", "Source cleanup completed"),
            done_message=(
                "cleanup_source.done.message",
                "Removed suggestions: {suggestions}\nTask mentions: {tasks}\nProject mentions: {projects}\n"
                "Agenda mentions: {agendas}\n\nDeleted orphan tasks: {deleted_tasks}\n"
                "Deleted orphan projects: {deleted_projects}\nDeleted orphan agendas: {deleted_agendas}",
            ),
            confirm_params={"source_kind": kind, "source_alias": alias or "-"},
            include_meeting_links=False,
        )

    def run_artifact_alias_cleanup(
        self,
        *,
        meeting_id: str,
        artifact_kind: str,
        source_alias: str,
    ) -> dict[str, int] | None:
        mid = str(meeting_id or "").strip()
        kind = str(artifact_kind or "").strip()
        alias = str(source_alias or "").strip()
        if not mid or not alias:
            return None
        return self._run_cleanup(
            policy_loader=lambda store: store.prepare_artifact_alias_cleanup(
                meeting_id=mid,
                artifact_kind=kind,
                source_alias=alias,
            ),
            cleanup_runner=lambda store, delete_orphans: store.cleanup_artifact_alias(
                meeting_id=mid,
                artifact_kind=kind,
                source_alias=alias,
                delete_orphan_entities=delete_orphans,
            ),
            empty_title=("artifact_cleanup.empty.title", "Nothing to clean"),
            empty_message=(
                "artifact_cleanup.empty.message",
                "No related Management suggestions or entity links were found for this artifact.",
            ),
            confirm_title=("artifact_cleanup.title", "Clean Management data for this artifact?"),
            confirm_message=(
                "artifact_cleanup.message",
                "This will remove Management suggestions and meeting mentions linked to this artifact version.\n\n"
                "Suggestions: {suggestions}\nTask mentions: {tasks}\nProject mentions: {projects}\n"
                "Agenda mentions: {agendas}",
            ),
            orphan_title=("artifact_cleanup.orphans.title", "Also delete orphan AI entities?"),
            orphan_message=(
                "artifact_cleanup.orphans.message",
                "After removing this artifact's links, some AI-created entities will have no remaining meetings or links.\n\n"
                "Also delete those orphan entities?\n\nTasks: {tasks}\nProjects: {projects}\nAgendas: {agendas}",
            ),
            done_title=("artifact_cleanup.done.title", "Management cleanup completed"),
            done_message=(
                "artifact_cleanup.done.message",
                "Removed suggestions: {suggestions}\nTask mentions: {tasks}\nProject mentions: {projects}\n"
                "Agenda mentions: {agendas}\n\nDeleted orphan tasks: {deleted_tasks}\n"
                "Deleted orphan projects: {deleted_projects}\nDeleted orphan agendas: {deleted_agendas}",
            ),
            confirm_params={},
            include_meeting_links=False,
        )

    def cleanup_meeting_for_delete(self, meeting_id: str) -> bool:
        mid = str(meeting_id or "").strip()
        if not mid:
            return True
        policy = self._load_policy(lambda store: store.prepare_meeting_cleanup(mid))
        if not bool(policy.get("has_changes", False)):
            return True
        delete_orphans = self._confirm_orphans(
            policy,
            title_key="delete.cleanup.title",
            title_default="Cleanup related management entities?",
            message_key="delete.cleanup.message",
            message_default=(
                "Suggestions and meeting links will be removed automatically.\n\n"
                "Also delete orphan AI entities with no other meetings or links?\n\n"
                "Tasks: {tasks}\nProjects: {projects}\nAgendas: {agendas}"
            ),
        )
        if delete_orphans is None:
            return False
        self._apply_cleanup(
            lambda store: store.cleanup_meeting(mid, delete_orphan_entities=delete_orphans)
        )
        return True

    def _run_cleanup(
        self,
        *,
        policy_loader: Callable[[ManagementStore], dict[str, object]],
        cleanup_runner: Callable[[ManagementStore, bool], dict[str, int]],
        empty_title: tuple[str, str],
        empty_message: tuple[str, str],
        confirm_title: tuple[str, str],
        confirm_message: tuple[str, str],
        orphan_title: tuple[str, str],
        orphan_message: tuple[str, str],
        done_title: tuple[str, str],
        done_message: tuple[str, str],
        confirm_params: dict[str, object],
        include_meeting_links: bool,
    ) -> dict[str, int] | None:
        policy = self._load_policy(policy_loader)
        if not bool(policy.get("has_changes", False)):
            self._information(
                self._parent,
                self._tr(*empty_title),
                self._tr(*empty_message),
            )
            return None
        if self._question(
            self._parent,
            self._tr(*confirm_title),
            self._fmt(
                confirm_message[0],
                confirm_message[1],
                **self._cleanup_counts(policy, include_meeting_links=include_meeting_links, **confirm_params),
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return None
        delete_orphans = self._confirm_orphans(
            policy,
            title_key=orphan_title[0],
            title_default=orphan_title[1],
            message_key=orphan_message[0],
            message_default=orphan_message[1],
        )
        if delete_orphans is None:
            return None
        result = self._apply_cleanup(lambda store: cleanup_runner(store, delete_orphans))
        self._information(
            self._parent,
            self._tr(*done_title),
            self._fmt(
                done_message[0],
                done_message[1],
                **self._done_counts(result, include_meeting_links=include_meeting_links),
            ),
        )
        return result

    def _confirm_orphans(
        self,
        policy: dict[str, object],
        *,
        title_key: str,
        title_default: str,
        message_key: str,
        message_default: str,
    ) -> bool | None:
        if not bool(policy.get("has_orphans", False)):
            return False
        reply = self._question(
            self._parent,
            self._tr(title_key, title_default),
            self._fmt(
                message_key,
                message_default,
                tasks=self._count(policy, "orphan_tasks"),
                projects=self._count(policy, "orphan_projects"),
                agendas=self._count(policy, "orphan_agendas"),
            ),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.No,
        )
        if reply == QMessageBox.Cancel:
            return None
        return reply == QMessageBox.Yes

    def _load_policy(
        self,
        loader: Callable[[ManagementStore], dict[str, object]],
    ) -> dict[str, object]:
        store = self._store_factory()
        try:
            return dict(loader(store) or {})
        finally:
            store.close()

    def _apply_cleanup(
        self,
        runner: Callable[[ManagementStore], dict[str, int]],
    ) -> dict[str, int]:
        store = self._store_factory()
        try:
            return dict(runner(store) or {})
        finally:
            store.close()

    @staticmethod
    def _cleanup_artifact_source(
        *,
        store: ManagementStore,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        suggestion_id: str,
        delete_orphans: bool,
    ) -> dict[str, int]:
        result = store.cleanup_artifact_source(
            meeting_id=meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            delete_orphan_entities=delete_orphans,
        )
        if suggestion_id:
            store.set_suggestion_state(suggestion_id, "hidden")
        return dict(result or {})

    @staticmethod
    def _count(payload: dict[str, object], key: str) -> int:
        try:
            return int(payload.get(key, 0) or 0)
        except (AttributeError, TypeError, ValueError):
            return 0

    def _cleanup_counts(
        self,
        payload: dict[str, object],
        *,
        include_meeting_links: bool,
        **extra: object,
    ) -> dict[str, Any]:
        counts: dict[str, Any] = {
            "suggestions": self._count(payload, "suggestions"),
            "tasks": self._count(payload, "task_mentions"),
            "projects": self._count(payload, "project_mentions"),
            "agendas": self._count(payload, "agenda_mentions"),
        }
        if include_meeting_links:
            counts["links"] = self._count(payload, "meeting_links")
        counts.update(extra)
        return counts

    def _done_counts(
        self,
        payload: dict[str, object],
        *,
        include_meeting_links: bool,
    ) -> dict[str, Any]:
        counts = self._cleanup_counts(payload, include_meeting_links=include_meeting_links)
        counts["deleted_tasks"] = self._count(payload, "deleted_orphan_tasks")
        counts["deleted_projects"] = self._count(payload, "deleted_orphan_projects")
        counts["deleted_agendas"] = self._count(payload, "deleted_orphan_agendas")
        return counts
