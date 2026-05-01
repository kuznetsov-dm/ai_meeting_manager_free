from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from aimn.ui.services.artifact_service import ArtifactService, ArtifactItem


class FileSelectionPanel(QWidget):
    filesChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("Files"))
        header.addStretch()
        layout.addLayout(header)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        actions = QHBoxLayout()
        self._add_btn = QPushButton("Add Files")
        self._remove_btn = QPushButton("Remove")
        self._clear_btn = QPushButton("Clear")
        self._add_btn.clicked.connect(self._pick_files)
        self._remove_btn.clicked.connect(self._remove_selected)
        self._clear_btn.clicked.connect(self.clear)
        actions.addWidget(self._add_btn)
        actions.addWidget(self._remove_btn)
        actions.addWidget(self._clear_btn)
        actions.addStretch()
        layout.addLayout(actions)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(420, 240)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, 160)

    def files(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def set_files(self, paths: list[str]) -> None:
        self._list.clear()
        for path in paths:
            self._list.addItem(path)
        self.filesChanged.emit()

    def add_files(self, paths: list[str]) -> None:
        for path in paths:
            self._list.addItem(path)
        self.filesChanged.emit()

    def clear(self) -> None:
        self._list.clear()
        self.filesChanged.emit()

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            row = self._list.row(item)
            self._list.takeItem(row)
        self.filesChanged.emit()

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select files")
        if files:
            self.add_files(files)


class JobsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Jobs"))
        self._list = QListWidget()
        layout.addWidget(self._list, 1)
        self._items: Dict[str, QListWidgetItem] = {}

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(520, 220)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, 140)

    def add_job_entry(self, job_id: str, label: str, *, status: str = "queued") -> None:
        item = QListWidgetItem(f"{status}: {label}")
        item.setData(Qt.UserRole, job_id)
        self._list.addItem(item)
        self._items[job_id] = item
        self._style_item(item, status)

    def update_job_status(self, job_id: str, status: str) -> None:
        item = self._items.get(job_id)
        if not item:
            return
        text = item.text()
        label = text.split(":", 1)[1].strip() if ":" in text else text
        item.setText(f"{status}: {label}")
        self._style_item(item, status)

    @staticmethod
    def _style_item(item: QListWidgetItem, status: str) -> None:
        palette = {
            "queued": "#9CA3AF",
            "running": "#2563EB",
            "finished": "#16A34A",
            "failed": "#DC2626",
        }
        color = palette.get(status, "#6B7280")
        item.setForeground(color)


