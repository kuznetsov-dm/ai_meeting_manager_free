from __future__ import annotations

import html
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal, QMimeData
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPalette,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from aimn.ui.controllers.artifact_export_buttons_controller import ArtifactExportButtonsController
from aimn.ui.controllers.artifact_kind_bar_controller import ArtifactKindBarController
from aimn.ui.controllers.artifact_kind_bar_view_controller import ArtifactKindBarViewController
from aimn.ui.controllers.artifact_selection_controller import ArtifactSelectionController
from aimn.ui.controllers.artifact_tab_navigation_controller import ArtifactTabNavigationController
from aimn.ui.controllers.artifact_tabs_controller import ArtifactTabsController
from aimn.ui.controllers.artifact_tabs_view_controller import ArtifactTabsViewController
from aimn.ui.controllers.artifact_toolbar_controller import ArtifactToolbarController
from aimn.ui.controllers.artifact_view_data_controller import ArtifactViewDataController
from aimn.ui.controllers.audio_playback_controller import AudioPlaybackController
from aimn.ui.controllers.global_search_results_controller import GlobalSearchResultsController
from aimn.ui.controllers.local_search_flow_controller import LocalSearchFlowController
from aimn.ui.controllers.logs_buffer_controller import LogsBufferController
from aimn.ui.controllers.main_text_panel_selection_controller import MainTextPanelSelectionController
from aimn.ui.controllers.main_text_panel_search_flow_controller import MainTextPanelSearchFlowController
from aimn.ui.controllers.main_text_panel_global_results_controller import MainTextPanelGlobalResultsController
from aimn.ui.controllers.main_text_panel_navigation_controller import MainTextPanelNavigationController
from aimn.ui.controllers.main_text_panel_state_controller import MainTextPanelStateController
from aimn.ui.controllers.results_view_controller import ResultsViewCallbacks, ResultsViewController
from aimn.ui.controllers.search_action_controller import SearchActionController
from aimn.ui.controllers.search_mode_controller import SearchModeController
from aimn.ui.controllers.text_editor_controller import TextEditorController
from aimn.ui.controllers.text_search_highlight_controller import TextSearchHighlightController
from aimn.ui.controllers.toolbar_icon_controller import ToolbarIconController
from aimn.ui.controllers.transcript_evidence_controller import (
    TranscriptEvidenceController,
)
from aimn.ui.controllers.transcript_evidence_controller import (
    TranscriptSuggestionSpan as _TranscriptSuggestionSpan,
)
from aimn.ui.controllers.transcript_highlight_controller import TranscriptHighlightController
from aimn.ui.controllers.transcript_navigation_controller import TranscriptNavigationController
from aimn.ui.controllers.transcript_segments_view_controller import (
    TranscriptSegmentsViewCallbacks,
    TranscriptSegmentsViewController,
)
from aimn.ui.controllers.transcript_sync_controller import TranscriptSyncController
from aimn.ui.controllers.transcript_view_model_controller import TranscriptViewModelController
from aimn.ui.services.artifact_service import ArtifactItem
from aimn.ui.services.log_service import LogService
from aimn.ui.tabs.contracts import StageViewModel
from aimn.ui.tabs.settings_tab import SettingsTab
from aimn.ui.widgets.standard_components import (
    StandardActionButton,
    StandardStatusBadge,
    StandardTextSourceView,
)

_LOG = logging.getLogger(__name__)


class _TranscriptTextEdit(QTextEdit):
    clickedAt = Signal(int)
    doubleClickedAt = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pending_click_position: int | None = None
        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self._emit_pending_click)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        # Defer plain click handling so the first click of a double click does not
        # trigger navigation/playback, while drag-selection/copy remains native.
        if event.button() == Qt.LeftButton and not self.textCursor().hasSelection():
            self._pending_click_position = int(self.textCursor().position())
            interval = int(QApplication.styleHints().mouseDoubleClickInterval())
            self._single_click_timer.start(max(1, interval))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._single_click_timer.stop()
        self._pending_click_position = None
        cursor = self.cursorForPosition(event.position().toPoint())
        pos = int(cursor.position()) if isinstance(cursor, QTextCursor) else int(self.textCursor().position())
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton:
            self.doubleClickedAt.emit(pos)

    def _emit_pending_click(self) -> None:
        pos = self._pending_click_position
        self._pending_click_position = None
        if pos is not None:
            self.clickedAt.emit(int(pos))


class _LogsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, labels: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self._labels = dict(_DEFAULT_UI_LABELS)
        if isinstance(labels, dict):
            self._labels.update({str(k): str(v) for k, v in labels.items()})
        self.setWindowTitle(_ui_label(self._labels, "dialog.logs.title", "Logs"))
        self.resize(900, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._editor = QTextEdit()
        self._editor.setObjectName("logsText")
        self._editor.setReadOnly(True)
        layout.addWidget(self._editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy_btn = buttons.addButton(_ui_label(self._labels, "dialog.logs.copy", "Copy"), QDialogButtonBox.ActionRole)
        copy_btn.clicked.connect(self._copy_all)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 0)

    def set_logs(self, text: str) -> None:
        self._editor.setPlainText(str(text or ""))

    def _copy_all(self) -> None:
        QApplication.clipboard().setText(self._editor.toPlainText())


TextEditorWidget = QTextEdit | QPlainTextEdit


_STATUS_LABELS = {
    "idle": "Idle",
    "ready": "Ready",
    "running": "Running",
    "completed": "Completed",
    "skipped": "Skipped",
    "failed": "Failed",
    "disabled": "Disabled",
}

_DEFAULT_UI_LABELS = {
    "tile.settings": "Settings",
    "tile.artifacts": "Artifacts",
    "status.idle": "Idle",
    "status.ready": "Ready",
    "status.running": "Running",
    "status.completed": "Completed",
    "status.skipped": "Skipped",
    "status.failed": "Failed",
    "status.disabled": "Disabled",
    "status.mock_suffix": "Mock",
    "pipeline.add": "ADD",
    "pipeline.run": "RUN",
    "pipeline.pause": "PAUSE",
    "pipeline.resume": "RESUME",
    "pipeline.stop": "STOP",
    "pipeline.pick_files_title": "Select audio/video files",
    "pipeline.pick_files_filter": "Media Files (*.wav *.mp3 *.m4a *.mp4 *.mkv *.mov *.avi *.flac *.ogg *.webm);;All Files (*.*)",
    "pipeline.drawer.settings_suffix": "settings",
    "pipeline.drawer.enabled": "Enabled",
    "history.title": "History",
    "history.rename": "Rename",
    "history.rerun": "Rerun",
    "history.export": "Export",
    "history.delete": "Delete",
    "history.rename_tip": "Rename meeting",
    "history.rerun_tip": "Run again from a selected stage",
    "history.export_tip": "Export meeting artifacts",
    "history.rerun_disabled_no_source": "No source file to rerun",
    "history.actions_disabled": "Meeting key is missing",
    "history.status.raw": "New",
    "history.status.processing": "Processing",
    "history.status.failed": "Failed",
    "history.status.cancelled": "Cancelled",
    "history.status.completed": "Completed",
    "artifacts.title": "Artifacts",
    "inspection.title": "Text Inspection",
    "inspection.empty": "Select a text version to inspect lineage.",
    "search.button": "Search",
    "search.prev": "Prev",
    "search.next": "Next",
    "search.clear": "Clear",
    "search.logs": "Logs",
    "search.copy": "Copy",
    "search.copy_all": "Copy All",
    "search.copy_html": "Copy HTML",
    "search.export": "Export",
    "search.export_target": "Target",
    "search.placeholder.local": "Search in text...",
    "search.placeholder.global": "Search across meetings...",
    "search.mode.local": "In document",
    "search.mode.global": "Everywhere",
    "search.tab.results": "Search Results",
    "search.tab.text": "Text",
    "search.matches.none": "0 matches",
    "audio.play": "Play",
    "audio.pause": "Pause",
    "audio.stop": "Stop",
    "dialog.logs.title": "Logs",
    "dialog.logs.copy": "Copy",
    "kind.transcript": "Transcript",
    "kind.edited": "Edited",
    "kind.summary": "Summary",
    "transcript.menu.create_task": "Create task from selection",
    "transcript.menu.create_project": "Create project from selection",
    "transcript.menu.create_agenda": "Create agenda from selection",
    "transcript.menu.approve_suggestion": "Approve highlighted suggestion",
    "transcript.menu.hide_suggestion": "Hide highlighted suggestion",
    "transcript.menu.create_task_highlight": "Create task from highlight",
    "transcript.menu.create_project_highlight": "Create project from highlight",
    "transcript.menu.create_agenda_highlight": "Create agenda from highlight",
}

_PIPELINE_TILE_HORIZONTAL_PADDING = 10
_PIPELINE_TILE_VERTICAL_PADDING = 8
_PIPELINE_TILE_SPACING = 6
_PIPELINE_TILE_BADGE_SPACING = 6
_PIPELINE_TILE_ACTION_SPACING = 8
_BADGE_HORIZONTAL_PADDING = 8
_BADGE_VERTICAL_PADDING = 2
_BADGE_MIN_HEIGHT = 18
_ICON_BUTTON_SIDE = 34
_ICON_SIZE = 24


def _ui_label(labels: dict[str, str], key: str, default: str) -> str:
    value = str((labels or {}).get(key, "") or "").strip()
    return value or str(default or "")


def _pipeline_badge_font(base_font: QFont) -> QFont:
    font = QFont(base_font)
    font.setBold(True)
    font.setPointSize(11)
    return font


def _pipeline_title_font(base_font: QFont) -> QFont:
    font = QFont(base_font)
    font.setBold(True)
    return font


def _measure_pipeline_badge_size(base_font: QFont, samples: Sequence[str]) -> QSize:
    metrics = QFontMetrics(_pipeline_badge_font(base_font))
    text_width = max((metrics.horizontalAdvance(str(sample or "") or " ") for sample in samples), default=0)
    text_height = metrics.height()
    width = text_width + (2 * _BADGE_HORIZONTAL_PADDING) + 2
    height = max(_BADGE_MIN_HEIGHT, text_height + (2 * _BADGE_VERTICAL_PADDING) + 2)
    return QSize(int(width), int(height))


def _measure_pipeline_action_button_size(base_font: QFont, text: str) -> QSize:
    font = _pipeline_badge_font(base_font)
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance(str(text or "") or " ") + 18
    height = max(_BADGE_MIN_HEIGHT + 2, metrics.height() + 6)
    return QSize(int(width), int(height))


def _measure_pipeline_tile_size(
    base_font: QFont,
    *,
    title: str,
    status_size: QSize,
    progress_size: QSize,
    action_sizes: Sequence[QSize] | None = None,
) -> QSize:
    title_metrics = QFontMetrics(_pipeline_title_font(base_font))
    title_width = title_metrics.horizontalAdvance(str(title or "") or " ")
    title_height = title_metrics.height()
    badge_row_width = int(status_size.width()) + _PIPELINE_TILE_BADGE_SPACING + int(progress_size.width())
    badge_row_height = max(int(status_size.height()), int(progress_size.height()))
    content_width = max(title_width, badge_row_width)
    total_height = title_height + _PIPELINE_TILE_SPACING + badge_row_height
    if action_sizes:
        actions_width = sum(int(size.width()) for size in action_sizes) + (
            _PIPELINE_TILE_ACTION_SPACING * max(0, len(action_sizes) - 1)
        )
        actions_height = max((int(size.height()) for size in action_sizes), default=0)
        content_width = max(content_width, actions_width)
        total_height += _PIPELINE_TILE_SPACING + actions_height
    width = (2 * _PIPELINE_TILE_HORIZONTAL_PADDING) + content_width
    height = (2 * _PIPELINE_TILE_VERTICAL_PADDING) + total_height
    return QSize(int(width), int(height))


def _configure_icon_button(button: QToolButton) -> None:
    button.setObjectName("audioControlButton")
    button.setAutoRaise(True)
    button.setFocusPolicy(Qt.NoFocus)
    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    button.setFixedSize(QSize(_ICON_BUTTON_SIDE, _ICON_BUTTON_SIDE))
    button.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))


def _history_status_label(status: str, labels: dict[str, str] | None = None) -> str:
    labels_map = dict(_DEFAULT_UI_LABELS)
    if isinstance(labels, dict):
        labels_map.update({str(k): str(v) for k, v in labels.items()})
    value = str(status or "").strip().lower()
    if value in {"complited", "complete", "done", "finished"}:
        value = "completed"
    if value in {"raw", "pending", "queued"}:
        return _ui_label(labels_map, "history.status.raw", "New")
    if value == "running":
        return _ui_label(labels_map, "history.status.processing", "Processing")
    if value == "failed":
        return _ui_label(labels_map, "history.status.failed", "Failed")
    if value == "cancelled":
        return _ui_label(labels_map, "history.status.cancelled", "Cancelled")
    if value == "completed":
        return _ui_label(labels_map, "history.status.completed", "Completed")
    if value:
        return value
    return ""


