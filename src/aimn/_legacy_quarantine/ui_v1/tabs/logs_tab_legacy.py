from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QTextEdit, QVBoxLayout, QWidget

from aimn.ui.tabs.contracts import PipelineEvent, StageViewModel


class LogsTab(QWidget):
    showRawToggled = Signal(bool)

    def __init__(self, log_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = log_service
        self._stage: Optional[StageViewModel] = None
        self._active = False
        self._show_raw = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        self._raw_toggle = QCheckBox("Show raw logs")
        self._raw_toggle.toggled.connect(self._on_raw_toggled)
        controls.addWidget(self._raw_toggle)
        controls.addStretch()
        layout.addLayout(controls)

        self._view = QTextEdit()
        self._view.setObjectName("logView")
        self._view.setReadOnly(True)
        layout.addWidget(self._view, 1)

    def set_stage(self, stage: StageViewModel) -> None:
        self._stage = stage
        if self._active:
            self._render_logs()

    def on_activated(self) -> None:
        if not self._active:
            self._service.log_appended.connect(self._on_log_appended)
        self._active = True
        self._render_logs()

    def on_deactivated(self) -> None:
        if self._active:
            try:
                self._service.log_appended.disconnect(self._on_log_appended)
            except Exception:
                pass
        self._active = False

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        return

    def _render_logs(self) -> None:
        if not self._stage:
            self._view.clear()
            return
        if self._show_raw:
            entries = self._service.get_all_logs()
        else:
            entries = self._service.get_stage_logs(self._stage.stage_id)
        lines = []
        for entry in entries:
            if entry.timestamp:
                lines.append(f"[{entry.timestamp}] {entry.message}")
            else:
                lines.append(entry.message)
        self._view.setPlainText("\n".join(lines))
        self._view.moveCursor(self._view.textCursor().End)

    def _on_log_appended(self, stage_id: str, _message: str) -> None:
        if not self._active:
            return
        if not self._show_raw and self._stage and stage_id != self._stage.stage_id:
            return
        self._render_logs()

    def _on_raw_toggled(self, value: bool) -> None:
        self._show_raw = value
        self._render_logs()