class ArtifactsPanel(QWidget):
    meetingSelected = Signal(object)
    retryFailedRequested = Signal(object)

    def __init__(self, service: ArtifactService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._current_meeting = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._history = _ListGroup("History")
        self._history.list.itemSelectionChanged.connect(self._on_history_selected)
        layout.addWidget(self._history)

        self._details = _TextGroup("Meeting Details")
        layout.addWidget(self._details)

        self._search = _SearchGroup()
        self._search.searchRequested.connect(self._run_search)
        self._search.list.itemSelectionChanged.connect(self._on_search_selected)
        layout.addWidget(self._search)

        self._artifacts = _ArtifactsGroup()
        self._artifacts.list.itemSelectionChanged.connect(self._on_artifact_selected)
        self._artifacts.openClicked.connect(self._open_artifact)
        self._artifacts.copyClicked.connect(self._copy_artifact)
        layout.addWidget(self._artifacts, 1)

        self._lineage = _LineageGroup()
        self._lineage.list.itemSelectionChanged.connect(self._on_lineage_selected)
        self._lineage.pinTranscript.connect(self._pin_transcript)
        self._lineage.pinSegments.connect(self._pin_segments)
        self._lineage.retryFailed.connect(self._retry_failed)
        layout.addWidget(self._lineage)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(440, 600)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 260)

    def load_history(self) -> None:
        self._history.list.clear()
        for meeting in self._service.list_meetings():
            item = QListWidgetItem(meeting.meeting_id)
            item.setData(Qt.UserRole, meeting.base_name)
            self._history.list.addItem(item)

    def add_history_entry(self, meeting_id: str, base_name: str) -> None:
        for i in range(self._history.list.count()):
            item = self._history.list.item(i)
            if item.data(Qt.UserRole) == base_name:
                item.setText(meeting_id)
                return
        item = QListWidgetItem(meeting_id)
        item.setData(Qt.UserRole, base_name)
        self._history.list.addItem(item)

    def current_meeting(self):
        return self._current_meeting

    def set_density(self, density: str) -> None:
        if density == "collapsed":
            self._details.setVisible(False)
            self._search.setVisible(False)
            self._artifacts.setVisible(False)
            self._lineage.setVisible(False)
        elif density == "mini":
            self._details.setVisible(False)
            self._search.setVisible(False)
            self._lineage.setVisible(False)
            self._artifacts.setVisible(True)
        else:
            self._details.setVisible(True)
            self._search.setVisible(True)
            self._lineage.setVisible(True)
            self._artifacts.setVisible(True)
        self.setProperty("density", density)

    def get_density(self) -> str:
        return str(self.property("density") or "full")

    def _on_history_selected(self) -> None:
        items = self._history.list.selectedItems()
        if not items:
            return
        base_name = items[0].data(Qt.UserRole)
        if not base_name:
            return
        meeting = self._service.load_meeting(str(base_name))
        self._current_meeting = meeting
        self._render_meeting(meeting)
        self.meetingSelected.emit(meeting)

    def _render_meeting(self, meeting) -> None:
        details = [
            f"meeting_id: {meeting.meeting_id}",
            f"base_name: {meeting.base_name}",
            f"updated_at: {meeting.updated_at}",
        ]
        if meeting.source.items:
            details.append("inputs:")
            for item in meeting.source.items:
                details.append(f"- {item.input_filename} ({item.input_path})")
        run = meeting.pipeline_runs[-1] if meeting.pipeline_runs else None
        if run:
            details.append(f"last_run: {run.result}")
            if run.error:
                details.append(f"last_error: {run.error}")
        self._details.text.setPlainText("\n".join(details))

        self._artifacts.list.clear()
        for artifact in self._service.list_artifacts(meeting):
            label = _artifact_label(artifact)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, artifact)
            self._artifacts.list.addItem(item)

        self._lineage.list.clear()
        for alias, node in sorted(meeting.nodes.items()):
            item = QListWidgetItem(f"{alias} | {node.stage_id}")
            item.setData(Qt.UserRole, alias)
            self._lineage.list.addItem(item)

    def _run_search(self, query: str) -> None:
        self._search.list.clear()
        for hit in self._service.search(query):
            label = f"{hit.kind} [{hit.meeting_id}]"
            item = QListWidgetItem(label)
            item.setToolTip(hit.snippet)
            item.setData(Qt.UserRole, (hit.meeting_id, hit.alias, hit.kind))
            self._search.list.addItem(item)

    def _on_search_selected(self) -> None:
        items = self._search.list.selectedItems()
        if not items:
            return
        meeting_id, alias, kind = items[0].data(Qt.UserRole)
        content = self._service.get_search_text(str(meeting_id), str(alias), str(kind))
        self._artifacts.preview.setPlainText(content)

    def _on_artifact_selected(self) -> None:
        relpath = self._selected_artifact_relpath()
        if not relpath:
            return
        self._artifacts.preview.setPlainText(self._service.read_artifact_text(relpath))

    def _selected_artifact_relpath(self) -> str:
        items = self._artifacts.list.selectedItems()
        if not items:
            return ""
        artifact = items[0].data(Qt.UserRole)
        if isinstance(artifact, ArtifactItem):
            return artifact.relpath
        return ""

    def _open_artifact(self) -> None:
        relpath = self._selected_artifact_relpath()
        if relpath:
            self._service.open_artifact(relpath)

    def _copy_artifact(self) -> None:
        relpath = self._selected_artifact_relpath()
        if not relpath:
            return
        QApplication.clipboard().setText(relpath)
        self._artifacts.preview.setPlainText(relpath)

    def _on_lineage_selected(self) -> None:
        items = self._lineage.list.selectedItems()
        if not items or not self._current_meeting:
            return
        alias = items[0].data(Qt.UserRole)
        node = self._current_meeting.nodes.get(str(alias))
        if not node:
            return
        parts = [
            f"alias: {alias}",
            f"stage_id: {node.stage_id}",
            f"cacheable: {node.cacheable}",
            f"created_at: {node.created_at}",
            f"fingerprint: {node.fingerprint}",
        ]
        if node.inputs.parent_nodes:
            parts.append(f"parents: {', '.join(node.inputs.parent_nodes)}")
        if node.inputs.source_ids:
            parts.append(f"sources: {', '.join(node.inputs.source_ids)}")
        parts.append("artifacts:")
        for artifact in node.artifacts:
            parts.append(f"- {artifact.kind}: {artifact.path}")
        self._lineage.details.setPlainText("\n".join(parts))

    def _pin_transcript(self) -> None:
        if not self._current_meeting:
            return
        alias = self._lineage.selected_alias()
        node = self._current_meeting.nodes.get(alias)
        if not node:
            return
        transcript = next((item for item in node.artifacts if item.kind == "transcript"), None)
        if not transcript:
            self._lineage.details.setPlainText("Selected node has no transcript artifact.")
            return
        self._current_meeting.transcript_relpath = transcript.path
        self._service.save_meeting(self._current_meeting)
        self._lineage.details.setPlainText("Transcript pinned.")

    def _pin_segments(self) -> None:
        if not self._current_meeting:
            return
        alias = self._lineage.selected_alias()
        node = self._current_meeting.nodes.get(alias)
        if not node:
            return
        segments = next((item for item in node.artifacts if item.kind == "segments"), None)
        if not segments:
            self._lineage.details.setPlainText("Selected node has no segments artifact.")
            return
        self._current_meeting.segments_relpath = segments.path
        self._service.save_meeting(self._current_meeting)
        self._lineage.details.setPlainText("Segments pinned.")

    def _retry_failed(self) -> None:
        if not self._current_meeting:
            return
        self.retryFailedRequested.emit(self._current_meeting)