def _history_status_colors(status: str, *, dark: bool = False) -> tuple[str, str]:
    value = str(status or "").strip().lower()
    if value in {"complited", "complete", "done", "finished"}:
        value = "completed"
    if dark:
        if value in {"raw", "pending", "queued"}:
            return "#202938", "#BDD0EA"
        if value == "running":
            return "#1F2D42", "#B8CCE8"
        if value == "failed":
            return "#3A2228", "#E2B6C3"
        if value == "cancelled":
            return "#222C3B", "#C1CBD9"
        if value == "completed":
            return "#20382F", "#B9DDCB"
        if value:
            return "#222C3B", "#C1CBD9"
        return "#111827", "#94A3B8"
    if value in {"raw", "pending", "queued"}:
        return "#F3F7FC", "#4E627D"
    if value == "running":
        return "#EDF4FF", "#355C8A"
    if value == "failed":
        return "#FBEFF2", "#9B4D62"
    if value == "cancelled":
        return "#F3F5F8", "#5B687A"
    if value == "completed":
        return "#EDF7F1", "#2E6C50"
    if value:
        return "#F3F5F8", "#5B687A"
    return "#F1F5F9", "#64748B"


def _ui_status(stage: StageViewModel) -> str:
    # UI v2: only one user-facing status. Internal states are mapped.
    raw = (stage.status or "idle").lower()
    if raw in {"dirty"}:
        return "ready"
    if raw in {"blocked"}:
        return "idle"
    return raw if raw in _STATUS_LABELS else "idle"


