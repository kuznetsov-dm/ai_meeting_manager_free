from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aimn.ui.tabs.contracts import PipelineEvent, StageViewModel
from aimn.ui.tabs.logs_tab import LogsTab
from aimn.ui.tabs.overview_tab import OverviewTab
from aimn.ui.tabs.preview_tab import PreviewTab
from aimn.ui.tabs.settings_tab import SettingsTab


class StageInspectorPanel(QWidget):
    settingsChanged = Signal(str, dict)
    runRequested = Signal(str)
    runFromRequested = Signal(str)
    rerunRequested = Signal(str)

    def __init__(self, settings_service, artifact_service, log_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stage: Optional[StageViewModel] = None
        self._density = "full"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QFrame()
        header.setObjectName("stageInspectorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(8)

        self._stage_name = QLabel("Select a stage")
        self._stage_name.setObjectName("stageInspectorTitle")
        self._stage_status = QLabel("")
        self._stage_status.setObjectName("stageInspectorStatus")
        self._stage_progress = QLabel("")
        self._stage_progress.setObjectName("stageInspectorProgress")
        self._stage_meta = QLabel("")
        self._stage_meta.setObjectName("stageInspectorMeta")

        header_layout.addWidget(self._stage_name)
        header_layout.addWidget(self._stage_status)
        header_layout.addWidget(self._stage_progress)
        header_layout.addStretch()
        header_layout.addWidget(self._stage_meta)

        self._run_btn = QPushButton("Run")
        self._run_from_btn = QPushButton("Run From Here")
        self._rerun_btn = QPushButton("Rerun")
        header_layout.addWidget(self._run_btn)
        header_layout.addWidget(self._run_from_btn)
        header_layout.addWidget(self._rerun_btn)

        self._tabs = StageInspectorTabsHost(settings_service, artifact_service, log_service)
        self._tabs.settingsChanged.connect(self.settingsChanged)

        self._run_btn.clicked.connect(self._emit_run)
        self._run_from_btn.clicked.connect(self._emit_run_from)
        self._rerun_btn.clicked.connect(self._emit_rerun)

        layout.addWidget(header)
        layout.addWidget(self._tabs, 1)

        self._apply_stage(None)

    def set_stage(self, stage: StageViewModel) -> None:
        self._apply_stage(stage)
        self._tabs.set_stage(stage)

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        self._tabs.on_pipeline_event(event)

    def set_density(self, density: str) -> None:
        self._density = density
        collapsed = density == "collapsed"
        self._tabs.setVisible(not collapsed)
        self._run_btn.setVisible(not collapsed)
        self._run_from_btn.setVisible(not collapsed)
        self._rerun_btn.setVisible(not collapsed)
        self._stage_meta.setVisible(not collapsed)
        self._tabs.set_density(density)
        self.setProperty("density", density)
        self.style().unpolish(self)
        self.style().polish(self)

    def get_density(self) -> str:
        return str(self.property("density") or "full")

    def _apply_stage(self, stage: StageViewModel | None) -> None:
        self._stage = stage
        if not stage:
            self._stage_name.setText("Select a stage")
            self._stage_status.setText("")
            self._stage_progress.setText("")
            self._stage_meta.setText("")
            self._run_btn.setEnabled(False)
            self._run_from_btn.setEnabled(False)
            self._rerun_btn.setEnabled(False)
            return
        self._stage_name.setText(stage.display_name)
        status = stage.status.title() if stage.status else ""
        self._stage_status.setText(status)
        if stage.progress is None:
            self._stage_progress.setText("")
        else:
            self._stage_progress.setText(f"{stage.progress}%")
        meta = stage.last_run_at or ""
        self._stage_meta.setText(meta)
        self._run_btn.setEnabled(stage.can_run)
        self._run_from_btn.setEnabled(stage.can_run)
        self._rerun_btn.setEnabled(stage.can_rerun)

    def _emit_run(self) -> None:
        if self._stage:
            self.runRequested.emit(self._stage.stage_id)

    def _emit_run_from(self) -> None:
        if self._stage:
            self.runFromRequested.emit(self._stage.stage_id)

    def _emit_rerun(self) -> None:
        if self._stage:
            self.rerunRequested.emit(self._stage.stage_id)


class StageInspectorTabsHost(QTabWidget):
    settingsChanged = Signal(str, dict)

    def __init__(self, settings_service, artifact_service, log_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stage: Optional[StageViewModel] = None
        self._active_index = 0
        self._density = "full"

        self._overview = OverviewTab()
        self._settings = SettingsTab(settings_service)
        self._preview = PreviewTab(artifact_service)
        self._logs = LogsTab(log_service)

        self.addTab(self._overview, "Overview")
        self.addTab(self._settings, "Settings")
        self.addTab(self._preview, "Preview")
        self.addTab(self._logs, "Logs")

        self._settings.settingsChanged.connect(self.settingsChanged)

        self.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(0)

    def set_stage(self, stage: StageViewModel) -> None:
        self._stage = stage
        self._overview.set_stage(stage)
        self._settings.set_stage(stage)
        self._preview.set_stage(stage)
        self._logs.set_stage(stage)
        if stage.stage_id == "input" and self._density != "collapsed":
            self._focus_settings_tab()

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        tab = self.widget(self.currentIndex())
        if hasattr(tab, "on_pipeline_event"):
            tab.on_pipeline_event(event)

    def set_density(self, density: str) -> None:
        self._density = density
        self._settings.set_density("full" if density == "full" else "mini")
        settings_index = self.indexOf(self._settings)
        if density == "mini":
            for idx in range(self.count()):
                self._set_tab_visible(idx, idx == settings_index)
            self.setCurrentIndex(settings_index)
        else:
            for idx in range(self.count()):
                self._set_tab_visible(idx, True)

    def _on_tab_changed(self, index: int) -> None:
        previous = self.widget(self._active_index)
        if hasattr(previous, "on_deactivated"):
            previous.on_deactivated()
        current = self.widget(index)
        if hasattr(current, "on_activated"):
            current.on_activated()
        self._active_index = index

    def _focus_settings_tab(self) -> None:
        settings_index = self.indexOf(self._settings)
        if settings_index >= 0:
            self.setCurrentIndex(settings_index)

    def _set_tab_visible(self, index: int, visible: bool) -> None:
        if hasattr(self, "setTabVisible"):
            self.setTabVisible(index, visible)
        else:
            self.setTabEnabled(index, visible)