class LogsPanel(QWidget):
    def __init__(self, log_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = log_service
        self._active = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Logs"))
        self._view = QTextEdit()
        self._view.setObjectName("logView")
        self._view.setReadOnly(True)
        layout.addWidget(self._view, 1)
        self._service.log_appended.connect(self._append)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(520, 220)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, 140)

    def set_density(self, density: str) -> None:
        self.setProperty("density", density)
        self.setVisible(density != "collapsed")

    def get_density(self) -> str:
        return str(self.property("density") or "full")

    def _append(self, _stage_id: str, message: str) -> None:
        self._view.append(message)


class _ListGroup(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)


class _TextGroup(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)


class _SearchGroup(QGroupBox):
    searchRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__("Search")
        layout = QVBoxLayout(self)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Search artifacts...")
        self.input.returnPressed.connect(self._emit)
        layout.addWidget(self.input)
        self.list = QListWidget()
        layout.addWidget(self.list)

    def _emit(self) -> None:
        self.searchRequested.emit(self.input.text().strip())


class _ArtifactsGroup(QGroupBox):
    openClicked = Signal()
    copyClicked = Signal()

    def __init__(self) -> None:
        super().__init__("Artifacts")
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        self._open_btn = QPushButton("Open File")
        self._copy_btn = QPushButton("Copy Path")
        self._open_btn.clicked.connect(self.openClicked.emit)
        self._copy_btn.clicked.connect(self.copyClicked.emit)
        actions.addWidget(self._open_btn)
        actions.addWidget(self._copy_btn)
        actions.addStretch()
        layout.addLayout(actions)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)


class _LineageGroup(QGroupBox):
    pinTranscript = Signal()
    pinSegments = Signal()
    retryFailed = Signal()

    def __init__(self) -> None:
        super().__init__("Lineage")
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        actions = QHBoxLayout()
        self._pin_transcript = QPushButton("Use Transcript")
        self._pin_segments = QPushButton("Use Segments")
        self._retry_failed = QPushButton("Retry Failed Stages")
        self._pin_transcript.clicked.connect(self.pinTranscript.emit)
        self._pin_segments.clicked.connect(self.pinSegments.emit)
        self._retry_failed.clicked.connect(self.retryFailed.emit)
        actions.addWidget(self._pin_transcript)
        actions.addWidget(self._pin_segments)
        actions.addWidget(self._retry_failed)
        actions.addStretch()
        layout.addLayout(actions)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details)

    def selected_alias(self) -> Optional[str]:
        items = self.list.selectedItems()
        if not items:
            return None
        alias = items[0].data(Qt.UserRole)
        return str(alias) if alias else None


def _artifact_label(item: ArtifactItem) -> str:
    stage = item.stage_id or "stage"
    alias = item.alias or "default"
    kind = item.kind or "artifact"
    parts = [f"{stage}:{alias}", kind]
    if item.timestamp:
        parts.append(item.timestamp)
    else:
        parts.append(item.relpath)
    return " | ".join(parts)