class PipelineTileV2(QFrame):
    clicked = Signal(str)
    artifactsClicked = Signal(str)
    contextRequested = Signal(str, QPoint)

    def __init__(
        self,
        stage_id: str,
        *,
        show_artifacts_button: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ui_labels = dict(_DEFAULT_UI_LABELS)
        self.stage_id = stage_id
        self._selected = False
        self._pressed = False
        self._attention = False
        self._show_artifacts_button = bool(show_artifacts_button)
        self._artifacts_btn: QToolButton | None = None
        self._settings_btn: QToolButton | None = None
        self._last_stage_signature: tuple[str, str, str, str, str] | None = None
        self._last_tooltip: str = ""
        self._last_artifacts_enabled: bool | None = None

        self.setObjectName("pipelineTileV2")
        self.setFrameShape(QFrame.Box)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setProperty("selected", False)
        self.setProperty("attention", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._name = QLabel(stage_id)
        self._name.setObjectName("pipelineTileName")
        self._name.setWordWrap(False)
        layout.addWidget(self._name)

        row = QHBoxLayout()
        row.setSpacing(_PIPELINE_TILE_BADGE_SPACING)
        self._status = StandardStatusBadge("Idle")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row.addWidget(self._status, 0)
        self._progress = StandardStatusBadge("")
        self._progress.setAlignment(Qt.AlignCenter)
        self._progress.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row.addWidget(self._progress, 0)
        layout.addLayout(row)

        if self._show_artifacts_button:
            actions = QHBoxLayout()
            actions.setContentsMargins(0, 0, 0, 0)
            actions.setSpacing(8)
            self._settings_btn = StandardActionButton()
            self._settings_btn.setText(_ui_label(self._ui_labels, "tile.settings", "Settings"))
            self._settings_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self._settings_btn.setAutoRaise(False)
            self._settings_btn.setFocusPolicy(Qt.NoFocus)
            self._settings_btn.clicked.connect(lambda *_args: self.clicked.emit(self.stage_id))
            actions.addWidget(self._settings_btn, 0, Qt.AlignLeft)
            self._artifacts_btn = StandardActionButton()
            self._artifacts_btn.setText(_ui_label(self._ui_labels, "tile.artifacts", "Artifacts"))
            self._artifacts_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self._artifacts_btn.setAutoRaise(False)
            self._artifacts_btn.setFocusPolicy(Qt.NoFocus)
            self._artifacts_btn.clicked.connect(lambda *_args: self.artifactsClicked.emit(self.stage_id))
            actions.addWidget(self._artifacts_btn, 0, Qt.AlignRight)
            layout.addLayout(actions)

        self._resize_tile()
        self._apply_selected(False)

    def set_stage(self, stage: StageViewModel) -> None:
        name = str(stage.display_name or "")
        key = _ui_status(stage)
        status_label = _ui_label(self._ui_labels, f"status.{key}", _STATUS_LABELS.get(key, "Idle"))
        if stage.stage_id == "llm_processing" and stage.ui_metadata.get("mock_summary"):
            status_label = f"{status_label} ({_ui_label(self._ui_labels, 'status.mock_suffix', 'Mock')})"
            key = "skipped"

        if stage.progress is None:
            progress_text = "..."
            progress_state = "idle"
        else:
            progress_text = f"{int(stage.progress)}%"
            progress_state = key
        signature = (name, key, status_label, progress_text, progress_state)
        if self._last_stage_signature != signature:
            self._last_stage_signature = signature
            self._name.setText(name)
            self._status.setText(status_label)
            self._status.set_state(key)
            self._progress.setText(progress_text)
            self._progress.set_state(progress_state)
            self._resize_tile()
        # Tooltip contains errors, but does not introduce extra UI states.
        tip = [stage.display_name]
        if stage.error:
            tip.append(f"Error: {stage.error}")
        if stage.stage_id == "llm_processing" and stage.ui_metadata.get("mock_summary"):
            mock_reason = str(stage.ui_metadata.get("mock_summary_reason_label", "") or "").strip() or str(
                stage.ui_metadata.get("mock_summary_reason", "") or ""
            ).strip()
            if mock_reason:
                tip.append(f"Mock fallback: {mock_reason}")
            else:
                tip.append("Mock summary provider selected")
        if (
            stage.stage_id == "llm_processing"
            and str(stage.status or "").lower() == "running"
            and stage.progress is None
        ):
            tip.append("LLM running; progress may be unavailable")
        tooltip = "\n".join(tip)
        if tooltip != self._last_tooltip:
            self._last_tooltip = tooltip
            self.setToolTip(tooltip)
        if self._artifacts_btn:
            enabled = stage.stage_id in {"transcription", "llm_processing", "management"}
            if self._last_artifacts_enabled is None or bool(self._last_artifacts_enabled) != bool(enabled):
                self._last_artifacts_enabled = bool(enabled)
                self._artifacts_btn.setEnabled(bool(enabled))

    def set_attention(self, attention: bool) -> None:
        self._attention = bool(attention)
        self._apply_selected(self._selected)

    def set_ui_labels(self, labels: dict[str, str] | None) -> None:
        if isinstance(labels, dict):
            self._ui_labels.update({str(k): str(v) for k, v in labels.items()})
        if self._settings_btn is not None:
            self._settings_btn.setText(_ui_label(self._ui_labels, "tile.settings", "Settings"))
        if self._artifacts_btn is not None:
            self._artifacts_btn.setText(_ui_label(self._ui_labels, "tile.artifacts", "Artifacts"))
        state = str(self._status.property("state") or "idle").strip().lower() or "idle"
        self._status.setText(_ui_label(self._ui_labels, f"status.{state}", _STATUS_LABELS.get(state, "Idle")))
        self._resize_tile()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_selected(self._selected)

    def _apply_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.setProperty("attention", bool((not selected) and self._attention))
        try:
            style = self.style()
            style.unpolish(self)
            style.polish(self)
            self.update()
        except RuntimeError as exc:
            _LOG.debug("workspace_tile_restyle_failed error=%s", exc)
            return

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            # Do not emit on press: the drawer may open under the cursor before mouseRelease,
            # which can cause accidental clicks (e.g. opening a file dialog).
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            was_pressed = self._pressed
            self._pressed = False
            if was_pressed and self.rect().contains(event.pos()):
                self.clicked.emit(self.stage_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        global_pos = event.globalPos() if event is not None else self.mapToGlobal(self.rect().center())
        self.contextRequested.emit(self.stage_id, global_pos)
        if event is not None:
            event.accept()

    def _resize_tile(self) -> None:
        status_samples = [
            _ui_label(self._ui_labels, f"status.{state}", _STATUS_LABELS.get(state, state.title()))
            for state in _STATUS_LABELS
        ]
        status_size = _measure_pipeline_badge_size(self.font(), status_samples)
        progress_size = _measure_pipeline_badge_size(self.font(), ["100%", "..."])
        self._status.setFixedSize(status_size)
        self._progress.setFixedSize(progress_size)

        action_sizes: list[QSize] = []
        if self._settings_btn is not None:
            action_sizes.append(_measure_pipeline_action_button_size(self.font(), self._settings_btn.text()))
        if self._artifacts_btn is not None:
            action_sizes.append(_measure_pipeline_action_button_size(self.font(), self._artifacts_btn.text()))
        size = _measure_pipeline_tile_size(
            self.font(),
            title=self._name.text(),
            status_size=status_size,
            progress_size=progress_size,
            action_sizes=action_sizes,
        )
        self.setFixedSize(size)


class PipelinePanelV2(QWidget):
    stageClicked = Signal(str)
    stageContextRequested = Signal(str, QPoint)
    runClicked = Signal()
    stageSettingsChanged = Signal(str, dict)
    stageEnabledChanged = Signal(str, bool)
    stageArtifactsClicked = Signal(str)
    filesAdded = Signal(list)
    pauseToggled = Signal(bool)
    stopClicked = Signal()
    stageActionRequested = Signal(str, dict)

    def __init__(
        self,
        settings_service,
        *,
        experimental_artifacts_click: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ui_labels = dict(_DEFAULT_UI_LABELS)
        self.setAcceptDrops(True)
        self._settings_service = settings_service
        self._experimental_artifacts_click = bool(experimental_artifacts_click)
        self._tiles: dict[str, PipelineTileV2] = {}
        self._selected_stage_id: str | None = None
        self._pending_stage_click: str | None = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._flush_stage_click)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._paused = False
        self._activity: str = ""
        self._default_input_dir: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # UI v2: keep the pipeline area clean. Meta goes to tooltips / status bar.
        self._meta = ""

        self._row = QWidget()
        row_layout = QHBoxLayout(self._row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        self._tiles_container = QWidget()
        self._tiles_layout = QHBoxLayout(self._tiles_container)
        self._tiles_layout.setContentsMargins(0, 0, 0, 0)
        self._tiles_layout.setSpacing(8)
        self._add_btn = QPushButton(_ui_label(self._ui_labels, "pipeline.add", "ADD"))
        self._add_btn.setObjectName("pipelineRunButton")
        self._add_btn.clicked.connect(self._pick_files)
        self._tiles_layout.addWidget(self._add_btn)
        row_layout.addWidget(self._tiles_container, 0, Qt.AlignLeft)
        row_layout.addStretch()

        self._pause_btn = QPushButton(_ui_label(self._ui_labels, "pipeline.pause", "PAUSE"))
        self._pause_btn.setObjectName("pipelinePauseButton")
        self._pause_btn.clicked.connect(self._toggle_pause)
        row_layout.addWidget(self._pause_btn, 0, Qt.AlignRight)

        self._stop_btn = QPushButton(_ui_label(self._ui_labels, "pipeline.stop", "STOP"))
        self._stop_btn.setObjectName("pipelineStopButton")
        self._stop_btn.clicked.connect(lambda _checked=False: self.stopClicked.emit())
        row_layout.addWidget(self._stop_btn, 0, Qt.AlignRight)

        self._run_btn = QPushButton(_ui_label(self._ui_labels, "pipeline.run", "RUN"))
        self._run_btn.setObjectName("pipelineRunButton")
        self._run_btn.clicked.connect(lambda _checked=False: self.runClicked.emit())
        row_layout.addWidget(self._run_btn, 0, Qt.AlignRight)
        self._update_action_button_sizes()

        layout.addWidget(self._row)

        # Expand-down settings drawer (one at a time).
        self._drawer = QFrame()
        self._drawer.setObjectName("stageSettingsDrawer")
        self._drawer.setFrameShape(QFrame.Box)
        self._drawer.setVisible(False)
        self._drawer.setMaximumHeight(16777215)
        self._drawer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        drawer_layout = QVBoxLayout(self._drawer)
        drawer_layout.setContentsMargins(10, 10, 10, 10)
        drawer_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._drawer_title = QLabel("")
        self._drawer_title.setObjectName("stageSettingsTitle")
        header.addWidget(self._drawer_title, 1)
        self._enabled_box = QCheckBox(_ui_label(self._ui_labels, "pipeline.drawer.enabled", "Enabled"))
        self._enabled_box.stateChanged.connect(lambda _state: self._emit_enabled())
        header.addWidget(self._enabled_box)
        drawer_layout.addLayout(header)

        self._settings_stack = QStackedWidget()
        self._settings_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._settings_tabs: dict[str, SettingsTab] = {}
        self._settings_stage_signatures: dict[str, tuple[str, ...]] = {}
        self._settings: SettingsTab | None = None
        # No stretch here: the drawer should follow the content size, not fill spare space.
        drawer_layout.addWidget(self._settings_stack, 0)
        layout.addWidget(self._drawer)

        self._update_height_constraints()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        files: list[str] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if path:
                files.append(path)
        if files:
            self.filesAdded.emit(files)
            event.acceptProposedAction()
            return
        event.ignore()

    def set_meta(self, text: str) -> None:
        meta = str(text or "")
        self._meta = meta
        # Use tooltips so users can still inspect the state when needed.
        self.setToolTip(meta)
        self._run_btn.setToolTip(meta)

    def set_activity(self, text: str) -> None:
        # Kept for API compatibility with MeetingsTabV2.
        self._activity = str(text or "").strip()
        self.setToolTip(self._meta or self._activity)
        self._run_btn.setToolTip(self._meta or self._activity)

    def set_activity_context(
        self,
        *,
        stage_name: str = "",
        plugin_name: str = "",
        lines: Sequence[str] | None = None,
    ) -> None:
        details: list[str] = []
        if str(stage_name or "").strip():
            details.append(str(stage_name or "").strip())
        if str(plugin_name or "").strip():
            details.append(str(plugin_name or "").strip())
        for line in list(lines or [])[:3]:
            text = str(line or "").strip()
            if text:
                details.append(text)
        if details:
            tip = "\n".join(details)
            self.setToolTip(tip)
            self._run_btn.setToolTip(tip)

    def set_run_enabled(self, enabled: bool) -> None:
        self._run_btn.setEnabled(bool(enabled))

    def set_pause_enabled(self, enabled: bool) -> None:
        self._pause_btn.setEnabled(bool(enabled))

    def set_stop_enabled(self, enabled: bool) -> None:
        self._stop_btn.setEnabled(bool(enabled))

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self._pause_btn.setText(
            _ui_label(self._ui_labels, "pipeline.resume", "RESUME")
            if self._paused
            else _ui_label(self._ui_labels, "pipeline.pause", "PAUSE")
        )

    def _pick_files(self) -> None:
        if self.sender() is not self._add_btn or not self.isVisible():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            _ui_label(self._ui_labels, "pipeline.pick_files_title", "Select audio/video files"),
            self._default_input_dir,
            _ui_label(
                self._ui_labels,
                "pipeline.pick_files_filter",
                "Media Files (*.wav *.mp3 *.m4a *.mp4 *.mkv *.mov *.avi *.flac *.ogg *.webm);;All Files (*.*)",
            ),
        )
        if files:
            self.filesAdded.emit(list(files))

    def set_default_input_dir(self, path: str) -> None:
        value = str(path or "").strip()
        self._default_input_dir = value

    def _toggle_pause(self) -> None:
        if not self._pause_btn.isEnabled():
            return
        self._paused = not self._paused
        self._pause_btn.setText(
            _ui_label(self._ui_labels, "pipeline.resume", "RESUME")
            if self._paused
            else _ui_label(self._ui_labels, "pipeline.pause", "PAUSE")
        )
        self.pauseToggled.emit(self._paused)

    def selected_stage_id(self) -> str | None:
        return self._selected_stage_id

    def is_settings_open(self) -> bool:
        return bool(self._drawer.isVisible())

    def set_stages(self, stages: Sequence[StageViewModel]) -> None:
        ids = [s.stage_id for s in stages]
        existing = set(self._tiles.keys())
        for stage in stages:
            tile = self._tiles.get(stage.stage_id)
            if not tile:
                tile = PipelineTileV2(
                    stage.stage_id, show_artifacts_button=self._experimental_artifacts_click
                )
                tile.set_ui_labels(self._ui_labels)
                tile.clicked.connect(self._on_tile_clicked)
                tile.contextRequested.connect(self.stageContextRequested.emit)
                tile.artifactsClicked.connect(self.stageArtifactsClicked.emit)
                self._tiles[stage.stage_id] = tile
                self._tiles_layout.addWidget(tile)
            tile.set_stage(stage)
            tile.set_attention(bool(stage.ui_metadata.get("attention") if stage.ui_metadata else False))
            tile.set_selected(stage.stage_id == self._selected_stage_id)
        for removed in existing - set(ids):
            tile = self._tiles.pop(removed)
            tile.setParent(None)
            if removed in self._settings_tabs:
                tab = self._settings_tabs.pop(removed)
                self._settings_stage_signatures.pop(removed, None)
                try:
                    self._settings_stack.removeWidget(tab)
                except RuntimeError as exc:
                    _LOG.debug("workspace_remove_settings_tab_failed stage_id=%s error=%s", removed, exc)
                tab.deleteLater()
                if self._settings is tab:
                    self._settings = None

        if self._selected_stage_id:
            # If the selected stage disappeared, close the drawer.
            if self._selected_stage_id not in self._tiles:
                self.close_settings()
        self._update_action_button_sizes()

    def _settings_tab_for_stage(self, stage_id: str) -> SettingsTab:
        sid = str(stage_id or "").strip()
        tab = self._settings_tabs.get(sid)
        if tab is not None:
            return tab
        tab = SettingsTab(self._settings_service)
        tab.set_layout_mode("grid", columns=3)
        tab.set_density("mini")
        tab.settingsChanged.connect(self._on_settings_changed)
        tab.customActionRequested.connect(self._on_custom_action_requested)
        self._settings_tabs[sid] = tab
        self._settings_stack.addWidget(tab)
        return tab

    @staticmethod
    def _stage_settings_signature(stage: StageViewModel) -> tuple[str, ...]:
        items: list[str] = [
            str(stage.stage_id or ""),
            str(stage.plugin_id or ""),
            "1" if bool(stage.is_enabled) else "0",
        ]
        for option in list(stage.plugin_options or []):
            items.append(f"p:{str(getattr(option, 'value', '') or '')}:{str(getattr(option, 'label', '') or '')}")
        for field in list(stage.settings_schema or []):
            field_key = str(getattr(field, "key", "") or "")
            field_value = json.dumps(getattr(field, "value", ""), ensure_ascii=True, sort_keys=True, default=str)
            items.append(f"f:{field_key}:{field_value}")
        current = getattr(stage, "current_settings", {}) or {}
        if isinstance(current, dict):
            for key in sorted(current.keys(), key=lambda value: str(value or "")):
                value = json.dumps(current.get(key), ensure_ascii=True, sort_keys=True, default=str)
                items.append(f"c:{str(key or '')}:{value}")
        ui_metadata = getattr(stage, "ui_metadata", {}) or {}
        if isinstance(ui_metadata, dict):
            for key in sorted(ui_metadata.keys(), key=lambda value: str(value or "")):
                value = json.dumps(ui_metadata.get(key), ensure_ascii=True, sort_keys=True, default=str)
                items.append(f"u:{str(key or '')}:{value}")
        for key in list(stage.inline_settings_keys or []):
            items.append(f"i:{str(key or '')}")
        return tuple(items)

    def open_settings(self, stage: StageViewModel) -> None:
        self._selected_stage_id = stage.stage_id
        for sid, tile in self._tiles.items():
            tile.set_selected(sid == stage.stage_id)
        self._drawer_title.setText(
            f"{stage.display_name} {_ui_label(self._ui_labels, 'pipeline.drawer.settings_suffix', 'settings')}"
        )
        self._enabled_box.blockSignals(True)
        self._enabled_box.setChecked(bool(stage.is_enabled))
        self._enabled_box.blockSignals(False)
        tab = self._settings_tab_for_stage(stage.stage_id)
        self._settings = tab
        self._settings_stack.setCurrentWidget(tab)
        signature = self._stage_settings_signature(stage)
        self._drawer.setUpdatesEnabled(False)
        try:
            if self._settings_stage_signatures.get(str(stage.stage_id or "")) != signature:
                tab.set_density("mini")
                tab.set_stage(stage)
                self._settings_stage_signatures[str(stage.stage_id or "")] = signature
        finally:
            self._drawer.setUpdatesEnabled(True)
        self._drawer.setVisible(True)
        self._sync_drawer_height()
        QTimer.singleShot(0, self._sync_drawer_height)
        QTimer.singleShot(20, self._sync_drawer_height)
        QTimer.singleShot(60, self._sync_drawer_height)
        self._update_height_constraints()
        self.updateGeometry()

    def close_settings(self) -> None:
        self._drawer.setVisible(False)
        self._drawer.setMinimumHeight(0)
        self._drawer.setMaximumHeight(16777215)
        self._selected_stage_id = None
        for tile in self._tiles.values():
            tile.set_selected(False)
        self._update_height_constraints()
        self.updateGeometry()

    def _on_tile_clicked(self, stage_id: str) -> None:
        if self._drawer.isVisible() and self._selected_stage_id == stage_id:
            self.close_settings()
            return
        # Debounce rapid clicks: schedule the open on the next event loop tick.
        self._pending_stage_click = stage_id
        if not self._click_timer.isActive():
            self._click_timer.start(0)

    def _flush_stage_click(self) -> None:
        if not self._pending_stage_click:
            return
        stage_id = self._pending_stage_click
        self._pending_stage_click = None
        self.stageClicked.emit(stage_id)

    def _emit_enabled(self) -> None:
        if not self._selected_stage_id:
            return
        self.stageEnabledChanged.emit(self._selected_stage_id, bool(self._enabled_box.isChecked()))

    def _on_settings_changed(self, stage_id: str, payload: dict) -> None:
        self.stageSettingsChanged.emit(stage_id, payload)
        QTimer.singleShot(0, self._sync_drawer_height)

    def _on_custom_action_requested(self, stage_id: str, payload: dict) -> None:
        self.stageActionRequested.emit(stage_id, payload)
        QTimer.singleShot(0, self._sync_drawer_height)

    def _sync_drawer_height(self) -> None:
        if not self._drawer.isVisible():
            return
        try:
            layout = self._drawer.layout()
            if layout:
                layout.activate()
            current_tab = self._settings_stack.currentWidget()
            header_height = 0
            if layout and layout.count() > 0:
                header_item = layout.itemAt(0)
                if header_item is not None:
                    header_height = int(header_item.sizeHint().height())
            spacing = int(layout.spacing()) if layout else 0
            margins = layout.contentsMargins() if layout else self._drawer.contentsMargins()
            content_height = int(current_tab.sizeHint().height()) if current_tab is not None else 0
            desired = (
                header_height
                + content_height
                + spacing
                + int(margins.top())
                + int(margins.bottom())
            )
            desired = max(96, desired)
            self._drawer.setMinimumHeight(desired)
            self._drawer.setMaximumHeight(desired)
            self._drawer.updateGeometry()
        except RuntimeError as exc:
            _LOG.debug("workspace_drawer_size_update_failed error=%s", exc)
            return

    def _update_height_constraints(self) -> None:
        if not self._drawer.isVisible():
            self.setMinimumHeight(0)
            return
        # Do not force minHeight in UI v2: it creates visible "blank space" jumps when switching stages.
        # If the window is too small, users can resize it; otherwise we prefer stable layout.
        self.setMinimumHeight(0)

    def set_ui_labels(self, labels: dict[str, str] | None) -> None:
        if isinstance(labels, dict):
            self._ui_labels.update({str(k): str(v) for k, v in labels.items()})
        self._add_btn.setText(_ui_label(self._ui_labels, "pipeline.add", "ADD"))
        self._run_btn.setText(_ui_label(self._ui_labels, "pipeline.run", "RUN"))
        self._stop_btn.setText(_ui_label(self._ui_labels, "pipeline.stop", "STOP"))
        self._pause_btn.setText(
            _ui_label(self._ui_labels, "pipeline.resume", "RESUME")
            if self._paused
            else _ui_label(self._ui_labels, "pipeline.pause", "PAUSE")
        )
        self._enabled_box.setText(_ui_label(self._ui_labels, "pipeline.drawer.enabled", "Enabled"))
        for tile in self._tiles.values():
            tile.set_ui_labels(self._ui_labels)
        self._update_action_button_sizes()

    def _update_action_button_sizes(self) -> None:
        status_samples = [
            _ui_label(self._ui_labels, f"status.{state}", _STATUS_LABELS.get(state, state.title()))
            for state in _STATUS_LABELS
        ]
        status_size = _measure_pipeline_badge_size(self.font(), status_samples)
        progress_size = _measure_pipeline_badge_size(self.font(), ["100%", "..."])
        sample_title = max(
            [str(tile._name.text() or "") for tile in self._tiles.values()] or ["AI Processing"],
            key=len,
        )
        tile_height = _measure_pipeline_tile_size(
            self.font(),
            title=sample_title,
            status_size=status_size,
            progress_size=progress_size,
        ).height()
        for button in (self._add_btn, self._pause_btn, self._stop_btn, self._run_btn):
            metrics = QFontMetrics(button.font())
            width = max(tile_height, metrics.horizontalAdvance(str(button.text() or "") or " ") + 30)
            button.setFixedSize(QSize(int(width), int(tile_height)))


class HistoryPanelV2(QWidget):
    meetingSelected = Signal(str)  # base_name
    meetingRenameRequested = Signal(str)  # meeting key: base_name or meeting_id
    meetingDeleteRequested = Signal(str)  # meeting key: base_name or meeting_id
    meetingRerunRequested = Signal(str)  # meeting key: base_name or meeting_id
    meetingExportRequested = Signal(str)  # meeting key: base_name or meeting_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_labels = dict(_DEFAULT_UI_LABELS)
        self._meetings: list[object] = []
        self._selected_row: int = -1
        self.setObjectName("historyPanelV2")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._title = QLabel(_ui_label(self._ui_labels, "history.title", "History"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)

        self._list = QListWidget()
        self._list.setObjectName("historyMeetingsList")
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.itemSelectionChanged.connect(self._emit_selection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setResizeMode(QListView.Adjust)
        layout.addWidget(self._list, 1)

    def set_meetings(self, meetings: Sequence[object]) -> None:
        self._meetings = list(meetings or [])
        self._selected_row = -1
        self._list.clear()
        for meeting in self._meetings:
            item = QListWidgetItem()
            base = str(getattr(meeting, "base_name", "") or "")
            meeting_id = str(getattr(meeting, "meeting_id", "") or "")
            meeting_key = base or meeting_id
            item.setData(Qt.UserRole, base)
            widget = _HistoryItemWidget(
                meeting,
                labels=self._ui_labels,
                actions_enabled=bool(meeting_key),
                on_rename=lambda _checked=False, _key=meeting_key: self.meetingRenameRequested.emit(_key),
                on_delete=lambda _checked=False, _key=meeting_key: self.meetingDeleteRequested.emit(_key),
                on_rerun=lambda _checked=False, _key=meeting_key: self.meetingRerunRequested.emit(_key),
            )
            item.setSizeHint(QSize(0, widget.sizeHint().height()))
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)
        self._sync_item_widths()
        self._set_selected_row(self._list.currentRow())

    def select_by_base_name(self, base_name: str) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == base_name:
                if self._list.currentRow() == i:
                    return
                self._list.setCurrentItem(item)
                return

    def selected_base_name(self) -> str:
        items = self._list.selectedItems()
        if not items:
            return ""
        base = items[0].data(Qt.UserRole)
        return str(base or "")

    def _emit_selection(self) -> None:
        self._set_selected_row(self._list.currentRow())
        items = self._list.selectedItems()
        if not items:
            return
        base = items[0].data(Qt.UserRole)
        if base:
            self.meetingSelected.emit(str(base))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_item_widths()

    def _sync_item_widths(self) -> None:
        width = max(0, int(self._list.viewport().width()) - 4)
        for i in range(self._list.count()):
            item = self._list.item(i)
            widget = self._list.itemWidget(item)
            if not widget:
                continue
            widget.setFixedWidth(width)
            hint = widget.sizeHint()
            item.setSizeHint(QSize(width, hint.height()))

    def _sync_selected_state(self) -> None:
        self._set_selected_row(self._list.currentRow())

    def _set_selected_row(self, row: int) -> None:
        target = int(row) if int(row) >= 0 else -1
        if target == self._selected_row:
            return
        previous = int(self._selected_row)
        self._selected_row = target
        self._apply_row_selected_state(previous, False)
        self._apply_row_selected_state(target, True)

    def _apply_row_selected_state(self, row: int, selected: bool) -> None:
        if int(row) < 0 or int(row) >= self._list.count():
            return
        item = self._list.item(int(row))
        if item is None:
            return
        widget = self._list.itemWidget(item)
        if not isinstance(widget, QWidget):
            return
        if bool(widget.property("selected")) == bool(selected):
            return
        widget.setProperty("selected", bool(selected))
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()

    def set_ui_labels(self, labels: dict[str, str] | None) -> None:
        if isinstance(labels, dict):
            self._ui_labels.update({str(k): str(v) for k, v in labels.items()})
        self._title.setText(_ui_label(self._ui_labels, "history.title", "History"))
        selected = self.selected_base_name()
        if self._meetings:
            self.set_meetings(self._meetings)
            if selected:
                self.select_by_base_name(selected)


class _HistoryItemWidget(QFrame):
    def __init__(
        self,
        meeting: object,
        *,
        on_rename,
        on_delete,
        on_rerun,
        actions_enabled: bool = True,
        labels: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._ui_labels = dict(_DEFAULT_UI_LABELS)
        if isinstance(labels, dict):
            self._ui_labels.update({str(k): str(v) for k, v in labels.items()})
        self.setObjectName("historyItemCard")
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        base = str(getattr(meeting, "base_name", "") or "")
        meeting_id = str(getattr(meeting, "meeting_id", "") or "")
        status = str(getattr(meeting, "processing_status", "") or "").strip().lower()
        if not status and getattr(meeting, "pipeline_runs", []):
            status = "completed"
        status_label = _history_status_label(status, self._ui_labels)
        source_name = ""
        try:
            source = getattr(meeting, "source", None)
            items = getattr(source, "items", None) if source else None
            if items:
                source_name = str(getattr(items[0], "input_filename", "") or "")
        except (AttributeError, IndexError, TypeError):
            source_name = ""
        display_title = str(getattr(meeting, "display_title", "") or "").strip()
        self._title_full = display_title or source_name or base or meeting_id
        meeting_time = str(getattr(meeting, "display_meeting_time", "") or "")
        processed_time = str(getattr(meeting, "display_processed_time", "") or "")
        stats_line = str(getattr(meeting, "display_stats", "") or "")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self._title = QLabel(self._title_full)
        self._title.setObjectName("historyItemTitle")
        self._title.setWordWrap(False)
        self._title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        top.addWidget(self._title, 1)
        layout.addLayout(top)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        if status_label:
            badge = StandardStatusBadge(status_label)
            badge.set_state(status)
            status_row.addWidget(badge, 0, Qt.AlignLeft)
        status_row.addItem(QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum))
        rename_btn = QToolButton()
        rename_btn.setText(_ui_label(self._ui_labels, "history.rename", "Rename"))
        rename_btn.setObjectName("historyItemRename")
        rename_btn.setAutoRaise(False)
        rename_btn.setFocusPolicy(Qt.NoFocus)
        rename_btn.setEnabled(bool(actions_enabled))
        rename_btn.clicked.connect(on_rename)
        rename_btn.setToolTip(
            _ui_label(self._ui_labels, "history.rename_tip", "Rename meeting")
            if actions_enabled
            else _ui_label(self._ui_labels, "history.actions_disabled", "Meeting key is missing")
        )
        status_row.addWidget(rename_btn, 0, Qt.AlignRight)
        delete_btn = QToolButton()
        delete_btn.setText(_ui_label(self._ui_labels, "history.delete", "Delete"))
        delete_btn.setObjectName("historyItemDelete")
        delete_btn.setAutoRaise(False)
        delete_btn.setFocusPolicy(Qt.NoFocus)
        delete_btn.setEnabled(bool(actions_enabled))
        delete_btn.setToolTip(
            _ui_label(self._ui_labels, "history.delete", "Delete")
            if actions_enabled
            else _ui_label(self._ui_labels, "history.actions_disabled", "Meeting key is missing")
        )
        delete_btn.clicked.connect(on_delete)
        status_row.addWidget(delete_btn, 0, Qt.AlignRight)
        layout.addLayout(status_row)

        meta_lines = [meeting_time, processed_time, stats_line]
        meta_lines = [line for line in meta_lines if str(line or "").strip()]
        for idx, line in enumerate(meta_lines):
            label = QLabel(line)
            label.setObjectName("historyItemMetaPrimary" if idx == 0 else "historyItemMeta")
            layout.addWidget(label)

        error = str(getattr(meeting, "processing_error", "") or "").strip()
        if error:
            self.setToolTip(error)

        # Styled by the app theme (avoid hardcoded light colors for dark mode compatibility).

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_title_elide()

    def _sync_title_elide(self) -> None:
        if not self._title_full:
            self._title.setText("")
            return
        width = max(0, int(self._title.width()))
        if width <= 0:
            self._title.setText(self._title_full)
            return
        metrics = self._title.fontMetrics()
        self._title.setText(metrics.elidedText(self._title_full, Qt.ElideRight, width))


@dataclass(frozen=True)
class ArtifactKindRow:
    kind: str
    count: int


class ArtifactsPanelV2(QWidget):
    artifactKindSelected = Signal(str)  # kind

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_labels = dict(_DEFAULT_UI_LABELS)
        self.setObjectName("artifactsPanelV2")
        self.setFixedWidth(320)
        self._max_visible_rows = 4

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._title = QLabel(_ui_label(self._ui_labels, "artifacts.title", "Artifacts"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)

        self._list = QListWidget()
        self._list.setObjectName("artifactsKindList")
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.itemSelectionChanged.connect(self._emit_selection)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self._list, 0)

    def set_artifacts(self, artifacts: Sequence[ArtifactItem]) -> None:
        self._list.clear()
        counts: dict[str, int] = {}
        for item in artifacts:
            kind = str(getattr(item, "kind", "") or "").strip().lower()
            if kind == "agendas":
                continue
            counts[kind] = counts.get(kind, 0) + 1
        order = ["transcript", "edited", "summary"]
        ordered = [k for k in order if k in counts]
        ordered.extend([k for k in counts.keys() if k not in set(order)])
        for kind in ordered:
            count = counts[kind]
            kind_label = _ui_label(self._ui_labels, f"kind.{kind}", kind)
            text = f"{kind_label}  ({count})" if count > 1 else kind_label
            lw = QListWidgetItem(text)
            lw.setData(Qt.UserRole, kind)
            self._list.addItem(lw)
        self._sync_list_height()

    def _sync_list_height(self) -> None:
        # Fixed-height list that fits exactly the 4 artifact kinds without scrolling.
        try:
            count = max(1, int(self._list.count()))
            visible = min(int(self._max_visible_rows), count)
            row_h = int(self._list.sizeHintForRow(0))
            if row_h <= 0:
                row_h = int(self._list.fontMetrics().height() + 8)
            frame = int(self._list.frameWidth() * 2)
            height = int(visible * row_h + frame + 10)
            self._list.setMinimumHeight(height)
            self._list.setMaximumHeight(height)
        except RuntimeError as exc:
            _LOG.debug("meeting_history_height_update_failed error=%s", exc)
            return

    def _emit_selection(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        kind = items[0].data(Qt.UserRole)
        if kind:
            self.artifactKindSelected.emit(str(kind))

    def set_ui_labels(self, labels: dict[str, str] | None) -> None:
        if isinstance(labels, dict):
            self._ui_labels.update({str(k): str(v) for k, v in labels.items()})
        self._title.setText(_ui_label(self._ui_labels, "artifacts.title", "Artifacts"))


class TextInspectionPanelV2(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_labels = dict(_DEFAULT_UI_LABELS)
        self.setObjectName("textInspectionPanelV2")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._title = QLabel(_ui_label(self._ui_labels, "inspection.title", "Text Inspection"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)

        self._view = StandardTextSourceView()
        self._view.setHtml(html.escape(_ui_label(self._ui_labels, "inspection.empty", "Select a text version to inspect lineage.")))
        layout.addWidget(self._view, 1)

    def set_html(self, html_text: str) -> None:
        self._view.setHtml(str(html_text or ""))

    def clear(self) -> None:
        self.set_html(html.escape(_ui_label(self._ui_labels, "inspection.empty", "Select a text version to inspect lineage.")))

    def set_ui_labels(self, labels: dict[str, str] | None) -> None:
        if isinstance(labels, dict):
            self._ui_labels.update({str(k): str(v) for k, v in labels.items()})
        self._title.setText(_ui_label(self._ui_labels, "inspection.title", "Text Inspection"))
        self.clear()


class _FlowWrapLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, *, h_spacing: int = 6, v_spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = int(max(0, h_spacing))
        self._v_spacing = int(max(0, v_spacing))
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:  # noqa: A003
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, max(0, int(width)), 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        right = effective.right()
        for item in self._items:
            hint = item.sizeHint()
            if hint.width() <= 0:
                continue
            next_x = x + hint.width()
            if line_height > 0 and next_x > right:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + self._h_spacing
            line_height = max(line_height, hint.height())
        return (y + line_height - rect.y()) + margins.bottom()


class _LazyArtifactView(QWidget):
    def __init__(self, loader: Callable[[], QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._loaded = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            content = self._loader()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            _LOG.warning("lazy_widget_loader_failed error=%s", exc)
            content = QTextEdit()
            content.setPlainText("")
            content.setReadOnly(True)
        self._layout.addWidget(content, 1)


class _ArtifactKindRow(QWidget):
    versionSelected = Signal(str, int)
    kindContextRequested = Signal(str, QPoint)
    versionContextRequested = Signal(str, int, QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind: str = ""
        self._kind_palette: str = "neutral"
        self._buttons: list[QToolButton] = []
        self._buttons_host: QWidget | None = None
        self._buttons_layout: _FlowWrapLayout | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._title = QLabel("")
        self._title.setObjectName("artifactKindRowTitle")
        self._title.setMinimumWidth(96)
        self._title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._title.setContextMenuPolicy(Qt.CustomContextMenu)
        self._title.customContextMenuRequested.connect(self._on_title_context_menu)
        root.addWidget(self._title, 0)

        buttons_host = QWidget(self)
        buttons_host.setObjectName("artifactKindTabBar")
        buttons_layout = _FlowWrapLayout(buttons_host, h_spacing=6, v_spacing=6)
        buttons_host.setLayout(buttons_layout)
        root.addWidget(buttons_host, 1)
        self._buttons_host = buttons_host
        self._buttons_layout = buttons_layout

    def set_row(
        self,
        *,
        kind: str,
        title: str,
        versions: Sequence[ArtifactItem],
        pinned_aliases: dict[str, str],
    ) -> None:
        self._kind = str(kind or "").strip()
        self._kind_palette = self._palette_id(self._kind)
        self._title.setText(str(title or "").strip())
        self._title.setProperty("kindPalette", self._kind_palette)
        self._refresh_widget_style(self._title)
        self._clear_buttons()
        if self._buttons_layout is None or self._buttons_host is None:
            return
        self._buttons_host.setProperty("kindPalette", self._kind_palette)
        self._refresh_widget_style(self._buttons_host)

        items = list(versions or [])
        if not items:
            placeholder = self._make_alias_button("-", index=0, enabled=False)
            self._buttons_layout.addWidget(placeholder)
            self._buttons.append(placeholder)
            return

        for index, art in enumerate(items):
            alias = str(getattr(art, "alias", "") or "").strip()
            stage_id = str(getattr(art, "stage_id", "") or "").strip()
            tab_title = alias or stage_id or f"v{index + 1}"
            if alias and stage_id and str(pinned_aliases.get(stage_id, "") or "").strip() == alias:
                tab_title = f"* {tab_title}"
            button = self._make_alias_button(tab_title, index=index, enabled=True)
            button.setToolTip(
                f"{stage_id}:{alias}\n{str(getattr(art, 'relpath', '') or '').strip()}",
            )
            self._buttons_layout.addWidget(button)
            self._buttons.append(button)

    def set_selected_index(self, index: int | None) -> None:
        active_kind = index is not None
        if self._buttons_host is not None:
            self._buttons_host.setProperty("activeKind", bool(active_kind))
            self._refresh_widget_style(self._buttons_host)
        target = int(index) if index is not None else -1
        for idx, button in enumerate(self._buttons):
            button.blockSignals(True)
            try:
                button.setChecked(active_kind and idx == target)
            finally:
                button.blockSignals(False)

    def _on_title_context_menu(self, pos: QPoint) -> None:
        self.kindContextRequested.emit(self._kind, self._title.mapToGlobal(pos))

    def _on_tab_clicked(self, index: int) -> None:
        idx = int(index)
        if idx < 0 or idx >= len(self._buttons):
            return
        button = self._buttons[idx]
        if not button.isEnabled():
            return
        self._emit_version_selected(idx)

    def _emit_version_selected(self, index: int) -> None:
        idx = int(index)
        if idx < 0 or idx >= len(self._buttons):
            return
        if not self._buttons[idx].isEnabled():
            return
        self.versionSelected.emit(self._kind, idx)

    def _on_tab_context_menu(self, pos: QPoint) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton):
            return
        try:
            idx = int(button.property("artifactIndex"))
        except (TypeError, ValueError):
            return
        if idx < 0 or idx >= len(self._buttons) or not button.isEnabled():
            return
        self.versionContextRequested.emit(self._kind, idx, button.mapToGlobal(pos))

    def _make_alias_button(self, title: str, *, index: int, enabled: bool) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("artifactAliasButton")
        button.setText(str(title or "").strip() or "-")
        button.setCheckable(True)
        button.setEnabled(bool(enabled))
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setProperty("kindPalette", self._kind_palette)
        button.setProperty("artifactIndex", int(index))
        button.clicked.connect(lambda _checked=False, idx=index: self._on_tab_clicked(idx))
        button.setContextMenuPolicy(Qt.CustomContextMenu)
        button.customContextMenuRequested.connect(self._on_tab_context_menu)
        self._refresh_widget_style(button)
        return button

    def _clear_buttons(self) -> None:
        if self._buttons_layout is None:
            self._buttons = []
            return
        while self._buttons_layout.count():
            item = self._buttons_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._buttons = []

    @staticmethod
    def _palette_id(kind: str) -> str:
        value = str(kind or "").strip().lower()
        if value == "transcript":
            return "transcript"
        if value == "summary":
            return "summary"
        return "neutral"

    @staticmethod
    def _refresh_widget_style(widget: QWidget) -> None:
        try:
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        except RuntimeError as exc:
            _LOG.debug("workspace_widget_restyle_failed widget=%s error=%s", type(widget).__name__, exc)
            return


class MainTextPanelV2(QWidget):
    globalSearchRequested = Signal(str, str)  # query, mode
    globalSearchCleared = Signal()
    globalSearchOpenRequested = Signal(
        str, str, str, str, int, int
    )  # meeting_id, stage_id, alias, kind, segment_index, start_ms
    pinRequested = Signal(str, str)  # stage_id, alias
    unpinRequested = Signal(str)  # stage_id
    activeVersionChanged = Signal(str, str)  # stage_id, alias
    artifactSelectionChanged = Signal(str, str, str)  # stage_id, alias, kind
    artifactKindContextRequested = Signal(str, QPoint)  # kind, global_pos
    artifactVersionContextRequested = Signal(str, str, str, QPoint)  # stage_id, alias, kind, global_pos
    artifactTextExportRequested = Signal(str, str, str, str, str, str)  # plugin_id, action_id, stage_id, alias, kind, text
    transcriptManagementCreateRequested = Signal(str, dict)  # entity_type, payload
    transcriptManagementSuggestionActionRequested = Signal(str, dict)  # action, payload

    def __init__(self, artifact_text_provider: Callable[[str], str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_labels = dict(_DEFAULT_UI_LABELS)
        self.setObjectName("mainTextPanelV2")
        self._artifact_text_provider = artifact_text_provider
        self._transcript_evidence_controller = TranscriptEvidenceController(artifact_text_provider)
        self._versions: list[ArtifactItem] = []
        self._segments_relpaths: dict[str, str] = {}
        self._management_suggestions: list[dict] = []
        self._artifacts_by_kind: dict[str, list[ArtifactItem]] = {}
        self._kinds: list[str] = []
        self._active_kind: str = ""
        self._pinned_aliases: dict[str, str] = {}
        self._active_aliases: dict[str, str] = {}
        self._current_audio_path: str = ""
        self._loaded_audio_path: str = ""
        self._latest_logs_text: str = ""
        self._latest_logs_count: int = 0
        self._match_cursors: list[QTextCursor] = []
        self._match_index: int = -1
        self._global_results_visible: bool = False
        self._global_results_query: str = ""
        self._global_results_hits: list[dict] = []
        self._global_results_answer: str = ""
        self._global_results_rows: list[dict] = []
        self._artifact_export_targets: list[dict[str, str]] = []
        self._artifact_export_buttons: list[QToolButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Search + playback controls (always visible when text content is shown).
        top = QHBoxLayout()
        top.setSpacing(8)

        self._mode = QComboBox()
        self._mode.setFixedWidth(140)
        self._mode.currentIndexChanged.connect(lambda _idx: self._on_search_mode_changed())
        top.addWidget(self._mode)

        self._search = QLineEdit()
        self._search.returnPressed.connect(self._submit_search)
        top.addWidget(self._search, 1)
        self._find_btn = QToolButton()
        _configure_icon_button(self._find_btn)
        self._find_btn.clicked.connect(self._submit_search)
        top.addWidget(self._find_btn)
        self._prev_btn = QToolButton()
        _configure_icon_button(self._prev_btn)
        self._prev_btn.clicked.connect(lambda *_args: self._step_match(-1))
        top.addWidget(self._prev_btn)
        self._next_btn = QToolButton()
        _configure_icon_button(self._next_btn)
        self._next_btn.clicked.connect(lambda *_args: self._step_match(1))
        top.addWidget(self._next_btn)
        self._matches = QLabel("")
        self._matches.setObjectName("searchMatchesLabel")
        top.addWidget(self._matches)

        self._clear_btn = QToolButton()
        _configure_icon_button(self._clear_btn)
        self._clear_btn.clicked.connect(self._clear_search)
        top.addWidget(self._clear_btn)
        self._logs_btn = QToolButton()
        _configure_icon_button(self._logs_btn)
        self._logs_btn.clicked.connect(self._show_logs_dialog)
        top.addWidget(self._logs_btn)
        self._copy_btn = QToolButton()
        _configure_icon_button(self._copy_btn)
        self._copy_btn.clicked.connect(self._copy_current_text)
        top.addWidget(self._copy_btn)
        self._copy_all_btn = QToolButton()
        _configure_icon_button(self._copy_all_btn)
        self._copy_all_btn.clicked.connect(self._copy_all_text)
        top.addWidget(self._copy_all_btn)
        self._copy_html_btn = QToolButton()
        _configure_icon_button(self._copy_html_btn)
        self._copy_html_btn.clicked.connect(self._copy_current_text_as_html)
        top.addWidget(self._copy_html_btn)
        self._export_buttons_host = QWidget(self)
        self._export_buttons_host.setObjectName("artifactExportButtonsHost")
        self._export_buttons_layout = QHBoxLayout(self._export_buttons_host)
        self._export_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._export_buttons_layout.setSpacing(4)
        top.addWidget(self._export_buttons_host, 0)

        self._audio_bar = QWidget(self)
        self._audio_bar.setObjectName("audioControlBar")
        audio_layout = QHBoxLayout(self._audio_bar)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(4)

        self._btn_play = QToolButton()
        _configure_icon_button(self._btn_play)
        self._btn_pause = QToolButton()
        _configure_icon_button(self._btn_pause)
        self._btn_stop = QToolButton()
        _configure_icon_button(self._btn_stop)
        self._btn_play.clicked.connect(self._play)
        self._btn_pause.clicked.connect(self._pause)
        self._btn_stop.clicked.connect(self._stop)
        audio_layout.addWidget(self._btn_play, 0)
        audio_layout.addWidget(self._btn_pause, 0)
        audio_layout.addWidget(self._btn_stop, 0)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setObjectName("audioSeekSlider")
        self._slider.setRange(0, 0)
        self._slider.setFixedWidth(180)
        self._slider.sliderMoved.connect(self._seek_ms)
        audio_layout.addWidget(self._slider, 0)
        top.addWidget(self._audio_bar, 0)

        layout.addLayout(top)

        self._kind_rows_host = QWidget(self)
        self._kind_rows_layout = QVBoxLayout(self._kind_rows_host)
        self._kind_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._kind_rows_layout.setSpacing(6)
        self._kind_rows: dict[str, _ArtifactKindRow] = {}
        layout.addWidget(self._kind_rows_host, 0)

        self._tabs = QTabWidget()
        self._tabs.setMovable(True)  # v2 spec: tabs are reorderable
        self._tabs.currentChanged.connect(lambda _idx: self._reset_search_state(clear_query=False))
        self._tabs.currentChanged.connect(self._on_version_tab_changed)
        self._tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self._tabs.tabBar().customContextMenuRequested.connect(self._on_tabs_context_menu)
        self._tabs.tabBar().hide()
        layout.addWidget(self._tabs, 1)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)

        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)

        self._set_audio_enabled(False)
        self._reset_search_state()
        self.set_search_modes(["local"])
        self._apply_command_icons()
        self._refresh_export_controls()

    def set_artifact_export_targets(self, targets: Sequence[dict] | Sequence[tuple[str, str, str]]) -> None:
        normalized = ArtifactExportButtonsController.normalize_targets(targets)

        if normalized == self._artifact_export_targets:
            self._refresh_export_controls()
            return
        self._artifact_export_targets = list(normalized)
        self._rebuild_export_buttons()
        self._refresh_export_controls()

    def set_artifacts(self, artifacts: Sequence[ArtifactItem], *, preferred_kind: str = "") -> None:
        items = list(artifacts or [])
        by_kind: dict[str, list[ArtifactItem]] = {}
        for art in items:
            kind = str(getattr(art, "kind", "") or "").strip() or "unknown"
            if kind.lower() == "agendas":
                continue
            by_kind.setdefault(kind, []).append(art)

        for _kind, kind_items in by_kind.items():
            kind_items.sort(key=lambda a: (str(a.alias or ""), str(a.stage_id or ""), str(a.relpath or "")))

        order = ["transcript", "edited", "summary"]
        kinds = [k for k in order if k in by_kind]
        kinds.extend([k for k in by_kind.keys() if k not in set(order)])

        self._artifacts_by_kind = by_kind
        self._kinds = kinds

        want = str(preferred_kind or "").strip()
        if not want:
            want = str(self._active_kind or "").strip()
        if want not in self._kinds:
            want = self._kinds[0] if self._kinds else ""

        self._rebuild_kind_bar(active_kind=want)
        self._active_kind = want
        self._versions = list(self._artifacts_by_kind.get(self._active_kind, []))
        self._rebuild_tabs()
        self._reset_search_state(clear_query=False)
        self._emit_current_selection()
        self._refresh_export_controls()

    def set_versions(self, versions: Sequence[ArtifactItem]) -> None:
        items = list(versions or [])
        preferred = ""
        if items:
            preferred = str(getattr(items[0], "kind", "") or "").strip()
        self.set_artifacts(items, preferred_kind=preferred)

    def set_meeting_context(
        self,
        *,
        artifacts: Sequence[ArtifactItem],
        segments_relpaths: dict[str, str] | None = None,
        management_suggestions: Sequence[dict] | None = None,
        pinned_aliases: dict[str, str] | None = None,
        active_aliases: dict[str, str] | None = None,
        preferred_kind: str = "",
    ) -> None:
        # Batch-update all meeting-scoped sources before rebuilding tabs once in set_artifacts().
        self._segments_relpaths = dict(segments_relpaths or {})
        self._transcript_evidence_controller.clear_segments_cache()
        self._management_suggestions = [dict(item) for item in (management_suggestions or []) if isinstance(item, dict)]
        self._pinned_aliases = dict(pinned_aliases or {})
        self._active_aliases = dict(active_aliases or {})
        self.set_artifacts(artifacts, preferred_kind=preferred_kind)

    def set_management_suggestions(self, suggestions: Sequence[dict] | None) -> None:
        payload = [dict(item) for item in (suggestions or []) if isinstance(item, dict)]
        if payload == self._management_suggestions:
            return
        self._management_suggestions = payload
        self._rebuild_tabs()
        self._emit_current_selection()

    def set_pinned_aliases(self, mapping: dict[str, str] | None) -> None:
        payload = dict(mapping or {})
        if payload == self._pinned_aliases:
            return
        self._pinned_aliases = payload
        self._rebuild_tabs()
        self._emit_current_selection()

    def set_active_aliases(
        self,
        mapping: dict[str, str] | None,
        *,
        rebuild_tabs: bool = True,
        emit_selection: bool = True,
    ) -> None:
        payload = dict(mapping or {})
        if payload == self._active_aliases:
            if emit_selection:
                self._emit_current_selection()
            return
        self._active_aliases = payload
        if rebuild_tabs:
            self._rebuild_tabs()
        if emit_selection:
            self._emit_current_selection()

    def set_segments_relpaths(self, mapping: dict[str, str] | None) -> None:
        payload = dict(mapping or {})
        if payload == self._segments_relpaths:
            return
        self._segments_relpaths = payload
        self._transcript_evidence_controller.clear_segments_cache()
        self._rebuild_tabs()
        self._emit_current_selection()

    def select_artifact_kind(self, kind: str) -> None:
        want = str(kind or "").strip()
        if not want or want not in self._kinds:
            return
        self._activate_kind(want)

    def _refresh_global_results_view(self, *, prefer_results: bool) -> None:
        state = MainTextPanelGlobalResultsController.apply_results(
            query=self._global_results_query,
            hits=list(self._global_results_hits),
            answer=self._global_results_answer,
            build_rows=self._build_global_results_rows,
        )
        self._global_results_visible = bool(state.visible)
        self._global_results_rows = list(state.rows)
        self._rebuild_tabs(prefer_results=prefer_results)

    def set_global_search_results(self, query: str, hits: list[dict], *, answer: str = "") -> None:
        state = MainTextPanelGlobalResultsController.apply_results(
            query=query,
            hits=hits,
            answer=answer,
            build_rows=self._build_global_results_rows,
        )
        if not state.changed:
            self.clear_global_search_results()
            return
        self._global_results_query = state.query
        self._global_results_hits = list(state.hits)
        self._global_results_answer = state.answer
        self._global_results_visible = bool(state.visible)
        self._global_results_rows = list(state.rows)
        self._rebuild_tabs(prefer_results=True)
        self._reset_search_state(clear_query=False)

    def clear_global_search_results(self) -> None:
        state = MainTextPanelGlobalResultsController.clear_results(
            visible=self._global_results_visible,
            query=self._global_results_query,
            hits=self._global_results_hits,
            answer=self._global_results_answer,
        )
        if not state.changed:
            return
        self._global_results_query = state.query
        self._global_results_hits = list(state.hits)
        self._global_results_answer = state.answer
        self._global_results_visible = bool(state.visible)
        self._global_results_rows = list(state.rows)
        self._rebuild_tabs()
        self._reset_search_state(clear_query=False)

    def highlight_query(self, query: str) -> None:
        should_highlight, q, target_mode = MainTextPanelSearchFlowController.highlight_request(query)
        if not should_highlight:
            return
        idx = self._mode.findData(target_mode)
        if idx >= 0 and idx != self._mode.currentIndex():
            self._mode.setCurrentIndex(idx)
        self._search.setText(q)
        self._run_search()

    def jump_to_transcript_segment(
        self,
        *,
        segment_index: int = -1,
        start_ms: int = -1,
        stage_id: str = "",
        alias: str = "",
        kind: str = "transcript",
    ) -> bool:
        want_stage = str(stage_id or "").strip()
        want_alias = str(alias or "").strip()
        want_kind = str(kind or "").strip() or "transcript"
        if want_kind:
            self.select_artifact_kind(want_kind)
        if want_stage or want_alias:
            self.select_version(stage_id=want_stage, alias=want_alias, kind=want_kind)

        widget = self._tabs.currentWidget()
        lst = widget.findChild(QListWidget, "transcriptSegmentsList") if isinstance(widget, QWidget) else None
        if not isinstance(lst, QListWidget):
            return False

        want_index = int(segment_index)
        want_start = int(start_ms)
        if want_index < 0 and want_start < 0:
            return False
        payloads: list[dict] = []
        for row in range(lst.count()):
            item = lst.item(row)
            payload = item.data(Qt.UserRole)
            payloads.append(dict(payload) if isinstance(payload, dict) else {})
        row = MainTextPanelNavigationController.transcript_row_index(
            payloads=payloads,
            segment_index=want_index,
            start_ms=want_start,
        )
        if row < 0:
            return False
        item = lst.item(int(row))
        lst.setCurrentRow(int(row))
        if item is not None:
            lst.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        return True

    def set_global_search_status(self, text: str) -> None:
        self._matches.setText(str(text or ""))

    def set_search_modes(self, modes: Sequence[str]) -> None:
        desired = SearchModeController.normalize_modes(modes)
        current = SearchModeController.normalized_mode(self._mode.currentData() or "local")
        self._mode.blockSignals(True)
        self._mode.clear()
        if "local" in desired:
            self._mode.addItem(_ui_label(self._ui_labels, "search.mode.local", "In document"), "local")
        if "global" in desired:
            self._mode.addItem(_ui_label(self._ui_labels, "search.mode.global", "Everywhere"), "global")
        idx = self._mode.findData(current)
        self._mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._mode.setVisible(self._mode.count() > 1)
        self._mode.blockSignals(False)
        self._on_search_mode_changed()

    def _search_mode(self) -> str:
        return SearchModeController.normalized_mode(self._mode.currentData() or "local")

    def _on_search_mode_changed(self) -> None:
        state = MainTextPanelSearchFlowController.mode_ui_state(
            mode=self._search_mode(),
            has_matches=bool(self._match_cursors),
            global_results_visible=self._global_results_visible,
        )
        match_nav_enabled = bool(state.get("match_nav_enabled"))
        self._prev_btn.setVisible(bool(state.get("show_match_nav")))
        self._next_btn.setVisible(bool(state.get("show_match_nav")))
        self._prev_btn.setEnabled(match_nav_enabled)
        self._next_btn.setEnabled(match_nav_enabled)
        self._search.setPlaceholderText(
            _ui_label(
                self._ui_labels,
                str(state.get("placeholder_key", "search.placeholder.local")),
                str(state.get("placeholder_default", "Search in text...")),
            )
        )
        if bool(state.get("reset_local_search")):
            # Avoid leaving stale local highlighting when switching to global modes.
            self._reset_search_state(clear_query=False)
        elif bool(state.get("clear_global_results")):
            self.clear_global_search_results()

    def _submit_search(self) -> None:
        action, query = MainTextPanelSearchFlowController.submit_request(
            mode=self._search_mode(),
            query=self._search.text(),
        )
        if action == "run_local":
            self._run_search()
            return
        if action == "clear_global":
            self._clear_search()
            return
        self.globalSearchRequested.emit(query, self._search_mode())

    def _clear_search(self) -> None:
        action, has_query = MainTextPanelSearchFlowController.clear_request(
            mode=self._search_mode(),
            query=self._search.text(),
        )
        if action == "reset_local":
            self._reset_search_state(clear_query=True)
            return
        if has_query:
            self._search.setText("")
        self._matches.setText("")
        self.globalSearchCleared.emit()

    def select_version_alias(self, alias: str) -> None:
        target = MainTextPanelNavigationController.alias_tab_index(
            versions=self._versions,
            global_results_visible=self._global_results_visible,
            alias=alias,
        )
        if target is None:
            return
        if 0 <= int(target) < self._tabs.count():
            self._tabs.setCurrentIndex(int(target))

    def select_version(self, *, stage_id: str = "", alias: str = "", kind: str = "") -> None:
        target = MainTextPanelNavigationController.version_tab_index(
            versions=self._versions,
            global_results_visible=self._global_results_visible,
            stage_id=stage_id,
            alias=alias,
            kind=kind,
        )
        if target is None:
            return
        if 0 <= int(target) < self._tabs.count():
            self._tabs.setCurrentIndex(int(target))

    def _rebuild_tabs(self, *, prefer_results: bool = False) -> None:
        results_title = _ui_label(self._ui_labels, "search.tab.results", "Search Results")
        text_title = _ui_label(self._ui_labels, "search.tab.text", "Text")
        prev_title = ""
        try:
            titles = [str(self._tabs.tabText(i) or "") for i in range(self._tabs.count())]
            prev_title = ArtifactTabsController.previous_title(titles, int(self._tabs.currentIndex()))
        except RuntimeError as exc:
            _LOG.debug("artifact_tabs_previous_title_failed error=%s", exc)
            prev_title = ""
        ArtifactTabsViewController.rebuild_tabs(
            self._tabs,
            versions=self._versions,
            global_results_visible=self._global_results_visible,
            results_title=results_title,
            text_title=text_title,
            pinned_aliases=self._pinned_aliases,
            active_aliases=self._active_aliases,
            previous_title=prev_title,
            prefer_results=prefer_results,
            make_results_view=self._make_results_view,
            make_text_view=lambda: self._make_editor(""),
            make_artifact_view=lambda art: _LazyArtifactView(
                lambda _art=art: self._make_artifact_view(_art),
                self._tabs,
            ),
            set_tab_tooltip=lambda index, tooltip: self._tabs.setTabToolTip(index, tooltip),
        )
        self._ensure_current_tab_loaded()

    def _rebuild_kind_bar(self, *, active_kind: str = "") -> None:
        self._clear_layout(self._kind_rows_layout)
        self._kind_rows = {}
        if not self._kinds:
            self._kind_rows_host.setVisible(False)
            return
        kind_rows, resolved_active_kind, visible = ArtifactKindBarViewController.rebuild_rows(
            kinds=self._kinds,
            current_active_kind=active_kind or self._active_kind,
            kind_titles={kind: _ui_label(self._ui_labels, f"kind.{kind}", kind) for kind in self._kinds},
            artifacts_by_kind=self._artifacts_by_kind,
            pinned_aliases=self._pinned_aliases,
            create_row=lambda: _ArtifactKindRow(self._kind_rows_host),
            add_row=lambda row: self._kind_rows_layout.addWidget(row, 0),
            connect_row_signals=lambda row: (
                row.versionSelected.connect(self._on_kind_version_selected),
                row.kindContextRequested.connect(self._on_kind_context_requested),
                row.versionContextRequested.connect(self._on_kind_version_context_requested),
            ),
        )
        self._kind_rows_host.setVisible(bool(visible))
        self._kind_rows = kind_rows
        self._active_kind = resolved_active_kind
        self._update_kind_rows_selection()

    def _activate_kind(self, kind: str) -> None:
        state = MainTextPanelSelectionController.activate_kind_selection(
            kind=kind,
            kinds=list(self._kinds),
            active_kind=self._active_kind,
            artifacts_by_kind=self._artifacts_by_kind,
            global_results_visible=self._global_results_visible,
        )
        if not state.active_kind:
            return
        if state.update_kind_rows_only:
            self._update_kind_rows_selection()
            return
        self._active_kind = state.active_kind
        self._versions = list(state.versions)
        self._rebuild_tabs()
        self._reset_search_state(clear_query=False)
        if state.emit_selection:
            self._emit_current_selection()
        self._update_kind_rows_selection()

    def _on_kind_version_selected(self, kind: str, version_index: int) -> None:
        selected_kind = str(kind or "").strip()
        if not selected_kind or selected_kind not in self._kinds:
            return
        state = MainTextPanelSelectionController.activate_kind_selection(
            kind=selected_kind,
            kinds=list(self._kinds),
            active_kind=self._active_kind,
            artifacts_by_kind=self._artifacts_by_kind,
            global_results_visible=self._global_results_visible,
            version_index=version_index,
        )
        if not state.active_kind:
            return
        if not state.update_kind_rows_only:
            self._active_kind = state.active_kind
            self._versions = list(state.versions)
            self._rebuild_tabs()
            self._reset_search_state(clear_query=False)
        target = state.target_tab_index
        if 0 <= target < self._tabs.count():
            self._tabs.setCurrentIndex(target)
        if state.emit_selection:
            self._emit_current_selection()
        self._update_kind_rows_selection()

    def _on_kind_context_requested(self, kind: str, global_pos: QPoint) -> None:
        selected_kind = str(kind or "").strip()
        if not selected_kind:
            return
        self.artifactKindContextRequested.emit(selected_kind, global_pos)

    def _on_kind_version_context_requested(self, kind: str, version_index: int, global_pos: QPoint) -> None:
        stage_id, alias, kind_value = ArtifactSelectionController.kind_version_context_payload(
            self._artifacts_by_kind,
            kind=kind,
            version_index=version_index,
        )
        if not stage_id or not alias:
            return
        self.artifactVersionContextRequested.emit(stage_id, alias, kind_value, global_pos)

    def _update_kind_rows_selection(self) -> None:
        version_idx = self._tab_to_version_index(int(self._tabs.currentIndex()))
        for kind, row in self._kind_rows.items():
            row.set_selected_index(
                ArtifactKindBarController.selected_version_index(
                    row_kind=kind,
                    active_kind=self._active_kind,
                    version_index=version_idx,
                )
            )

    @staticmethod
    def _clear_layout(layout: QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout is not None:
                MainTextPanelV2._clear_layout(child_layout)

    def _tab_to_version_index(self, tab_index: int) -> int | None:
        return ArtifactTabNavigationController.tab_to_version_index(
            int(tab_index),
            global_results_visible=self._global_results_visible,
            versions_count=len(self._versions),
        )

    def _on_version_tab_changed(self, tab_index: int) -> None:
        self._ensure_current_tab_loaded()
        stage_id, alias, kind = MainTextPanelSelectionController.current_selection_payload(
            versions=list(self._versions),
            tab_index=int(tab_index),
            global_results_visible=self._global_results_visible,
        )
        if not (stage_id and alias):
            self._refresh_export_controls()
            return
        self.activeVersionChanged.emit(stage_id, alias)
        self.artifactSelectionChanged.emit(stage_id, alias, kind)
        self._refresh_export_controls()

    def _ensure_current_tab_loaded(self) -> None:
        widget = self._tabs.currentWidget()
        if isinstance(widget, _LazyArtifactView):
            widget.ensure_loaded()

    def _emit_current_selection(self) -> None:
        stage_id, alias, kind = MainTextPanelSelectionController.current_selection_payload(
            versions=list(self._versions),
            tab_index=int(self._tabs.currentIndex()),
            global_results_visible=self._global_results_visible,
        )
        if stage_id and alias and kind:
            self.artifactSelectionChanged.emit(stage_id, alias, kind)

    def _on_tabs_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        tab = self._tabs.tabBar().tabAt(pos)
        actions = ArtifactSelectionController.pin_menu_actions_for_tab(
            self._versions,
            tab_index=int(tab),
            global_results_visible=self._global_results_visible,
            pinned_aliases=self._pinned_aliases,
        )
        if not actions:
            return

        menu = QMenu(self)
        for spec in actions:
            if spec.action == "pin":
                menu.addAction(spec.label).triggered.connect(
                    lambda _checked=False, _stage=spec.stage_id, _alias=spec.alias: self.pinRequested.emit(_stage, _alias)
                )
                continue
            menu.addAction(spec.label).triggered.connect(
                lambda _checked=False, _stage=spec.stage_id: self.unpinRequested.emit(_stage)
            )
        menu.exec(self._tabs.tabBar().mapToGlobal(pos))

    def set_logs(self, log_service: LogService) -> None:
        self._latest_logs_text, self._latest_logs_count = LogsBufferController.update_buffer(
            list(log_service.get_all_logs()),
            current_text=self._latest_logs_text,
            current_count=self._latest_logs_count,
        )

    def _show_logs_dialog(self) -> None:
        dialog = _LogsDialog(self, labels=self._ui_labels)
        dialog.set_logs(self._latest_logs_text)
        dialog.exec()

    def set_audio_path(self, audio_path: str) -> None:
        next_path = str(audio_path or "").strip()
        if next_path == self._current_audio_path:
            return
        self._current_audio_path = next_path
        self._release_audio_source()
        self._set_audio_enabled(bool(self._current_audio_path))

    def _set_audio_enabled(self, enabled: bool) -> None:
        AudioPlaybackController.set_audio_enabled(
            (self._btn_play, self._btn_pause, self._btn_stop, self._slider, self._audio_bar),
            enabled,
        )

    def set_ui_labels(self, labels: dict[str, str] | None) -> None:
        if isinstance(labels, dict):
            self._ui_labels.update({str(k): str(v) for k, v in labels.items()})
        self._apply_command_icons()
        current_modes: list[str] = []
        for idx in range(self._mode.count()):
            mode = str(self._mode.itemData(idx) or "").strip()
            if mode:
                current_modes.append(mode)
        self.set_search_modes(current_modes or ["local"])
        self._rebuild_kind_bar(active_kind=self._active_kind)
        self._refresh_export_controls()

    def _refresh_export_controls(self) -> None:
        has_targets = bool(self._artifact_export_buttons)
        self._ensure_current_tab_loaded()
        editor = self._current_editor()
        text = str(editor.toPlainText() or "") if editor is not None else ""
        state = ArtifactToolbarController.export_controls_state_for_tab(
            versions=self._versions,
            tab_index=int(self._tabs.currentIndex()),
            global_results_visible=self._global_results_visible,
            has_targets=has_targets,
            text=text,
        )
        self._copy_btn.setEnabled(bool(state.get("copy_enabled")))
        self._copy_all_btn.setEnabled(bool(state.get("copy_enabled")))
        self._copy_html_btn.setEnabled(bool(state.get("copy_enabled")))
        self._export_buttons_host.setVisible(bool(state.get("host_visible")))
        for button in self._artifact_export_buttons:
            button.setEnabled(bool(state.get("export_enabled")))

    def _current_artifact_identity(self) -> tuple[str, str, str]:
        return ArtifactToolbarController.current_artifact_identity(
            self._versions,
            tab_index=int(self._tabs.currentIndex()),
            global_results_visible=self._global_results_visible,
        )

    def _copy_current_text(self) -> None:
        self._ensure_current_tab_loaded()
        editor = self._current_editor()
        if editor is None:
            return
        text = ArtifactToolbarController.copyable_text(
            str(editor.textCursor().selectedText() or ""),
            str(editor.toPlainText() or ""),
        )
        if not text:
            return
        QApplication.clipboard().setText(text)

    def _copy_all_text(self) -> None:
        self._ensure_current_tab_loaded()
        editor = self._current_editor()
        if editor is None:
            return
        text = str(editor.toPlainText() or "")
        if not text:
            return
        QApplication.clipboard().setText(text)

    def _copy_current_text_as_html(self) -> None:
        self._ensure_current_tab_loaded()
        editor = self._current_editor()
        if editor is None:
            return
        source_text = ArtifactToolbarController.copyable_text(
            str(editor.textCursor().selectedText() or ""),
            str(editor.toPlainText() or ""),
        )
        if not source_text:
            return
        document = QTextDocument()
        document.setMarkdown(str(source_text))
        mime = QMimeData()
        mime.setHtml(document.toHtml())
        mime.setText(document.toPlainText())
        clipboard = QApplication.clipboard()
        clipboard.setMimeData(mime)

    def _emit_artifact_export_request_for_target(self, plugin_id: str, action_id: str) -> None:
        if not plugin_id or not action_id:
            return
        self._ensure_current_tab_loaded()
        editor = self._current_editor()
        if editor is None:
            return
        payload = ArtifactToolbarController.export_request_payload_for_tab(
            versions=self._versions,
            tab_index=int(self._tabs.currentIndex()),
            global_results_visible=self._global_results_visible,
            plugin_id=plugin_id,
            action_id=action_id,
            text=str(editor.toPlainText() or ""),
        )
        if not payload:
            return
        self.artifactTextExportRequested.emit(*payload)

    def _rebuild_export_buttons(self) -> None:
        self._clear_layout(self._export_buttons_layout)
        self._artifact_export_buttons = []
        specs = ArtifactExportButtonsController.build_specs(
            self._artifact_export_targets,
            export_label=_ui_label(self._ui_labels, "search.export", "Export"),
        )
        for spec in specs:
            button = QToolButton(self._export_buttons_host)
            _configure_icon_button(button)
            button.setIcon(
                self._build_export_target_icon(
                    label=spec.label,
                    plugin_id=spec.plugin_id,
                    icon_hint=spec.icon_hint,
                )
            )
            button.setToolTip(spec.tooltip)
            button.clicked.connect(
                lambda _checked=False, _pid=spec.plugin_id, _aid=spec.action_id: self._emit_artifact_export_request_for_target(
                    _pid, _aid
                )
            )
            self._export_buttons_layout.addWidget(button, 0)
            self._artifact_export_buttons.append(button)

    def _apply_command_icons(self) -> None:
        for spec in ToolbarIconController.command_button_specs():
            button = getattr(self, spec.button_name, None)
            if not isinstance(button, QToolButton):
                continue
            button.setText("")
            button.setIcon(self._draw_toolbar_icon(spec.icon_kind))
            button.setToolTip(_ui_label(self._ui_labels, spec.tooltip_key, spec.tooltip_default))
        self._rebuild_export_buttons()

    def _toolbar_icon_color(self) -> QColor:
        app = QApplication.instance()
        theme_id = str(app.property("aimn_theme_id") or "").strip().lower() if app is not None else ""
        palette = self.palette()
        window = palette.color(QPalette.Window)
        lightness = int(window.lightness()) if window.isValid() else 255
        return ToolbarIconController.toolbar_icon_color(
            theme_id=theme_id,
            palette_lightness=lightness,
        )

    def _draw_toolbar_icon(self, kind: str, *, glyph: str = "") -> QIcon:
        return ToolbarIconController.draw_toolbar_icon(
            kind,
            color=self._toolbar_icon_color(),
            glyph=glyph,
            icon_size=_ICON_SIZE,
        )

    def _build_export_target_icon(self, *, label: str, plugin_id: str, icon_hint: str = "") -> QIcon:
        glyph = ToolbarIconController.export_target_glyph(label)
        if str(icon_hint or "").strip():
            return self._draw_toolbar_icon("target", glyph=glyph)
        return self._draw_toolbar_icon("target", glyph=glyph)

    def _make_artifact_view(self, art: ArtifactItem) -> QWidget:
        kind = str(getattr(art, "kind", "") or "").strip()
        if kind != "transcript":
            return self._make_editor(self._artifact_text_provider(art.relpath))
        transcript_data = ArtifactViewDataController.build_transcript_artifact_data(
            stage_id=str(getattr(art, "stage_id", "") or "").strip(),
            alias=str(getattr(art, "alias", "") or "").strip(),
            relpath=str(getattr(art, "relpath", "") or "").strip(),
            segments_relpaths=self._segments_relpaths,
            load_segments_records=self._load_segments_records,
            load_artifact_text=self._artifact_text_provider,
            transcript_suggestions_for_alias=self._transcript_suggestions_for_alias,
            build_segment_text_ranges=self._build_segment_text_ranges,
            build_transcript_suggestion_spans=self._build_transcript_suggestion_spans,
        )
        if transcript_data is None:
            return self._make_editor(self._artifact_text_provider(art.relpath))
        return self._make_transcript_segments_view(
            transcript_data.records,
            transcript_text=transcript_data.transcript_text,
            suggestion_spans=transcript_data.suggestion_spans,
        )

    def _make_editor(self, text: str) -> QPlainTextEdit:
        return TextEditorController.build_readonly_plain_text(text)

    def _make_results_view(self) -> QWidget:
        return ResultsViewController.build_view(
            query=self._global_results_query,
            rows=list(self._global_results_rows),
            answer_text=str(self._global_results_answer or "").strip(),
            callbacks=ResultsViewCallbacks(
                editor_factory=_TranscriptTextEdit,
                apply_editor_term_highlights=self._apply_editor_term_highlights,
                highlight_range=lambda editor, left, right, terms: self._highlight_transcript_range(
                    editor,
                    int(left),
                    int(right),
                    terms=terms,
                ),
                emit_open=lambda args: self.globalSearchOpenRequested.emit(*args),
            ),
        )

    def _build_global_results_rows(self, query: str, hits: list[dict]) -> list[dict]:
        return GlobalSearchResultsController.build_rows(query, hits)

    @staticmethod
    def _result_payload_from_hit(hit: dict) -> dict:
        return GlobalSearchResultsController.result_payload_from_hit(hit)

    def _result_excerpt_from_hit(self, hit: dict, _query: str, *, terms: Sequence[str] | None = None) -> str:
        return GlobalSearchResultsController.result_excerpt_from_hit(hit, terms=terms)

    def _resolve_hit_content(self, hit: dict) -> str:
        return GlobalSearchResultsController.resolve_hit_content(hit)

    @staticmethod
    def _normalized_result_content(value: object) -> str:
        return GlobalSearchResultsController.normalized_result_content(value)

    @staticmethod
    def _is_missing_text(value: str) -> bool:
        return GlobalSearchResultsController.is_missing_text(value)

    @staticmethod
    def _sentence_window(text: str, terms: Sequence[str]) -> str:
        return GlobalSearchResultsController.sentence_window(text, terms)

    @staticmethod
    def _marked_terms_from_snippet(snippet: str) -> list[str]:
        return GlobalSearchResultsController.marked_terms_from_snippet(snippet)

    @staticmethod
    def _snippet_terms_for_highlight(snippet: str) -> list[str]:
        # Backward-compatible alias for older call sites.
        return MainTextPanelV2._marked_terms_from_snippet(snippet)

    @staticmethod
    def _dedupe_terms(terms: Sequence[str], *, min_len: int = 1, max_terms: int = 40) -> list[str]:
        return GlobalSearchResultsController.dedupe_terms(terms, min_len=min_len, max_terms=max_terms)

    @staticmethod
    def _search_terms_from_query(query: str) -> list[str]:
        return GlobalSearchResultsController.search_terms_from_query(query)

    @staticmethod
    def _query_lexemes(query: str) -> list[str]:
        return GlobalSearchResultsController.query_lexemes(query)

    def _apply_editor_term_highlights(self, editor: TextEditorWidget, terms: Sequence[str]) -> None:
        wanted = MainTextPanelV2._dedupe_terms(list(terms or []), min_len=1, max_terms=48)
        self._set_editor_layer_selections(
            editor,
            "search",
            TextSearchHighlightController.build_term_highlight_selections(editor, wanted),
        )

    def _extract_text_editor(self, widget: QWidget | None) -> TextEditorWidget | None:
        return TextEditorController.extract_text_editor(widget)

    def _current_editor(self) -> TextEditorWidget | None:
        return self._extract_text_editor(self._tabs.currentWidget())

    @staticmethod
    def _ms_to_hhmmss(ms: int) -> str:
        return TranscriptEvidenceController.ms_to_hhmmss(ms)

    def _load_segments_records(self, relpath: str) -> list[dict]:
        return self._transcript_evidence_controller.load_segments_records(relpath)

    @staticmethod
    def _editor_layer_attr(layer: str) -> str:
        return TextSearchHighlightController.editor_layer_attr(layer)

    def _editor_layer_selections(self, editor: TextEditorWidget, layer: str) -> list[QTextEdit.ExtraSelection]:
        return TextSearchHighlightController.editor_layer_selections(editor, layer)

    def _set_editor_layer_selections(
        self,
        editor: TextEditorWidget,
        layer: str,
        selections: Sequence[QTextEdit.ExtraSelection] | None,
    ) -> None:
        TextSearchHighlightController.set_editor_layer_selections(editor, layer, selections)

    def _refresh_editor_extra_selections(self, editor: TextEditorWidget) -> None:
        TextSearchHighlightController.refresh_editor_extra_selections(editor)

    def _transcript_suggestions_for_alias(self, alias: str) -> list[dict]:
        return self._transcript_evidence_controller.transcript_suggestions_for_alias(
            self._management_suggestions,
            alias,
        )

    @staticmethod
    def _build_transcript_suggestion_spans(
        records: list[dict],
        ranges: list[tuple[int, int] | None],
        suggestions: Sequence[dict],
    ) -> list[_TranscriptSuggestionSpan]:
        return TranscriptEvidenceController.build_transcript_suggestion_spans(records, ranges, suggestions)

    @staticmethod
    def _management_overlay_selections(
        editor: TextEditorWidget,
        spans: Sequence[_TranscriptSuggestionSpan],
    ) -> list[QTextEdit.ExtraSelection]:
        return TranscriptHighlightController.management_overlay_selections(editor, spans)

    @staticmethod
    def _suggestion_span_at_position(
        spans: Sequence[_TranscriptSuggestionSpan],
        position: int,
    ) -> _TranscriptSuggestionSpan | None:
        return TranscriptViewModelController.suggestion_span_at_position(spans, position)

    def _make_transcript_segments_view(
        self,
        records: list[dict],
        *,
        transcript_text: str = "",
        suggestion_spans: Sequence[_TranscriptSuggestionSpan] | None = None,
    ) -> QWidget:
        return TranscriptSegmentsViewController.build_view(
            records,
            transcript_text=transcript_text,
            suggestion_spans=suggestion_spans,
            callbacks=TranscriptSegmentsViewCallbacks(
                editor_factory=_TranscriptTextEdit,
                format_ms=self._ms_to_hhmmss,
                highlight_transcript_range=self._highlight_transcript_range,
                seek_ms=self._seek_ms,
                play=self._play,
                current_artifact_identity=self._current_artifact_identity,
                selection_evidence_payload=self._selection_evidence_payload,
                suggestion_span_at_position=self._suggestion_span_at_position,
                label_text=lambda key, default: _ui_label(self._ui_labels, key, default),
                emit_create_requested=lambda entity_type, payload: self.transcriptManagementCreateRequested.emit(
                    entity_type,
                    payload,
                ),
                emit_suggestion_action_requested=lambda action_name, payload: self.transcriptManagementSuggestionActionRequested.emit(
                    action_name,
                    payload,
                ),
                set_editor_layer_selections=self._set_editor_layer_selections,
                management_overlay_selections=self._management_overlay_selections,
                find_segment_row_for_cursor=self._find_segment_row_for_cursor,
                find_segment_row_by_timestamp=self._find_segment_row_by_timestamp,
                build_segment_text_ranges=self._build_segment_text_ranges,
            ),
        )

    @staticmethod
    def _build_segment_text_ranges(transcript_text: str, records: list[dict]) -> list[tuple[int, int] | None]:
        return TranscriptEvidenceController.build_segment_text_ranges(transcript_text, records)

    @staticmethod
    def _find_segment_row_for_cursor(position: int, ranges: list[tuple[int, int] | None]) -> int:
        return TranscriptEvidenceController.find_segment_row_for_cursor(position, ranges)

    @staticmethod
    def _selection_evidence_payload(
        cursor: QTextCursor,
        ranges: list[tuple[int, int] | None],
        records: list[dict],
    ) -> dict[str, object]:
        return TranscriptEvidenceController.selection_evidence_payload(cursor, ranges, records)

    @staticmethod
    def _find_segment_row_by_timestamp(records: list[dict], seconds: float) -> int:
        return TranscriptEvidenceController.find_segment_row_by_timestamp(records, seconds)

    @staticmethod
    def _line_text_at_position(editor: TextEditorWidget, position: int) -> str:
        return TranscriptSyncController.line_text_at_position(editor, position)

    @staticmethod
    def _highlight_transcript_range(
        editor: TextEditorWidget,
        start: int,
        end: int,
        *,
        terms: Sequence[str] | None = None,
    ) -> None:
        left = max(0, min(int(start), len(editor.toPlainText())))
        TextSearchHighlightController.set_editor_layer_selections(
            editor,
            "focus",
            TranscriptHighlightController.focus_range_selections(
                editor,
                start=start,
                end=end,
                terms=terms,
            ),
        )
        caret = editor.textCursor()
        caret.setPosition(left)
        editor.setTextCursor(caret)
        editor.ensureCursorVisible()

    def _run_search(self) -> None:
        query = self._search.text().strip()
        editor = self._current_editor()
        self._reset_search_state(clear_query=False)
        if not editor or not query:
            self._reset_search_state()
            return
        result = LocalSearchFlowController.run_search(
            editor,
            query,
            no_matches_text=_ui_label(self._ui_labels, "search.matches.none", "0 matches"),
        )
        self._match_cursors = list(result.match_cursors)
        self._match_index = int(result.match_index)
        self._matches.setText(result.matches_text)
        self._prev_btn.setEnabled(result.prev_enabled)
        self._next_btn.setEnabled(result.next_enabled)
        self._highlight_all(editor)

    def _highlight_all(self, editor: TextEditorWidget) -> None:
        self._set_editor_layer_selections(
            editor,
            "search",
            TextSearchHighlightController.build_search_highlight_selections(editor, self._match_cursors),
        )

    def _reset_search_state(self, *, clear_query: bool = True) -> None:
        self._match_cursors = []
        self._match_index = -1
        plan = LocalSearchFlowController.reset_plan(
            clear_query=clear_query,
            is_local_mode=self._search_mode() == "local",
            global_results_visible=self._global_results_visible,
            current_tab_index=int(self._tabs.currentIndex()),
        )
        if plan.clear_query:
            self._search.setText("")
        if self._search_mode() == "local":
            self._matches.setText(plan.matches_text)
        self._prev_btn.setEnabled(plan.prev_enabled)
        self._next_btn.setEnabled(plan.next_enabled)
        editor = self._current_editor()
        if editor:
            if plan.clear_search_layer:
                self._set_editor_layer_selections(editor, "search", [])
            if plan.clear_focus_layer:
                self._set_editor_layer_selections(editor, "focus", [])

    def _step_match(self, delta: int) -> None:
        editor = self._current_editor()
        if not editor or not self._match_cursors:
            return
        result = LocalSearchFlowController.step_match(
            editor,
            self._match_cursors,
            self._match_index,
            delta,
        )
        if result is None:
            return
        self._match_index = int(result.match_index)
        self._matches.setText(result.matches_text)

    def _apply_match_selection(self, editor: TextEditorWidget) -> None:
        outcome = TextSearchHighlightController.apply_match_selection(
            editor,
            self._match_cursors,
            self._match_index,
        )
        if not outcome:
            return
        current, total = outcome
        self._matches.setText(f"{current}/{total}")

    def _play(self) -> None:
        if self._ensure_audio_source_loaded():
            self._player.play()

    def _pause(self) -> None:
        self._player.pause()

    def _stop(self) -> None:
        self._release_audio_source()

    def _seek_ms(self, ms: int) -> None:
        if not self._ensure_audio_source_loaded():
            return
        try:
            self._player.setPosition(int(ms))
        except RuntimeError as exc:
            _LOG.debug("audio_seek_failed ms=%s error=%s", ms, exc)
            return

    def _ensure_audio_source_loaded(self) -> bool:
        ok, loaded_path = AudioPlaybackController.ensure_audio_source_loaded(
            self._player,
            self._current_audio_path,
            self._loaded_audio_path,
        )
        self._loaded_audio_path = loaded_path
        return ok

    def _release_audio_source(self) -> None:
        self._loaded_audio_path = AudioPlaybackController.release_audio_source(self._player, self._slider)

    def _on_duration(self, duration: int) -> None:
        AudioPlaybackController.set_duration(self._slider, duration)

    def _on_position(self, position: int) -> None:
        AudioPlaybackController.sync_position(self._slider, position)

def _extract_timestamp_seconds(text: str) -> float | None:
    return TranscriptSyncController.extract_timestamp_seconds(text)


class MeetingsWorkspaceV2(QWidget):
    """
    UI v2 layout (docs/UI.txt):
    - Top: Pipeline panel (fixed tiles + single RUN + expand-down stage settings)
    - Below: History | Artifacts | Main Text/Content
    """

    def __init__(
        self,
        pipeline_panel: PipelinePanelV2,
        history_panel: HistoryPanelV2,
        inspection_panel: QWidget,
        text_panel: MainTextPanelV2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline_panel = pipeline_panel
        self._history_panel = history_panel
        self._inspection_panel = inspection_panel
        self._text_panel = text_panel
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(pipeline_panel, 0)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Left column: History + Artifacts stacked (docs/Backlog_my.txt).
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(history_panel, 1)
        # UI update: text inspection panel is removed from the workspace view.
        inspection_panel.setVisible(False)
        body_layout.addWidget(left, 0)

        text_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body_layout.addWidget(text_panel, 1)

        layout.addWidget(body, 1)

    def set_ui_labels(self, labels: dict[str, str] | None) -> None:
        payload = dict(labels or {})
        if hasattr(self._pipeline_panel, "set_ui_labels"):
            self._pipeline_panel.set_ui_labels(payload)
        if hasattr(self._history_panel, "set_ui_labels"):
            self._history_panel.set_ui_labels(payload)
        if hasattr(self._inspection_panel, "set_ui_labels"):
            self._inspection_panel.set_ui_labels(payload)
        if hasattr(self._text_panel, "set_ui_labels"):
            self._text_panel.set_ui_labels(payload)
