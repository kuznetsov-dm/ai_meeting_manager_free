from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aimn.ui.tabs.contracts import PipelineEvent, StageViewModel


class PreviewTab(QWidget):
    def __init__(self, artifact_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = artifact_service
        self._stage: Optional[StageViewModel] = None
        self._active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._status = QLabel("Stage outputs will appear after a run.")
        layout.addWidget(self._status)

        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self._list, 1)

        actions = QHBoxLayout()
        self._open_btn = QPushButton("Open")
        self._copy_btn = QPushButton("Copy Path")
        actions.addWidget(self._open_btn)
        actions.addWidget(self._copy_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        layout.addWidget(self._preview, 2)

        self._open_btn.clicked.connect(self._open_selected)
        self._copy_btn.clicked.connect(self._copy_selected)

    def set_stage(self, stage: StageViewModel) -> None:
        self._stage = stage
        if self._active:
            self._render_list()

    def on_activated(self) -> None:
        self._active = True
        self._render_list()

    def on_deactivated(self) -> None:
        self._active = False

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        if not self._stage or event.stage_id != self._stage.stage_id:
            return
        if event.event_type in {"artifact_written", "stage_finished"}:
            self._render_list()

    def _render_list(self) -> None:
        self._list.clear()
        self._preview.clear()
        stage = self._stage
        if not stage:
            return
        artifacts = stage.artifacts or []
        if not artifacts:
            self._status.setText("No artifacts yet for this stage.")
            return
        self._status.setText(f"Artifacts: {len(artifacts)}")
        for entry in artifacts:
            relpath = str(entry.get("relpath", ""))
            label = entry.get("label") or relpath
            item = QListWidgetItem(str(label))
            item.setData(Qt.UserRole, entry)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _selected_relpath(self) -> str:
        items = self._list.selectedItems()
        if not items:
            return ""
        entry = items[0].data(Qt.UserRole) or {}
        return str(entry.get("relpath", ""))

    def _load_selected(self) -> None:
        relpath = self._selected_relpath()
        if not relpath:
            return
        self._preview.setPlainText(self._service.read_artifact_text(relpath))

    def _open_selected(self) -> None:
        relpath = self._selected_relpath()
        if relpath:
            self._service.open_artifact(relpath)

    def _copy_selected(self) -> None:
        relpath = self._selected_relpath()
        if not relpath:
            return
        self._preview.setPlainText(relpath)
