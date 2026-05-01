from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QTextEdit

from aimn.ui.tabs.contracts import PipelineEvent, StageViewModel


class OverviewTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._status = QLabel("Select a stage to view details.")
        self._summary = QTextEdit()
        self._summary.setReadOnly(True)

        layout.addWidget(self._status)
        layout.addWidget(self._summary, 1)

        self._stage: StageViewModel | None = None

    def set_stage(self, stage: StageViewModel) -> None:
        self._stage = stage
        status = stage.status.title() if stage.status else "Idle"
        parts = [f"Status: {status}"]
        if stage.progress is not None:
            parts.append(f"Progress: {stage.progress}%")
        if stage.error:
            parts.append(f"Error: {stage.error}")
        if stage.warnings:
            parts.append(f"Warnings: {len(stage.warnings)}")
        self._status.setText(" | ".join(parts))

        details = []
        if stage.error:
            details.append(f"Error:\n{stage.error}")
        if stage.warnings:
            details.append("Warnings:")
            details.extend(f"- {warning}" for warning in stage.warnings)
        if not details:
            details.append("No additional details for this stage yet.")
        self._summary.setPlainText("\n".join(details))

    def on_activated(self) -> None:
        return

    def on_deactivated(self) -> None:
        return

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        if not self._stage or event.stage_id != self._stage.stage_id:
            return
        if event.event_type in {"stage_failed", "stage_skipped"} and event.message:
            self._summary.setPlainText(event.message)
