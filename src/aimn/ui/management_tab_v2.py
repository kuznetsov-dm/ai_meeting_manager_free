from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import ManagementStore
from aimn.core.release_profile import active_release_profile
from aimn.ui.controllers.management_cleanup_controller import ManagementCleanupController
from aimn.ui.i18n import UiI18n
from aimn.ui.services.artifact_service import ArtifactService
from aimn.ui.services.async_worker import run_async
from aimn.ui.widgets.standard_components import (
    StandardActionButton,
    StandardBadge,
    StandardCard,
    StandardPanel,
)

_PERF_WARN_RELOAD_MS = 220
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntityItem:
    entity_type: str
    entity_id: str
    title: str
    subtitle: str
    status: str
    updated_at: str


class ClickableEntityCard(StandardCard):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        child = self.childAt(event.pos())
        while child is not None and child is not self:
            if isinstance(child, QAbstractButton):
                super().mousePressEvent(event)
                return
            child = child.parentWidget()
        self.clicked.emit()
        super().mousePressEvent(event)


class ManagementTabV2(QWidget):
    evidenceOpenRequested = Signal(dict)
    _ADJACENT: dict[str, set[str]] = {
        "meeting": {"agenda", "project", "task"},
        "agenda": {"meeting", "project", "task"},
        "project": {"meeting", "agenda", "task"},
        "task": {"meeting", "agenda", "project"},
    }

    def __init__(self, app_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_root = app_root
        self._release_profile = active_release_profile(app_root)
        self._placeholder_mode = False
        self._i18n = UiI18n(app_root, namespace="management")
        self._artifact_service = ArtifactService(app_root)
        self._last_reload_monotonic: float = 0.0
        self._reload_request_id: int = 0
        self._reload_pending: bool = False
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(60)
        self._reload_timer.timeout.connect(self._flush_reload_request)

        self._focus_type: str = ""
        self._focus_id: str = ""

        self._search: dict[str, str] = {
            "meeting": "",
            "agenda": "",
            "project": "",
            "task": "",
        }
        self._items: dict[str, list[EntityItem]] = {
            "meeting": [],
            "agenda": [],
            "project": [],
            "task": [],
        }
        self._rows: dict[str, dict[str, dict]] = {
            "meeting": {},
            "agenda": {},
            "project": {},
            "task": {},
        }
        self._suggestions: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        if self._release_profile.profile_id == "core_free":
            self._placeholder_mode = True
            self._build_core_free_placeholder(layout)
            return

        header = QHBoxLayout()
        title = QLabel(self._tr("title", "Management"))
        title.setObjectName("pageTitle")
        header.addWidget(title, 1)

        self._focus_label = QLabel(
            self._tr("focus.none", "Context: not selected. Click any tile to focus relations.")
        )
        self._focus_label.setObjectName("pipelineMetaLabel")
        header.addWidget(self._focus_label, 0)

        self._clear_selection_button = QPushButton(self._tr("button.clear_focus", "Clear focus"))
        self._clear_selection_button.clicked.connect(self._clear_focus)
        header.addWidget(self._clear_selection_button)

        self._reload_button = QPushButton(self._tr("button.reload", "Reload"))
        self._reload_button.clicked.connect(self.reload)
        header.addWidget(self._reload_button)

        self._open_output = QPushButton(self._tr("button.open_output", "Open output folder"))
        self._open_output.clicked.connect(self._artifact_service.open_output_folder)
        header.addWidget(self._open_output)
        layout.addLayout(header)

        self._suggestions_panel = StandardPanel()
        suggestions_layout = QVBoxLayout(self._suggestions_panel)
        suggestions_layout.setContentsMargins(12, 12, 12, 12)
        suggestions_layout.setSpacing(8)

        suggestions_header = QHBoxLayout()
        self._suggestions_title = QLabel(self._tr("suggestions.title", "Suggestions"))
        self._suggestions_title.setObjectName("pageTitle")
        suggestions_header.addWidget(self._suggestions_title, 1)
        self._approve_shown_button = QPushButton(self._tr("button.approve_shown", "Approve shown"))
        self._approve_shown_button.clicked.connect(self._approve_shown_suggestions)
        self._approve_shown_button.setEnabled(False)
        suggestions_header.addWidget(self._approve_shown_button, 0)
        self._merge_shown_button = QPushButton(self._tr("button.merge_shown", "Merge obvious"))
        self._merge_shown_button.clicked.connect(self._merge_shown_obvious_suggestions)
        self._merge_shown_button.setEnabled(False)
        suggestions_header.addWidget(self._merge_shown_button, 0)
        self._hide_shown_button = QPushButton(self._tr("button.hide_shown", "Hide shown"))
        self._hide_shown_button.clicked.connect(self._hide_shown_suggestions)
        self._hide_shown_button.setEnabled(False)
        suggestions_header.addWidget(self._hide_shown_button, 0)
        self._cleanup_focus_button = QPushButton(
            self._tr("button.cleanup_focus_meeting", "Clean focused meeting")
        )
        self._cleanup_focus_button.clicked.connect(self._cleanup_focused_meeting_management)
        self._cleanup_focus_button.setEnabled(False)
        suggestions_header.addWidget(self._cleanup_focus_button, 0)
        self._suggestions_meta = QLabel(self._tr("suggestions.empty", "No pending suggestions."))
        self._suggestions_meta.setObjectName("pipelineMetaLabel")
        suggestions_header.addWidget(self._suggestions_meta, 0)
        suggestions_layout.addLayout(suggestions_header)

        self._suggestions_scroll = QScrollArea()
        self._suggestions_scroll.setWidgetResizable(True)
        self._suggestions_scroll.setFrameShape(QFrame.NoFrame)
        self._suggestions_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._suggestions_container = QWidget()
        self._suggestions_list = QVBoxLayout(self._suggestions_container)
        self._suggestions_list.setContentsMargins(0, 0, 0, 0)
        self._suggestions_list.setSpacing(8)
        self._suggestions_scroll.setWidget(self._suggestions_container)
        suggestions_layout.addWidget(self._suggestions_scroll)
        layout.addWidget(self._suggestions_panel)

        columns = QGridLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setHorizontalSpacing(10)
        columns.setVerticalSpacing(0)

        self._column_lists: dict[str, QVBoxLayout] = {}
        self._column_search: dict[str, QLineEdit] = {}

        order = [
            ("meeting", self._tr("column.meetings", "Meetings"), False),
            ("agenda", self._tr("column.agendas", "Agendas"), True),
            ("project", self._tr("column.projects", "Projects"), True),
            ("task", self._tr("column.tasks", "Tasks"), True),
        ]
        for col, (entity_type, title_text, can_add) in enumerate(order):
            columns.addWidget(self._build_column(entity_type, title_text, can_add), 0, col)

        for col in range(4):
            columns.setColumnStretch(col, 1)
        layout.addLayout(columns, 1)

        self.reload(immediate=True)

    def _tr(self, key: str, default: str) -> str:
        return self._i18n.t(key, default)

    def _fmt(self, key: str, default: str, **kwargs: object) -> str:
        template = self._tr(key, default)
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def _build_core_free_placeholder(self, layout: QVBoxLayout) -> None:
        title = QLabel(self._tr("core_free.title", "Management extensions are not included in this release."))
        title.setObjectName("pageTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        panel = StandardPanel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)

        body = QLabel(
            self._tr(
                "core_free.body",
                "Core Free keeps the management stage in the pipeline, but real management plugins are available only in Pro.",
            )
        )
        body.setObjectName("pipelineMetaLabel")
        body.setWordWrap(True)
        panel_layout.addWidget(body)

        note = QLabel(
            self._tr(
                "core_free.note",
                "Upgrade the release profile later to enable tasks, projects, agendas, and related management automation.",
            )
        )
        note.setObjectName("pipelineMetaLabel")
        note.setWordWrap(True)
        panel_layout.addWidget(note)

        layout.addWidget(panel)
        layout.addStretch(1)

    def shutdown(self) -> None:
        if self._reload_timer.isActive():
            self._reload_timer.stop()
        self._artifact_service.close()

    def reload(self, _checked: bool = False, *, immediate: bool = False, force: bool = False) -> None:
        if self._placeholder_mode:
            return
        self._reload_pending = True
        if bool(immediate):
            if self._reload_timer.isActive():
                self._reload_timer.stop()
            self._flush_reload_request()
            return
        if not self._reload_timer.isActive():
            self._reload_timer.start()

    def _flush_reload_request(self) -> None:
        if not self._reload_pending:
            return
        self._reload_pending = False
        self._start_reload_async()

    def _start_reload_async(self) -> None:
        perf_started = time.perf_counter()
        request_id = int(self._reload_request_id + 1)
        self._reload_request_id = request_id
        self._set_reload_running(True)

        def _worker() -> dict[str, object]:
            store = ManagementStore(self._app_root)
            artifact_service = ArtifactService(self._app_root)
            try:
                meetings, meeting_rows = self._load_meetings(store, artifact_service=artifact_service)
                agendas, agenda_rows = self._load_agendas(store)
                projects, project_rows = self._load_projects(store)
                tasks, task_rows = self._load_tasks(store)
                suggestions = store.list_suggestions(state="suggested")
                return {
                    "meetings": meetings,
                    "meeting_rows": meeting_rows,
                    "agendas": agendas,
                    "agenda_rows": agenda_rows,
                    "projects": projects,
                    "project_rows": project_rows,
                    "tasks": tasks,
                    "task_rows": task_rows,
                    "suggestions": suggestions,
                }
            finally:
                store.close()
                artifact_service.close()

        def _on_finished(done_request_id: int, payload: object) -> None:
            if int(done_request_id) != int(self._reload_request_id):
                return
            self._set_reload_running(False)
            data = payload if isinstance(payload, dict) else {}
            self._apply_reload_payload(data, perf_started=perf_started)
            if self._reload_pending:
                QTimer.singleShot(0, self._flush_reload_request)

        def _on_error(done_request_id: int, error: Exception) -> None:
            if int(done_request_id) != int(self._reload_request_id):
                return
            self._set_reload_running(False)
            _LOG.exception("management_reload_async_failed")
            elapsed_ms = int(max(0.0, (time.perf_counter() - perf_started) * 1000.0))
            _LOG.warning("slow_ui_path ManagementTabV2.reload.error: elapsed_ms=%s, error=%s", elapsed_ms, error)
            if self._reload_pending:
                QTimer.singleShot(0, self._flush_reload_request)

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _set_reload_running(self, running: bool) -> None:
        if self._placeholder_mode:
            return
        self._reload_button.setEnabled(not bool(running))

    def _apply_reload_payload(self, payload: dict[str, object], *, perf_started: float) -> None:
        meetings = list(payload.get("meetings", []) or [])
        agendas = list(payload.get("agendas", []) or [])
        projects = list(payload.get("projects", []) or [])
        tasks = list(payload.get("tasks", []) or [])
        meeting_rows = dict(payload.get("meeting_rows", {}) or {})
        agenda_rows = dict(payload.get("agenda_rows", {}) or {})
        project_rows = dict(payload.get("project_rows", {}) or {})
        task_rows = dict(payload.get("task_rows", {}) or {})
        suggestions = list(payload.get("suggestions", []) or [])

        self._items["meeting"] = meetings
        self._items["agenda"] = agendas
        self._items["project"] = projects
        self._items["task"] = tasks

        self._rows["meeting"] = meeting_rows
        self._rows["agenda"] = agenda_rows
        self._rows["project"] = project_rows
        self._rows["task"] = task_rows
        self._suggestions = suggestions

        if self._focus_type and self._focus_id and self._focus_id not in self._rows.get(self._focus_type, {}):
            self._focus_type = ""
            self._focus_id = ""

        self._refresh_focus_label()
        self._render_suggestions()
        self._render_all_columns()
        self._last_reload_monotonic = time.monotonic()
        elapsed_ms = int(max(0.0, (time.perf_counter() - perf_started) * 1000.0))
        if elapsed_ms >= _PERF_WARN_RELOAD_MS:
            _LOG.warning(
                "slow_ui_path ManagementTabV2.reload: elapsed_ms=%s, meetings=%s, agendas=%s, projects=%s, tasks=%s",
                elapsed_ms,
                len(self._items["meeting"]),
                len(self._items["agenda"]),
                len(self._items["project"]),
                len(self._items["task"]),
            )

    def reload_if_stale(self, *, max_age_seconds: float = 2.5, force: bool = False) -> None:
        if self._placeholder_mode:
            return
        if bool(force):
            self.reload(immediate=True, force=True)
            return
        now = time.monotonic()
        age = now - float(self._last_reload_monotonic or 0.0)
        if age < max(0.1, float(max_age_seconds or 0.0)):
            return
        self.reload()

    def _load_meetings(
        self,
        store: ManagementStore,
        *,
        artifact_service: ArtifactService | None = None,
    ) -> tuple[list[EntityItem], dict[str, dict]]:
        service = artifact_service or self._artifact_service
        meetings = service.list_meetings()
        items: list[EntityItem] = []
        rows: dict[str, dict] = {}
        for meeting in meetings:
            meeting_id = str(getattr(meeting, "meeting_id", "") or "").strip()
            if not meeting_id:
                continue
            display_title = str(getattr(meeting, "display_title", "") or "").strip()
            title = display_title or str(getattr(meeting, "base_name", "") or meeting_id).strip() or meeting_id
            agenda_count = len(store.list_agendas_for_meeting(meeting_id))
            project_count = len(store.list_projects_for_meeting(meeting_id))
            task_count = len(store.list_tasks_for_meeting(meeting_id))
            subtitle = self._fmt(
                "subtitle.meeting_counts",
                "Agendas: {agendas}  Projects: {projects}  Tasks: {tasks}",
                agendas=agenda_count,
                projects=project_count,
                tasks=task_count,
            )
            updated_at = str(getattr(meeting, "updated_at", "") or "")
            items.append(
                EntityItem(
                    entity_type="meeting",
                    entity_id=meeting_id,
                    title=title,
                    subtitle=subtitle,
                    status="",
                    updated_at=updated_at,
                )
            )
            rows[meeting_id] = {"id": meeting_id, "title": title, "updated_at": updated_at}
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items, rows

    def _load_agendas(self, store: ManagementStore) -> tuple[list[EntityItem], dict[str, dict]]:
        items: list[EntityItem] = []
        rows: dict[str, dict] = {}
        for row in store.list_agendas():
            aid = str(row.get("id", "") or "").strip()
            if not aid:
                continue
            text = str(row.get("text", "") or "").strip().replace("\n", " ")
            snippet = text[:120] + ("..." if len(text) > 120 else "")
            meetings = len(row.get("meetings", []) or [])
            subtitle = (
                self._fmt("subtitle.agenda_with_snippet", "{snippet} | Meetings: {meetings}", snippet=snippet, meetings=meetings)
                if snippet
                else self._fmt("subtitle.meetings_count", "Meetings: {meetings}", meetings=meetings)
            )
            item = EntityItem(
                entity_type="agenda",
                entity_id=aid,
                title=str(row.get("title", "") or aid),
                subtitle=subtitle,
                status=str(row.get("status", "active") or "active"),
                updated_at=str(row.get("updated_at", "") or ""),
            )
            items.append(item)
            rows[aid] = dict(row)
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items, rows

    def _load_projects(self, store: ManagementStore) -> tuple[list[EntityItem], dict[str, dict]]:
        items: list[EntityItem] = []
        rows: dict[str, dict] = {}
        for row in store.list_projects():
            pid = str(row.get("id", "") or "").strip()
            if not pid:
                continue
            meetings = len(row.get("meetings", []) or [])
            tasks_count = int(row.get("tasks_count", 0) or 0)
            desc = str(row.get("description", "") or "").strip().replace("\n", " ")
            desc_part = f"{desc[:90]}{'...' if len(desc) > 90 else ''} | " if desc else ""
            subtitle = self._fmt(
                "subtitle.project_counts",
                "{description}Meetings: {meetings}  Tasks: {tasks}",
                description=desc_part,
                meetings=meetings,
                tasks=tasks_count,
            )
            item = EntityItem(
                entity_type="project",
                entity_id=pid,
                title=str(row.get("name", "") or pid),
                subtitle=subtitle,
                status=str(row.get("status", "active") or "active"),
                updated_at=str(row.get("updated_at", "") or ""),
            )
            items.append(item)
            rows[pid] = dict(row)
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items, rows

    def _load_tasks(self, store: ManagementStore) -> tuple[list[EntityItem], dict[str, dict]]:
        projects_by_id = {
            str(p.get("id", "") or ""): str(p.get("name", "") or "")
            for p in store.list_projects()
            if str(p.get("id", "") or "").strip()
        }
        items: list[EntityItem] = []
        rows: dict[str, dict] = {}
        for row in store.list_tasks():
            tid = str(row.get("id", "") or "").strip()
            if not tid:
                continue
            meetings = len(row.get("meetings", []) or [])
            project_ids = [
                str(project_id or "").strip()
                for project_id in (row.get("project_ids", []) or [])
                if str(project_id or "").strip()
            ]
            project_names = [projects_by_id.get(project_id, project_id) for project_id in project_ids]
            if not project_names:
                projects_part = self._tr("subtitle.projects_unassigned", "Projects: unassigned")
            elif len(project_names) == 1:
                projects_part = self._fmt("subtitle.project_single", "Project: {project}", project=project_names[0])
            else:
                preview = ", ".join(project_names[:2])
                more = f" +{len(project_names) - 2}" if len(project_names) > 2 else ""
                projects_part = self._fmt("subtitle.project_many", "Projects: {projects}", projects=f"{preview}{more}")
            subtitle = self._fmt(
                "subtitle.task_counts",
                "{projects} | Meetings: {meetings}",
                projects=projects_part,
                meetings=meetings,
            )
            item = EntityItem(
                entity_type="task",
                entity_id=tid,
                title=str(row.get("title", "") or tid),
                subtitle=subtitle,
                status=str(row.get("status", "open") or "open"),
                updated_at=str(row.get("updated_at", "") or ""),
            )
            items.append(item)
            rows[tid] = dict(row)
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items, rows

    def _build_column(self, entity_type: str, title: str, can_add: bool) -> QWidget:
        frame = StandardPanel()
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        top.addWidget(label, 1)
        if can_add:
            add_btn = QPushButton("+")
            add_btn.setFixedWidth(30)
            add_btn.clicked.connect(lambda *_a, et=entity_type: self._on_add_entity(et))
            top.addWidget(add_btn, 0)
        layout.addLayout(top)

        search = QLineEdit()
        search.setPlaceholderText(self._tr("search.placeholder", "Search"))
        search.textChanged.connect(lambda text, et=entity_type: self._on_search_changed(et, text))
        self._column_search[entity_type] = search
        layout.addWidget(search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addStretch(1)
        self._column_lists[entity_type] = content_layout

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        return frame

    def _render_all_columns(self) -> None:
        for entity_type in ("meeting", "agenda", "project", "task"):
            self._render_column(entity_type)

    def _render_column(self, entity_type: str) -> None:
        layout = self._column_lists.get(entity_type)
        if layout is None:
            return

        while layout.count() > 0:
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        items = list(self._items.get(entity_type, []))
        query = self._search.get(entity_type, "").strip().lower()
        if query:
            items = [
                item
                for item in items
                if query in item.title.lower() or query in item.subtitle.lower() or query in item.entity_id.lower()
            ]

        items.sort(key=lambda item: self._sort_key(item))

        for item in items:
            layout.addWidget(self._build_entity_card(item), 0)
        layout.addStretch(1)

    def _sort_key(self, item: EntityItem) -> tuple:
        rank = self._updated_rank(item.updated_at)
        if not self._focus_type or not self._focus_id:
            return (0, -rank, item.title.lower())

        if item.entity_type == self._focus_type:
            is_focus = item.entity_id == self._focus_id
            return (0 if is_focus else 1, -rank, item.title.lower())

        if self._is_adjacent(self._focus_type, item.entity_type):
            related = self._is_related(
                left_type=self._focus_type,
                left_id=self._focus_id,
                right_type=item.entity_type,
                right_id=item.entity_id,
            )
            return (0 if related else 1, -rank, item.title.lower())

        return (1, -rank, item.title.lower())

    @staticmethod
    def _updated_rank(value: str) -> int:
        text = str(value or "").strip()
        if not text:
            return 0
        normalized = text.replace("Z", "+00:00")
        try:
            return int(datetime.fromisoformat(normalized).timestamp())
        except Exception:
            return 0

    def _entity_provenance_badges(self, item: EntityItem) -> list[tuple[str, str]]:
        row = self._rows.get(item.entity_type, {}).get(item.entity_id, {})
        if not isinstance(row, dict):
            return []
        manual_mentions = int(row.get("manual_mentions", 0) or 0)
        ai_mentions = int(row.get("ai_mentions", 0) or 0)
        mention_count = int(row.get("mention_count", 0) or 0)
        meetings_count = len(row.get("meetings", []) or [])
        badges: list[tuple[str, str]] = []
        if mention_count <= 0 or (manual_mentions > 0 and ai_mentions <= 0):
            badges.append((self._tr("provenance.manual", "Manual"), "neutral"))
        elif ai_mentions > 0 and manual_mentions <= 0:
            badges.append((self._tr("provenance.ai", "AI-approved"), "focus"))
        elif ai_mentions > 0 and manual_mentions > 0:
            badges.append((self._tr("provenance.mixed", "Mixed"), "warning"))
        if meetings_count > 1:
            badges.append((self._tr("provenance.merged", "Merged"), "success"))
        return badges

    def _build_entity_card(self, item: EntityItem) -> QWidget:
        card = ClickableEntityCard()
        card.clicked.connect(lambda et=item.entity_type, eid=item.entity_id: self._on_card_clicked(et, eid))

        outer = QVBoxLayout(card)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        is_focus = item.entity_type == self._focus_type and item.entity_id == self._focus_id
        is_related = False
        if not is_focus and self._focus_type and self._focus_id and self._is_adjacent(self._focus_type, item.entity_type):
            is_related = self._is_related(
                left_type=self._focus_type,
                left_id=self._focus_id,
                right_type=item.entity_type,
                right_id=item.entity_id,
            )
        card.set_variant("focus" if is_focus else "related" if is_related else "default")

        if is_focus:
            focus_tag = StandardBadge(self._tr("tag.selected", "Selected context"))
            focus_tag.set_kind("focus")
            outer.addWidget(focus_tag)
        elif is_related:
            focus_tag = StandardBadge(self._tr("tag.linked", "Linked to selected context"))
            focus_tag.set_kind("related")
            outer.addWidget(focus_tag)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        check = QCheckBox()
        can_toggle = self._can_toggle_checkbox(item.entity_type)
        checked = self._checkbox_state(item)
        check.setChecked(checked)
        check.setEnabled(can_toggle)
        focus_type = self._focus_type
        focus_id = self._focus_id
        check.stateChanged.connect(
            lambda state, et=item.entity_type, eid=item.entity_id, ft=focus_type, fid=focus_id: self._on_relation_checked(
                et,
                eid,
                bool(state),
                focus_type=ft,
                focus_id=fid,
            )
        )
        top.addWidget(check, 0, Qt.AlignTop)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        title = QLabel(item.title)
        title.setWordWrap(True)
        title.setObjectName("stdCardTitle")
        title.setProperty("tone", "focus" if is_focus else "related" if is_related else "default")
        title_box.addWidget(title)

        provenance_badges = self._entity_provenance_badges(item)
        if provenance_badges:
            badges_row = QHBoxLayout()
            badges_row.setContentsMargins(0, 0, 0, 0)
            badges_row.setSpacing(6)
            for label, kind in provenance_badges:
                badge = StandardBadge(label)
                badge.set_kind(kind)
                badges_row.addWidget(badge, 0)
            badges_row.addStretch(1)
            title_box.addLayout(badges_row)

        subtitle = QLabel(item.subtitle)
        subtitle.setObjectName("pipelineMetaLabel")
        subtitle.setWordWrap(True)
        title_box.addWidget(subtitle)

        if item.status:
            status = QLabel(self._fmt("status.label", "Status: {status}", status=item.status))
            status.setObjectName("pipelineMetaLabel")
            title_box.addWidget(status)

        if not can_toggle and self._focus_type and item.entity_type != self._focus_type:
            hint = QLabel(self._tr("relations.hint", "Relations are managed from compatible columns"))
            hint.setObjectName("pipelineMetaLabel")
            title_box.addWidget(hint)

        top.addLayout(title_box, 1)
        outer.addLayout(top)

        if item.entity_type != "meeting":
            actions = QHBoxLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(6)

            rename_btn = self._make_action_button(self._tr("button.rename", "Rename"))
            rename_btn.clicked.connect(lambda *_a, it=item: self._rename_entity(it))
            actions.addWidget(rename_btn, 0)

            if item.entity_type == "task":
                status_btn = self._make_action_button(
                    self._tr("button.reopen", "Reopen") if item.status == "done" else self._tr("button.done", "Done")
                )
                status_btn.clicked.connect(lambda *_a, it=item: self._toggle_task_status(it))
                actions.addWidget(status_btn, 0)
            elif item.entity_type == "project":
                edit_btn = self._make_action_button(self._tr("button.edit", "Edit"))
                edit_btn.clicked.connect(lambda *_a, it=item: self._edit_project(it))
                actions.addWidget(edit_btn, 0)

                status_btn = self._make_action_button(
                    self._tr("button.activate", "Activate")
                    if item.status == "archived"
                    else self._tr("button.archive", "Archive")
                )
                status_btn.clicked.connect(lambda *_a, it=item: self._toggle_project_status(it))
                actions.addWidget(status_btn, 0)
            elif item.entity_type == "agenda":
                edit_btn = self._make_action_button(self._tr("button.edit", "Edit"))
                edit_btn.clicked.connect(lambda *_a, it=item: self._edit_agenda(it))
                actions.addWidget(edit_btn, 0)

                status_btn = self._make_action_button(
                    self._tr("button.activate", "Activate")
                    if item.status == "archived"
                    else self._tr("button.archive", "Archive")
                )
                status_btn.clicked.connect(lambda *_a, it=item: self._toggle_agenda_status(it))
                actions.addWidget(status_btn, 0)

            delete_btn = self._make_action_button(self._tr("button.delete", "Delete"))
            delete_btn.clicked.connect(lambda *_a, it=item: self._delete_entity(it))
            actions.addWidget(delete_btn, 0)
            actions.addStretch(1)
            outer.addLayout(actions)

        return card

    @staticmethod
    def _make_action_button(label: str) -> QToolButton:
        btn = StandardActionButton(str(label or ""))
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    def _refresh_focus_label(self) -> None:
        if not self._focus_type or not self._focus_id:
            self._focus_label.setText(self._tr("focus.none", "Context: not selected. Click any tile to focus relations."))
            self._cleanup_focus_button.setEnabled(False)
            return
        title = self._title_for(self._focus_type, self._focus_id)
        self._focus_label.setText(
            self._fmt("focus.selected", "Context: {type} -> {title}", type=self._focus_type, title=title)
        )
        self._cleanup_focus_button.setEnabled(self._focus_type == "meeting" and bool(self._focus_id))

    def _on_card_clicked(self, entity_type: str, entity_id: str) -> None:
        et = str(entity_type or "").strip()
        eid = str(entity_id or "").strip()
        if not et or not eid:
            return
        if self._focus_type == et and self._focus_id == eid:
            self._focus_type = ""
            self._focus_id = ""
        else:
            self._focus_type = et
            self._focus_id = eid
        self._refresh_focus_label()
        self._render_all_columns()
        self._render_suggestions()

    def _on_search_changed(self, entity_type: str, text: str) -> None:
        self._search[entity_type] = str(text or "")
        self._render_column(entity_type)

    def _clear_focus(self) -> None:
        self._focus_type = ""
        self._focus_id = ""
        self._refresh_focus_label()
        self._render_suggestions()
        self._render_all_columns()

    def _render_suggestions(self) -> None:
        while self._suggestions_list.count():
            item = self._suggestions_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        items = self._filtered_suggestions_for_view(
            self._suggestions,
            focus_type=self._focus_type,
            focus_id=self._focus_id,
        )
        self._approve_shown_button.setEnabled(bool(items))
        self._merge_shown_button.setEnabled(bool(items))
        self._hide_shown_button.setEnabled(bool(items))
        if not items:
            self._suggestions_meta.setText(self._tr("suggestions.empty", "No pending suggestions."))
            placeholder = QLabel(
                self._tr(
                    "suggestions.placeholder",
                    "Run Management to collect suggestions or focus a meeting to narrow the queue.",
                )
            )
            placeholder.setObjectName("pipelineMetaLabel")
            placeholder.setWordWrap(True)
            self._suggestions_list.addWidget(placeholder)
            self._suggestions_list.addStretch(1)
            return
        self._suggestions_meta.setText(
            self._fmt("suggestions.count", "Pending suggestions: {count}", count=len(items))
        )
        for row in items:
            self._suggestions_list.addWidget(self._build_suggestion_card(row))
        self._suggestions_list.addStretch(1)

    def _build_suggestion_card(self, row: dict) -> QWidget:
        card = StandardCard()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(6)

        kind = str(row.get("kind", "") or "").strip() or "item"
        title = str(row.get("title", "") or "").strip() or self._tr("suggestions.untitled", "Untitled suggestion")
        confidence = float(row.get("confidence", 0.0) or 0.0)
        meeting_id = str(row.get("source_meeting_id", "") or "").strip()
        meeting_title = self._title_for("meeting", meeting_id) if meeting_id else ""
        reasoning = str(row.get("reasoning_short", "") or "").strip()
        description = str(row.get("description", "") or "").strip()
        evidence = row.get("evidence", [])
        evidence_text = ""
        if isinstance(evidence, list):
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "") or "").strip()
                if text:
                    evidence_text = text
                    break

        header = QHBoxLayout()
        name = QLabel(title)
        name.setObjectName("pageTitle")
        name.setWordWrap(True)
        header.addWidget(name, 1)
        badge = StandardBadge(f"{kind} {confidence:.2f}")
        header.addWidget(badge, 0)
        outer.addLayout(header)

        meta_parts = []
        if meeting_title:
            meta_parts.append(
                self._fmt("suggestions.meeting", "Meeting: {value}", value=meeting_title)
            )
        if reasoning:
            meta_parts.append(reasoning)
        if meta_parts:
            meta = QLabel(" | ".join(meta_parts))
            meta.setObjectName("pipelineMetaLabel")
            meta.setWordWrap(True)
            outer.addWidget(meta)
        if description:
            desc = QLabel(description)
            desc.setWordWrap(True)
            outer.addWidget(desc)
        if evidence_text:
            ev = QLabel(self._fmt("suggestions.evidence", "Evidence: {value}", value=evidence_text))
            ev.setObjectName("pipelineMetaLabel")
            ev.setWordWrap(True)
            outer.addWidget(ev)

        suggestion_id = str(row.get("id", "") or "").strip()
        actions = QHBoxLayout()
        approve_btn = self._make_action_button(self._tr("button.approve", "Approve"))
        approve_btn.clicked.connect(lambda *_a, sid=suggestion_id: self._approve_suggestion(sid))
        actions.addWidget(approve_btn, 0)

        reject_btn = self._make_action_button(self._tr("button.reject", "Reject"))
        reject_btn.clicked.connect(lambda *_a, sid=suggestion_id: self._set_suggestion_state(sid, "rejected"))
        actions.addWidget(reject_btn, 0)

        merge_btn = self._make_action_button(self._tr("button.merge", "Merge"))
        merge_btn.clicked.connect(lambda *_a, data=dict(row): self._merge_suggestion(data))
        actions.addWidget(merge_btn, 0)

        hide_btn = self._make_action_button(self._tr("button.hide", "Hide"))
        hide_btn.clicked.connect(lambda *_a, sid=suggestion_id: self._set_suggestion_state(sid, "hidden"))
        actions.addWidget(hide_btn, 0)

        if meeting_id:
            focus_btn = self._make_action_button(self._tr("button.focus_meeting", "Focus meeting"))
            focus_btn.clicked.connect(lambda *_a, mid=meeting_id: self._on_card_clicked("meeting", mid))
            actions.addWidget(focus_btn, 0)
            open_btn = self._make_action_button(self._tr("button.open_evidence", "Open evidence"))
            open_btn.clicked.connect(lambda *_a, data=dict(row): self._open_suggestion_evidence(data))
            actions.addWidget(open_btn, 0)
        clean_source_btn = self._make_action_button(self._tr("button.clean_source", "Clean source"))
        clean_source_btn.clicked.connect(lambda *_a, data=dict(row): self._cleanup_suggestion_source(data))
        actions.addWidget(clean_source_btn, 0)
        actions.addStretch(1)
        outer.addLayout(actions)
        return card

    @staticmethod
    def _filtered_suggestions_for_view(
        suggestions: list[dict] | tuple[dict, ...] | None,
        *,
        focus_type: str = "",
        focus_id: str = "",
    ) -> list[dict]:
        items = [dict(row) for row in list(suggestions or []) if isinstance(row, dict)]
        meeting_id = str(focus_id or "").strip() if str(focus_type or "").strip() == "meeting" else ""
        if not meeting_id:
            return items
        return [
            row
            for row in items
            if str(row.get("source_meeting_id", "") or "").strip() == meeting_id
        ]

    def _shown_suggestions(self) -> list[dict]:
        return self._filtered_suggestions_for_view(
            self._suggestions,
            focus_type=self._focus_type,
            focus_id=self._focus_id,
        )

    def _approve_shown_suggestions(self) -> None:
        shown = self._shown_suggestions()
        if not shown:
            return
        reply = QMessageBox.question(
            self,
            self._tr("suggestions.bulk_approve.title", "Approve shown suggestions?"),
            self._fmt(
                "suggestions.bulk_approve.message",
                "Approve all currently shown suggestions?\n\nCount: {count}",
                count=len(shown),
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        approved = 0
        failed = 0
        store = ManagementStore(self._app_root)
        try:
            for row in shown:
                suggestion_id = str(row.get("id", "") or "").strip()
                if not suggestion_id:
                    continue
                result = store.approve_suggestion(suggestion_id)
                if isinstance(result, dict):
                    approved += 1
                else:
                    failed += 1
        finally:
            store.close()
        self.reload()
        if failed > 0:
            QMessageBox.warning(
                self,
                self._tr("suggestions.bulk_approve.done_with_failures.title", "Some suggestions were not approved"),
                self._fmt(
                    "suggestions.bulk_approve.done_with_failures.message",
                    "Approved: {approved}\nFailed: {failed}",
                    approved=approved,
                    failed=failed,
                ),
            )
            return
        QMessageBox.information(
            self,
            self._tr("suggestions.bulk_approve.done.title", "Suggestions approved"),
            self._fmt(
                "suggestions.bulk_approve.done.message",
                "Approved suggestions: {count}",
                count=approved,
            ),
        )

    def _merge_shown_obvious_suggestions(self) -> None:
        shown = self._shown_suggestions()
        candidates: list[tuple[str, str]] = []
        for row in shown:
            suggestion_id = str(row.get("id", "") or "").strip()
            kind = str(row.get("kind", "") or "").strip().lower()
            if not suggestion_id or kind not in {"task", "project", "agenda"}:
                continue
            target_id = self._obvious_merge_target_id(kind, row, self._rows.get(kind, {}))
            if target_id:
                candidates.append((suggestion_id, target_id))
        if not candidates:
            QMessageBox.information(
                self,
                self._tr("suggestions.bulk_merge_empty.title", "No obvious merges"),
                self._tr(
                    "suggestions.bulk_merge_empty.message",
                    "No shown suggestions have a single obvious existing match.",
                ),
            )
            return
        reply = QMessageBox.question(
            self,
            self._tr("suggestions.bulk_merge.title", "Merge obvious suggestions?"),
            self._fmt(
                "suggestions.bulk_merge.message",
                "Merge shown suggestions that have a single obvious existing match?\n\nCandidates: {count}",
                count=len(candidates),
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        merged = 0
        failed = 0
        store = ManagementStore(self._app_root)
        try:
            for suggestion_id, target_id in candidates:
                result = store.approve_suggestion_into_existing(suggestion_id, entity_id=target_id)
                if isinstance(result, dict):
                    merged += 1
                else:
                    failed += 1
        finally:
            store.close()
        self.reload()
        if failed > 0:
            QMessageBox.warning(
                self,
                self._tr("suggestions.bulk_merge.done_with_failures.title", "Some suggestions were not merged"),
                self._fmt(
                    "suggestions.bulk_merge.done_with_failures.message",
                    "Merged: {merged}\nFailed: {failed}",
                    merged=merged,
                    failed=failed,
                ),
            )
            return
        QMessageBox.information(
            self,
            self._tr("suggestions.bulk_merge.done.title", "Suggestions merged"),
            self._fmt(
                "suggestions.bulk_merge.done.message",
                "Merged suggestions: {count}",
                count=merged,
            ),
        )

    def _hide_shown_suggestions(self) -> None:
        shown = self._shown_suggestions()
        if not shown:
            return
        reply = QMessageBox.question(
            self,
            self._tr("suggestions.bulk_hide.title", "Hide shown suggestions?"),
            self._fmt(
                "suggestions.bulk_hide.message",
                "Hide all currently shown suggestions?\n\nCount: {count}",
                count=len(shown),
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        updated = 0
        store = ManagementStore(self._app_root)
        try:
            for row in shown:
                suggestion_id = str(row.get("id", "") or "").strip()
                if not suggestion_id:
                    continue
                store.set_suggestion_state(suggestion_id, state="hidden")
                updated += 1
        finally:
            store.close()
        self.reload()
        QMessageBox.information(
            self,
            self._tr("suggestions.bulk_hide.done.title", "Suggestions hidden"),
            self._fmt(
                "suggestions.bulk_hide.done.message",
                "Hidden suggestions: {count}",
                count=updated,
            ),
        )

    def _cleanup_focused_meeting_management(self) -> None:
        meeting_id = self._focus_id if self._focus_type == "meeting" else ""
        if not meeting_id:
            return
        if self._management_cleanup_controller().run_meeting_cleanup(meeting_id) is None:
            return
        self.reload()

    def _cleanup_suggestion_source(self, row: dict) -> None:
        suggestion_id = str(row.get("id", "") or "").strip()
        meeting_id = str(row.get("source_meeting_id", "") or "").strip()
        source_kind = str(row.get("source_kind", "") or "").strip()
        source_alias = str(row.get("source_alias", "") or "").strip()
        if not meeting_id or not source_kind:
            return
        if self._management_cleanup_controller().run_artifact_source_cleanup(
            meeting_id=meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            suggestion_id=suggestion_id,
        ) is None:
            return
        self.reload()

    def _management_cleanup_controller(self) -> ManagementCleanupController:
        return ManagementCleanupController(
            app_root=self._app_root,
            parent=self,
            tr=self._tr,
            fmt=self._fmt,
        )

    def _can_toggle_checkbox(
        self,
        entity_type: str,
        *,
        focus_type: str = "",
        focus_id: str = "",
    ) -> bool:
        left_type = str(focus_type or self._focus_type).strip()
        left_id = str(focus_id or self._focus_id).strip()
        if not left_type or not left_id:
            return False
        if entity_type == left_type:
            return False
        return self._is_adjacent(left_type, entity_type)

    def _checkbox_state(self, item: EntityItem) -> bool:
        if not self._can_toggle_checkbox(item.entity_type):
            return False
        return self._is_related(
            left_type=self._focus_type,
            left_id=self._focus_id,
            right_type=item.entity_type,
            right_id=item.entity_id,
        )

    def _on_relation_checked(
        self,
        entity_type: str,
        entity_id: str,
        checked: bool,
        *,
        focus_type: str = "",
        focus_id: str = "",
    ) -> None:
        left_type = str(focus_type or self._focus_type).strip()
        left_id = str(focus_id or self._focus_id).strip()
        if not self._can_toggle_checkbox(entity_type, focus_type=left_type, focus_id=left_id):
            return
        self._toggle_relation(
            left_type=left_type,
            left_id=left_id,
            right_type=entity_type,
            right_id=entity_id,
            checked=checked,
        )
        self.reload()

    def _toggle_relation(
        self,
        *,
        left_type: str,
        left_id: str,
        right_type: str,
        right_id: str,
        checked: bool,
    ) -> None:
        store = ManagementStore(self._app_root)
        try:
            pair = frozenset({str(left_type or "").strip().lower(), str(right_type or "").strip().lower()})
            allowed_pairs = {
                frozenset({"meeting", "agenda"}),
                frozenset({"meeting", "project"}),
                frozenset({"meeting", "task"}),
                frozenset({"agenda", "project"}),
                frozenset({"agenda", "task"}),
                frozenset({"project", "task"}),
            }
            if pair not in allowed_pairs:
                return
            if checked:
                store.link_entities(left_type=left_type, left_id=left_id, right_type=right_type, right_id=right_id)
            else:
                store.unlink_entities(left_type=left_type, left_id=left_id, right_type=right_type, right_id=right_id)
        finally:
            store.close()

    def _is_adjacent(self, left_type: str, right_type: str) -> bool:
        left = str(left_type or "").strip().lower()
        right = str(right_type or "").strip().lower()
        return right in set(self._ADJACENT.get(left, set()))

    def _is_related(self, *, left_type: str, left_id: str, right_type: str, right_id: str) -> bool:
        lt = str(left_type or "").strip().lower()
        li = str(left_id or "").strip()
        rt = str(right_type or "").strip().lower()
        ri = str(right_id or "").strip()
        if not lt or not li or not rt or not ri:
            return False

        pair = {lt, rt}
        if pair == {"meeting", "agenda"}:
            if lt == "meeting":
                agenda = self._rows.get("agenda", {}).get(ri, {})
                return li in {str(m) for m in agenda.get("meetings", []) or []}
            agenda = self._rows.get("agenda", {}).get(li, {})
            return ri in {str(m) for m in agenda.get("meetings", []) or []}

        if pair == {"meeting", "project"}:
            if lt == "meeting":
                project = self._rows.get("project", {}).get(ri, {})
                return li in {str(m) for m in project.get("meetings", []) or []}
            project = self._rows.get("project", {}).get(li, {})
            return ri in {str(m) for m in project.get("meetings", []) or []}

        if pair == {"meeting", "task"}:
            if lt == "meeting":
                task = self._rows.get("task", {}).get(ri, {})
                return li in {str(m) for m in task.get("meetings", []) or []}
            task = self._rows.get("task", {}).get(li, {})
            return ri in {str(m) for m in task.get("meetings", []) or []}

        if pair == {"agenda", "project"}:
            if lt == "agenda":
                agenda = self._rows.get("agenda", {}).get(li, {})
                return ri in {str(p) for p in agenda.get("projects", []) or []}
            agenda = self._rows.get("agenda", {}).get(ri, {})
            return li in {str(p) for p in agenda.get("projects", []) or []}

        if pair == {"agenda", "task"}:
            if lt == "agenda":
                agenda = self._rows.get("agenda", {}).get(li, {})
                return ri in {str(t) for t in agenda.get("tasks", []) or []}
            agenda = self._rows.get("agenda", {}).get(ri, {})
            return li in {str(t) for t in agenda.get("tasks", []) or []}

        if pair == {"project", "task"}:
            if lt == "project":
                project = self._rows.get("project", {}).get(li, {})
                return ri in {str(t) for t in project.get("tasks", []) or []}
            project = self._rows.get("project", {}).get(ri, {})
            return li in {str(t) for t in project.get("tasks", []) or []}

        return False

    def _title_for(self, entity_type: str, entity_id: str) -> str:
        et = str(entity_type or "").strip().lower()
        eid = str(entity_id or "").strip()
        if not et or not eid:
            return ""
        for item in self._items.get(et, []):
            if item.entity_id == eid:
                return item.title
        return eid

    def _on_add_entity(self, entity_type: str) -> None:
        store = ManagementStore(self._app_root)
        try:
            if entity_type == "task":
                title, ok = QInputDialog.getText(
                    self,
                    self._tr("dialog.new_task_title", "New Task"),
                    self._tr("dialog.new_task_prompt", "Task title:"),
                )
                if ok and str(title or "").strip():
                    preferred_project = ""
                    if self._focus_type == "project" and self._focus_id:
                        preferred_project = self._focus_id
                    store.create_task(title=str(title), project_id=preferred_project or None)
            elif entity_type == "project":
                name, ok = QInputDialog.getText(
                    self,
                    self._tr("dialog.new_project_title", "New Project"),
                    self._tr("dialog.new_project_prompt", "Project name:"),
                )
                if ok and str(name or "").strip():
                    store.create_project(name=str(name), description="")
            elif entity_type == "agenda":
                title, ok = QInputDialog.getText(
                    self,
                    self._tr("dialog.new_agenda_title", "New Agenda"),
                    self._tr("dialog.new_agenda_prompt", "Agenda title:"),
                )
                if ok and str(title or "").strip():
                    text, ok_text = QInputDialog.getMultiLineText(
                        self,
                        self._tr("dialog.agenda_text_title", "Agenda Text"),
                        self._tr("dialog.agenda_text_prompt", "Agenda details:"),
                    )
                    if ok_text:
                        store.create_agenda(title=str(title), text=str(text or ""))
        finally:
            store.close()
        self.reload()

    def _approve_suggestion(self, suggestion_id: str) -> None:
        sid = str(suggestion_id or "").strip()
        if not sid:
            return
        store = ManagementStore(self._app_root)
        try:
            result = store.approve_suggestion(sid)
        finally:
            store.close()
        if not isinstance(result, dict):
            QMessageBox.warning(
                self,
                self._tr("suggestions.approve_failed_title", "Suggestion approval failed"),
                self._tr("suggestions.approve_failed_message", "Unable to approve this suggestion."),
            )
            return
        self.reload()

    def _merge_suggestion(self, row: dict) -> None:
        suggestion_id = str(row.get("id", "") or "").strip()
        kind = str(row.get("kind", "") or "").strip().lower()
        if not suggestion_id or kind not in {"task", "project", "agenda"}:
            return
        choices = self._merge_target_choices(kind, suggestion=row)
        if not choices:
            QMessageBox.information(
                self,
                self._tr("suggestions.merge_empty_title", "No merge targets"),
                self._tr(
                    "suggestions.merge_empty_message",
                    "No existing approved entities of this type were found.",
                ),
            )
            return
        labels = [label for label, _entity_id in choices]
        picked, ok = QInputDialog.getItem(
            self,
            self._tr("suggestions.merge_title", "Merge suggestion"),
            self._tr("suggestions.merge_prompt", "Choose an existing entity:"),
            labels,
            0,
            False,
        )
        if not ok:
            return
        picked_text = str(picked or "").strip()
        target_id = next((entity_id for label, entity_id in choices if label == picked_text), "")
        if not target_id:
            return
        store = ManagementStore(self._app_root)
        try:
            result = store.approve_suggestion_into_existing(suggestion_id, entity_id=target_id)
        finally:
            store.close()
        if not isinstance(result, dict):
            QMessageBox.warning(
                self,
                self._tr("suggestions.merge_failed_title", "Suggestion merge failed"),
                self._tr("suggestions.merge_failed_message", "Unable to merge this suggestion."),
            )
            return
        self.reload()

    def _set_suggestion_state(self, suggestion_id: str, state: str) -> None:
        sid = str(suggestion_id or "").strip()
        if not sid:
            return
        store = ManagementStore(self._app_root)
        try:
            store.set_suggestion_state(sid, state=str(state or "").strip().lower())
        finally:
            store.close()
        self.reload()

    def _merge_target_choices(self, entity_type: str, *, suggestion: dict) -> list[tuple[str, str]]:
        rows = self._rows.get(str(entity_type or "").strip().lower(), {})
        if not isinstance(rows, dict):
            return []
        suggestion_title = str(suggestion.get("title", "") or "").strip()
        suggestion_norm = str(suggestion.get("normalized_key", "") or "").strip()
        if not suggestion_norm:
            suggestion_norm = " ".join(suggestion_title.lower().split())
        scored: list[tuple[float, str, str]] = []
        for entity_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            if entity_type == "task":
                title = str(row.get("title", "") or "").strip()
            elif entity_type == "project":
                title = str(row.get("name", "") or "").strip()
            else:
                title = str(row.get("title", "") or "").strip()
            if not title:
                continue
            norm = " ".join(title.lower().split())
            score = SequenceMatcher(None, suggestion_norm, norm).ratio() if suggestion_norm else 0.0
            label = f"{title} [{score:.2f}]"
            scored.append((score, label, str(entity_id or "").strip()))
        scored.sort(key=lambda item: (-item[0], item[1].lower()))
        return [(label, entity_id) for _score, label, entity_id in scored[:24]]

    @staticmethod
    def _obvious_merge_target_id(entity_type: str, suggestion: dict, rows: dict[str, dict] | None) -> str:
        kind = str(entity_type or "").strip().lower()
        if kind not in {"task", "project", "agenda"} or not isinstance(rows, dict) or not rows:
            return ""
        suggestion_title = str(suggestion.get("title", "") or "").strip()
        suggestion_norm = str(suggestion.get("normalized_key", "") or "").strip()
        if not suggestion_norm:
            suggestion_norm = " ".join(suggestion_title.lower().split())
        if not suggestion_norm:
            return ""
        exact_ids: list[str] = []
        scored: list[tuple[float, str]] = []
        for entity_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            if kind == "project":
                title = str(row.get("name", "") or "").strip()
            else:
                title = str(row.get("title", "") or "").strip()
            if not title:
                continue
            norm = " ".join(title.lower().split())
            if not norm:
                continue
            entity_id_value = str(entity_id or "").strip()
            if norm == suggestion_norm:
                exact_ids.append(entity_id_value)
                continue
            score = SequenceMatcher(None, suggestion_norm, norm).ratio()
            scored.append((score, entity_id_value))
        if len(exact_ids) == 1:
            return exact_ids[0]
        if len(exact_ids) > 1:
            return ""
        if not scored:
            return ""
        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score, best_id = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= 0.985 and (best_score - second_score) >= 0.03:
            return best_id
        return ""

    def _open_suggestion_evidence(self, row: dict) -> None:
        meeting_id = str(row.get("source_meeting_id", "") or "").strip()
        source_kind = str(row.get("source_kind", "") or "").strip().lower()
        source_alias = str(row.get("source_alias", "") or "").strip()
        evidence = row.get("evidence", [])
        evidence_text = ""
        start_ms = -1
        segment_index = -1
        if isinstance(evidence, list):
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                source_kind_value = str(item.get("source", "") or "").strip().lower()
                source_alias_value = str(item.get("alias", "") or "").strip()
                if source_kind_value:
                    source_kind = source_kind_value
                if source_alias_value:
                    source_alias = source_alias_value
                text = str(item.get("text", "") or "").strip()
                if text and not evidence_text:
                    evidence_text = text
                try:
                    if int(item.get("start_ms", -1)) >= 0:
                        start_ms = int(item.get("start_ms", -1))
                except Exception:
                    start_ms = start_ms
                try:
                    if int(item.get("segment_index", -1)) >= 0:
                        segment_index = int(item.get("segment_index", -1))
                except Exception:
                    segment_index = segment_index
        if not meeting_id:
            return
        payload = {
            "meeting_id": meeting_id,
            "source_kind": source_kind,
            "source_alias": source_alias,
            "query": evidence_text,
            "segment_index": segment_index,
            "start_ms": start_ms,
        }
        self.evidenceOpenRequested.emit(payload)

    def _rename_entity(self, item: EntityItem) -> None:
        text, ok = QInputDialog.getText(
            self,
            self._tr("dialog.rename_title", "Rename"),
            self._tr("dialog.rename_prompt", "New name:"),
            text=item.title,
        )
        if not ok:
            return
        value = str(text or "").strip()
        if not value:
            return
        store = ManagementStore(self._app_root)
        try:
            if item.entity_type == "task":
                store.rename_task(item.entity_id, title=value)
            elif item.entity_type == "project":
                store.rename_project(item.entity_id, name=value)
            elif item.entity_type == "agenda":
                store.rename_agenda(item.entity_id, title=value)
        finally:
            store.close()
        self.reload()

    def _edit_project(self, item: EntityItem) -> None:
        current = str(self._rows.get("project", {}).get(item.entity_id, {}).get("description", "") or "")
        text, ok = QInputDialog.getMultiLineText(
            self,
            self._tr("dialog.project_description_title", "Project Description"),
            self._tr("dialog.project_description_prompt", "Description:"),
            current,
        )
        if not ok:
            return
        store = ManagementStore(self._app_root)
        try:
            store.update_project_description(item.entity_id, description=str(text or ""))
        finally:
            store.close()
        self.reload()

    def _edit_agenda(self, item: EntityItem) -> None:
        current = str(self._rows.get("agenda", {}).get(item.entity_id, {}).get("text", "") or "")
        text, ok = QInputDialog.getMultiLineText(
            self,
            self._tr("dialog.agenda_text_title", "Agenda Text"),
            self._tr("dialog.agenda_text_prompt", "Agenda details:"),
            current,
        )
        if not ok:
            return
        store = ManagementStore(self._app_root)
        try:
            store.update_agenda_text(item.entity_id, text=str(text or ""))
        finally:
            store.close()
        self.reload()

    def _toggle_task_status(self, item: EntityItem) -> None:
        next_status = "open" if item.status == "done" else "done"
        store = ManagementStore(self._app_root)
        try:
            store.set_task_status(item.entity_id, status=next_status)
        finally:
            store.close()
        self.reload()

    def _toggle_project_status(self, item: EntityItem) -> None:
        next_status = "active" if item.status == "archived" else "archived"
        store = ManagementStore(self._app_root)
        try:
            store.set_project_status(item.entity_id, status=next_status)
        finally:
            store.close()
        self.reload()

    def _toggle_agenda_status(self, item: EntityItem) -> None:
        next_status = "active" if item.status == "archived" else "archived"
        store = ManagementStore(self._app_root)
        try:
            store.set_agenda_status(item.entity_id, status=next_status)
        finally:
            store.close()
        self.reload()

    def _delete_entity(self, item: EntityItem) -> None:
        question = self._fmt(
            "dialog.delete_question",
            "Delete {entity_type} '{title}'?",
            entity_type=item.entity_type,
            title=item.title,
        )
        if QMessageBox.question(
            self,
            self._tr("dialog.delete_title", "Confirm Delete"),
            question,
        ) != QMessageBox.Yes:
            return
        store = ManagementStore(self._app_root)
        try:
            if item.entity_type == "task":
                store.delete_task(item.entity_id)
            elif item.entity_type == "project":
                store.delete_project(item.entity_id)
            elif item.entity_type == "agenda":
                store.delete_agenda(item.entity_id)
        finally:
            store.close()

        if self._focus_type == item.entity_type and self._focus_id == item.entity_id:
            self._focus_type = ""
            self._focus_id = ""
        self.reload()
