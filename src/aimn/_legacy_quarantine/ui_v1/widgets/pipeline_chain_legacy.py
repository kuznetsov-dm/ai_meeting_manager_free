from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QFileDialog,
    QBoxLayout,
    QButtonGroup,
)

from aimn.ui.tabs.contracts import SettingField, StageViewModel, inline_fields_from_schema


_STATUS_COLORS = {
    "idle": QColor("#9CA3AF"),
    "ready": QColor("#2563EB"),
    "running": QColor("#2563EB"),
    "completed": QColor("#16A34A"),
    "failed": QColor("#DC2626"),
    "skipped": QColor("#F59E0B"),
    "dirty": QColor("#D97706"),
    "blocked": QColor("#6B7280"),
    "disabled": QColor("#9CA3AF"),
}


_STAGE_ICON_MAP = {
    "input": QStyle.SP_DialogOpenButton,
    "media_convert": QStyle.SP_BrowserReload,
    "transcription": QStyle.SP_MediaPlay,
    "llm_processing": QStyle.SP_ComputerIcon,
    "management": QStyle.SP_FileIcon,
    "service": QStyle.SP_DriveNetIcon,
}


# UI.txt sizing targets (px) for 1200x700 default layout.
# Pipeline chain has no scrollbars; tiles must remain shrinkable to avoid forcing
# a larger-than-allowed main window.
_PIPELINE_TOOLBAR_HEIGHT = 32
_PIPELINE_TILES_ROW_HEIGHT_H = 114

# Horizontal tiles: fixed height, scalable width.
_PIPELINE_PANEL_HEIGHT_H = 146
_TILE_HEIGHT_H = 110
_TILE_WIDTHS_H = {"collapsed": 88, "mini": 260, "full": 420}
_TILE_MIN_WIDTHS_H = {"collapsed": 64, "mini": 140, "full": 180}

_TILE_WIDTH_V = 320
_TILE_HEIGHTS_V = {"collapsed": 52, "mini": 140, "full": 220}
_TILE_MIN_HEIGHTS_V = {"collapsed": 44, "mini": 60, "full": 80}


class PipelineChainBarWidget(QWidget):
    stageSelected = Signal(str)
    stageSettingsChanged = Signal(str, dict)
    runFromStageRequested = Signal(str)
    rerunStageRequested = Signal(str)
    openOutputRequested = Signal(str)
    orientationChanged = Signal(str)
    stagePresentationChanged = Signal(str, bool, str)
    stageDisabledChanged = Signal(str, bool)
    presetChanged = Signal(str)
    presentation_changed = Signal()
    inputFilesChanged = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tiles: Dict[str, StageTileWidget] = {}
        self._stage_states: Dict[str, dict] = {}
        self._orientation = "horizontal"

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._toolbar_widget = QWidget()
        toolbar = QHBoxLayout(self._toolbar_widget)
        toolbar.setContentsMargins(8, 2, 8, 2)
        toolbar.setSpacing(8)
        self._toolbar_widget.setFixedHeight(_PIPELINE_TOOLBAR_HEIGHT)

        self._run_all_btn = QPushButton("Run All")
        self._run_all_btn.setFixedHeight(26)
        toolbar.addWidget(self._run_all_btn)

        self._preset_combo = QComboBox()
        self._preset_combo.setFixedHeight(26)
        self._preset_combo.addItem("Default", "default")
        self._preset_combo.addItem("Offline (Local)", "offline")
        self._preset_combo.currentIndexChanged.connect(self._emit_preset)
        toolbar.addWidget(self._preset_combo)

        toolbar.addStretch()

        self._stage_container = QWidget()
        self._row = QBoxLayout(QBoxLayout.LeftToRight, self._stage_container)
        self._row.setContentsMargins(8, 0, 8, 0)
        self._row.setSpacing(12)

        self._orientation_group = QButtonGroup(self)
        self._horizontal_btn = QToolButton()
        self._horizontal_btn.setText("Horizontal")
        self._horizontal_btn.setCheckable(True)
        self._horizontal_btn.setFixedSize(QSize(96, 26))
        self._vertical_btn = QToolButton()
        self._vertical_btn.setText("Vertical")
        self._vertical_btn.setCheckable(True)
        self._vertical_btn.setFixedSize(QSize(96, 26))
        self._orientation_group.setExclusive(True)
        self._orientation_group.addButton(self._horizontal_btn)
        self._orientation_group.addButton(self._vertical_btn)
        self._horizontal_btn.setChecked(True)
        self._horizontal_btn.clicked.connect(lambda: self.set_orientation("horizontal"))
        self._vertical_btn.clicked.connect(lambda: self.set_orientation("vertical"))
        toolbar.addWidget(self._horizontal_btn)
        toolbar.addWidget(self._vertical_btn)

        self._customize_btn = QToolButton()
        self._customize_btn.setText("Customize")
        self._customize_btn.setFixedHeight(26)
        toolbar.addWidget(self._customize_btn)

        self._root_layout.addWidget(self._toolbar_widget)
        self._root_layout.addWidget(self._stage_container, 1)
        self._apply_orientation_layout()

    def sizeHint(self) -> QSize:  # noqa: N802
        # Keep the dock from driving the main window into an oversized geometry.
        if self._orientation == "vertical":
            return QSize(_TILE_WIDTH_V + 16, 520)
        return QSize(1200, _PIPELINE_PANEL_HEIGHT_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        if self._orientation == "vertical":
            return QSize(_TILE_WIDTH_V + 16, 240)
        return QSize(520, _PIPELINE_PANEL_HEIGHT_H)

    def set_stages(self, stages: List[StageViewModel]) -> None:
        existing = {tile.stage_id for tile in self._tiles.values()}
        for stage in stages:
            if stage.stage_id in self._tiles:
                self._tiles[stage.stage_id].set_stage(stage)
                continue
            tile = StageTileWidget(stage)
            tile.selected.connect(self.stageSelected.emit)
            tile.settingsChanged.connect(self.stageSettingsChanged.emit)
            tile.runRequested.connect(self.runFromStageRequested.emit)
            tile.rerunRequested.connect(self.rerunStageRequested.emit)
            tile.openOutputRequested.connect(self.openOutputRequested.emit)
            tile.presentationChanged.connect(self._on_tile_presentation)
            tile.disableChanged.connect(self.stageDisabledChanged.emit)
            tile.filesChanged.connect(self._on_files_changed)
            tile.set_orientation(self._orientation)
            self._tiles[stage.stage_id] = tile
            self._row.addWidget(tile)
        removed = existing - {stage.stage_id for stage in stages}
        for stage_id in removed:
            tile = self._tiles.pop(stage_id)
            tile.setParent(None)
        self._apply_tile_sizes()

    def orientation(self) -> str:
        return self._orientation

    def set_orientation(self, orientation: str) -> None:
        normalized = "vertical" if orientation == "vertical" else "horizontal"
        if normalized == self._orientation:
            return
        self._orientation = normalized
        direction = QBoxLayout.TopToBottom if normalized == "vertical" else QBoxLayout.LeftToRight
        self._row.setDirection(direction)
        self._apply_orientation_layout()
        for tile in self._tiles.values():
            tile.set_orientation(normalized)
        self._sync_orientation_buttons()
        self.orientationChanged.emit(normalized)
        self.presentation_changed.emit()
        self._apply_tile_sizes()

    def _apply_orientation_layout(self) -> None:
        if self._orientation == "vertical":
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            # Account for the container layout margins (8px left + 8px right).
            self.setFixedWidth(_TILE_WIDTH_V + 16)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            # Clear horizontal fixed constraints from the horizontal layout mode.
            self._stage_container.setMinimumHeight(0)
            self._stage_container.setMaximumHeight(16777215)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setFixedHeight(_PIPELINE_PANEL_HEIGHT_H)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self._stage_container.setFixedHeight(_PIPELINE_TILES_ROW_HEIGHT_H)

    def set_stage_presentation(self, stage_id: str, visible: bool, density: str) -> None:
        tile = self._tiles.get(stage_id)
        if tile:
            tile.set_density(density)
            tile.setVisible(visible)
        self._stage_states[stage_id] = {"visible": visible, "density": density}
        self.presentation_changed.emit()
        self._apply_tile_sizes()

    def capture_presentation(self) -> Dict[str, dict]:
        for stage_id, tile in self._tiles.items():
            self._stage_states[stage_id] = {
                "visible": tile.isVisible(),
                "density": tile.density,
            }
        return dict(self._stage_states)

    def apply_presentation(self, states: Dict[str, dict]) -> None:
        for stage_id, state in states.items():
            visible = bool(state.get("visible", True))
            density = str(state.get("density", "full"))
            self.set_stage_presentation(stage_id, visible, density)
        self._apply_tile_sizes()

    def show_all_stages(self) -> None:
        for stage_id in self._tiles.keys():
            self.set_stage_presentation(stage_id, True, self._tiles[stage_id].density)

    def reset_presentation(self) -> None:
        for stage_id, tile in self._tiles.items():
            self.set_stage_presentation(stage_id, True, "mini")
        self._apply_tile_sizes()

    def run_all_button(self) -> QPushButton:
        return self._run_all_btn

    def set_preset(self, preset_id: str) -> None:
        index = self._preset_combo.findData(preset_id)
        if index >= 0:
            self._preset_combo.setCurrentIndex(index)

    def customize_button(self) -> QToolButton:
        return self._customize_btn

    def _on_tile_presentation(self, stage_id: str, visible: bool, density: str) -> None:
        self.set_stage_presentation(stage_id, visible, density)
        self.stagePresentationChanged.emit(stage_id, visible, density)

    def _emit_preset(self) -> None:
        preset_id = self._preset_combo.currentData()
        if preset_id:
            self.presetChanged.emit(str(preset_id))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_tile_sizes()

    def _apply_tile_sizes(self) -> None:
        visible_tiles = [tile for tile in self._tiles.values() if tile.isVisible()]
        if not visible_tiles:
            return

        # No-scroll sizing: we rely on layout stretch factors along the primary axis.
        # This keeps the chain shrinkable within the main window max size and avoids
        # "minimum size hint forces huge window" behavior.
        if self._orientation == "vertical":
            for tile in visible_tiles:
                tile.apply_fixed_size("vertical")
                self._row.setStretchFactor(tile, max(1, _TILE_HEIGHTS_V.get(tile.density, _TILE_HEIGHTS_V["mini"])))
            self._stage_container.setFixedWidth(_TILE_WIDTH_V + 16)
            self._stage_container.setMinimumHeight(0)
            self._stage_container.setMaximumHeight(16777215)
        else:
            for tile in visible_tiles:
                tile.apply_fixed_size("horizontal")
                self._row.setStretchFactor(tile, max(1, _TILE_WIDTHS_H.get(tile.density, _TILE_WIDTHS_H["mini"])))
            self._stage_container.setFixedHeight(_PIPELINE_TILES_ROW_HEIGHT_H)
            self._stage_container.setMinimumWidth(0)
            self._stage_container.setMaximumWidth(16777215)

    def _sync_orientation_buttons(self) -> None:
        for btn, active in (
            (self._horizontal_btn, self._orientation == "horizontal"),
            (self._vertical_btn, self._orientation == "vertical"),
        ):
            previous = btn.blockSignals(True)
            btn.setChecked(active)
            btn.blockSignals(previous)

    def _on_files_changed(self, files: list[str]) -> None:
        self.inputFilesChanged.emit(files)


@dataclass(frozen=True)
class _ControlSpec:
    key: str
    label: str
    kind: str
    options: List[Tuple[str, str]] = None
    editable: bool = False


class _ControlsForm(QWidget):
    settingChanged = Signal(str, object)

    def __init__(self, specs: List[_ControlSpec], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._specs = {spec.key: spec for spec in specs}
        self._widgets: Dict[str, QWidget] = {}
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for spec in specs:
            widget = self._build_widget(spec)
            self._widgets[spec.key] = widget
            if isinstance(widget, QCheckBox):
                layout.addRow(spec.label, widget)
            else:
                layout.addRow(QLabel(spec.label), widget)

    def set_values(self, values: dict) -> None:
        for key, widget in self._widgets.items():
            spec = self._specs[key]
            value = values.get(key)
            blocker = None
            try:
                blocker = widget.blockSignals(True)
                if isinstance(widget, QComboBox):
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    elif spec.editable:
                        widget.setCurrentText("" if value is None else str(value))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText("" if value is None else str(value))
                elif isinstance(widget, QLabel):
                    widget.setText("" if value is None else str(value))
            finally:
                if blocker is not None:
                    widget.blockSignals(False)

    def set_options(self, key: str, options: List[Tuple[str, str]]) -> None:
        widget = self._widgets.get(key)
        if not isinstance(widget, QComboBox):
            return
        widget.blockSignals(True)
        widget.clear()
        for label, value in options:
            widget.addItem(label, value)
        widget.blockSignals(False)

    def has_fields(self) -> bool:
        return bool(self._widgets)

    def _build_widget(self, spec: _ControlSpec) -> QWidget:
        options = spec.options or []
        if spec.kind == "combo":
            combo = QComboBox()
            combo.setEditable(spec.editable)
            combo.setFixedHeight(24)
            for label, value in options:
                combo.addItem(label, value)
            combo.currentIndexChanged.connect(lambda _=0, k=spec.key: self._emit(k))
            return combo
        if spec.kind == "toggle":
            box = QCheckBox()
            box.setFixedHeight(24)
            box.stateChanged.connect(lambda _=0, k=spec.key: self._emit(k))
            return box
        if spec.kind == "text":
            line = QLineEdit()
            line.setFixedHeight(24)
            line.editingFinished.connect(lambda k=spec.key, w=line: self._emit(k, w.text()))
            return line
        label = QLabel("")
        label.setObjectName("controlHint")
        return label

    def _emit(self, key: str, value: object | None = None) -> None:
        widget = self._widgets.get(key)
        if widget is None:
            return
        if value is None:
            if isinstance(widget, QComboBox):
                value = widget.currentData() or widget.currentText()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                value = widget.text()
            elif isinstance(widget, QLabel):
                value = widget.text()
        self.settingChanged.emit(key, value)


class _InlineStageControls(QWidget):
    settingsChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stage: StageViewModel | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._inline_row = InlineSettingsRow()
        self._advanced_form = _ControlsForm([])
        layout.addWidget(self._inline_row)
        layout.addWidget(self._advanced_form)
        self._advanced_form.setVisible(False)
        self._inline_row.settingsChanged.connect(self._emit_inline)
        self._advanced_form.settingChanged.connect(self._emit_advanced)

    def set_stage(self, stage: StageViewModel) -> None:
        self._stage = stage
        self._inline_row.set_fields(
            stage.settings_schema,
            stage.inline_settings_keys,
            stage.current_settings,
        )
        advanced_fields = [
            field for field in stage.settings_schema if field.key not in set(stage.inline_settings_keys)
        ][:4]
        specs = _specs_from_fields(advanced_fields)
        self._advanced_form = _ControlsForm(specs)
        self._advanced_form.settingChanged.connect(self._emit_advanced)
        self._advanced_form.set_values(stage.current_settings)
        layout = self.layout()
        if layout and layout.count() > 1:
            item = layout.itemAt(1)
            if item and item.widget():
                item.widget().setParent(None)
            layout.addWidget(self._advanced_form)

    def set_density(self, density: str) -> None:
        show_advanced = density == "full" and self._advanced_form.has_fields()
        self._advanced_form.setVisible(show_advanced)

    def _emit_inline(self, settings: dict) -> None:
        if settings:
            self.settingsChanged.emit(settings)

    def _emit_advanced(self, key: str, value: object) -> None:
        self.settingsChanged.emit({key: value})


class _FormStageControls(QWidget):
    settingsChanged = Signal(dict)

    def __init__(
        self,
        primary_specs: List[_ControlSpec],
        advanced_specs: List[_ControlSpec],
        *,
        hint_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._primary_form = _ControlsForm(primary_specs)
        self._advanced_form = _ControlsForm(advanced_specs)
        self._hint = QLabel(hint_text)
        self._hint.setWordWrap(True)
        self._hint.setObjectName("controlHint")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._primary_form)
        layout.addWidget(self._advanced_form)
        layout.addWidget(self._hint)
        self._advanced_form.setVisible(False)
        self._hint.setVisible(False)
        self._primary_form.settingChanged.connect(self._emit)
        self._advanced_form.settingChanged.connect(self._emit)

    def set_stage(self, stage: StageViewModel) -> None:
        values = dict(stage.current_settings)
        if stage.plugin_id:
            values.setdefault("plugin_id", stage.plugin_id)
        self._primary_form.set_values(values)
        self._advanced_form.set_values(values)

    def set_density(self, density: str) -> None:
        show_advanced = density == "full" and self._advanced_form.has_fields()
        self._advanced_form.setVisible(show_advanced)
        self._hint.setVisible(show_advanced and bool(self._hint.text().strip()))

    def set_options(self, key: str, options: List[Tuple[str, str]]) -> None:
        self._primary_form.set_options(key, options)
        self._advanced_form.set_options(key, options)

    def _emit(self, key: str, value: object) -> None:
        self.settingsChanged.emit({key: value})


class _ServiceStageControls(QWidget):
    settingsChanged = Signal(dict)
    openOutputRequested = Signal()

    def __init__(
        self,
        primary_specs: List[_ControlSpec],
        advanced_specs: List[_ControlSpec],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._primary_form = _ControlsForm(primary_specs)
        self._advanced_form = _ControlsForm(advanced_specs)
        self._open_btn = QToolButton()
        self._open_btn.setText("Open folder")
        self._open_btn.setFixedHeight(24)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._primary_form)
        layout.addWidget(self._open_btn)
        layout.addWidget(self._advanced_form)
        self._advanced_form.setVisible(False)
        self._primary_form.settingChanged.connect(self._emit)
        self._advanced_form.settingChanged.connect(self._emit)
        self._open_btn.clicked.connect(self.openOutputRequested.emit)

    def set_stage(self, stage: StageViewModel) -> None:
        values = dict(stage.current_settings)
        self._primary_form.set_values(values)
        self._advanced_form.set_values(values)

    def set_density(self, density: str) -> None:
        show_advanced = density == "full" and self._advanced_form.has_fields()
        self._advanced_form.setVisible(show_advanced)

    def _emit(self, key: str, value: object) -> None:
        self.settingsChanged.emit({key: value})


class _InputStageControls(QWidget):
    settingsChanged = Signal(dict)
    filesChanged = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._files: List[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._file_list = QListWidget()
        self._file_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self._file_list)

        actions = QHBoxLayout()
        self._add_btn = QPushButton("Select")
        self._remove_btn = QPushButton("Remove")
        self._clear_btn = QPushButton("Clear")
        for btn in (self._add_btn, self._remove_btn, self._clear_btn):
            btn.setFixedHeight(24)
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)

        self._info_label = QLabel("")
        self._info_label.setObjectName("fileInfo")
        layout.addWidget(self._info_label)

        advanced_box = QGroupBox("Input Settings")
        advanced_layout = QVBoxLayout(advanced_box)
        self._advanced_form = _ControlsForm(
            [
                _ControlSpec(
                    key="input_language",
                    label="Input language",
                    kind="combo",
                    options=[("auto", "auto"), ("manual", "manual")],
                    editable=True,
                ),
                _ControlSpec(
                    key="channel_mode",
                    label="Channel mode",
                    kind="combo",
                    options=[("auto", "auto"), ("mono", "mono"), ("stereo", "stereo")],
                ),
                _ControlSpec(
                    key="trim_silence",
                    label="Trim silence",
                    kind="toggle",
                ),
                _ControlSpec(
                    key="normalize_audio",
                    label="Audio normalization",
                    kind="toggle",
                ),
            ]
        )
        advanced_layout.addWidget(self._advanced_form)
        self._format_hint = QLabel("")
        self._format_hint.setWordWrap(True)
        self._format_hint.setObjectName("controlHint")
        advanced_layout.addWidget(self._format_hint)
        layout.addWidget(advanced_box)
        advanced_box.setVisible(False)
        self._advanced_box = advanced_box

        self._add_btn.clicked.connect(self._pick_files)
        self._remove_btn.clicked.connect(self._remove_selected)
        self._clear_btn.clicked.connect(self._clear)
        self._advanced_form.settingChanged.connect(self._emit_setting)

    def set_stage(self, stage: StageViewModel) -> None:
        files = stage.current_settings.get("files", [])
        self._set_files(files if isinstance(files, list) else [])
        self._advanced_form.set_values(stage.current_settings)
        hint = stage.ui_metadata.get("formats_hint") if isinstance(stage.ui_metadata, dict) else ""
        self._format_hint.setText(f"Supported formats: {hint}" if hint else "")

    def set_density(self, density: str) -> None:
        if density == "full":
            self._file_list.setFixedHeight(72)
            self._advanced_box.setVisible(True)
        else:
            self._file_list.setFixedHeight(48)
            self._advanced_box.setVisible(False)

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select files")
        if files:
            self._set_files(self._files + files)
            self.filesChanged.emit(list(self._files))

    def _remove_selected(self) -> None:
        selected = [item.text() for item in self._file_list.selectedItems()]
        if not selected:
            return
        remaining = [path for path in self._files if path not in selected]
        self._set_files(remaining)
        self.filesChanged.emit(list(self._files))

    def _clear(self) -> None:
        self._set_files([])
        self.filesChanged.emit([])

    def _set_files(self, files: List[str]) -> None:
        self._files = list(files)
        self._file_list.clear()
        for path in self._files:
            self._file_list.addItem(QListWidgetItem(path))
        if not self._files:
            self._info_label.setText("No files selected")
        elif len(self._files) == 1:
            name = self._files[0].split("\\")[-1]
            self._info_label.setText(f"File: {name} | Duration: n/a")
        else:
            name = self._files[0].split("\\")[-1]
            self._info_label.setText(f"Files: {len(self._files)} (first: {name}) | Duration: n/a")

    def _emit_setting(self, key: str, value: object) -> None:
        self.settingsChanged.emit({key: value})


class _LlmStageControls(QWidget):
    settingsChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._providers: List[Tuple[str, str]] = []
        self._models: List[Tuple[str, str]] = []
        self._selected_provider = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        primary_specs = [
            _ControlSpec("provider", "Provider", "combo"),
            _ControlSpec("model_id", "Model", "combo"),
            _ControlSpec(
                "task_preset",
                "Task preset",
                "combo",
                options=[("Summary", "summary"), ("Decisions", "decisions"), ("Topics", "topics")],
            ),
        ]
        self._primary_form = _ControlsForm(primary_specs)
        layout.addWidget(self._primary_form)

        advanced_specs = [
            _ControlSpec("prompt_profile", "Prompt profile", "combo"),
            _ControlSpec("temperature", "Temperature", "text"),
            _ControlSpec("max_tokens", "Max tokens", "text"),
            _ControlSpec(
                "context_strategy",
                "Context strategy",
                "combo",
                options=[("default", "default"), ("windowed", "windowed"), ("truncated", "truncated")],
            ),
            _ControlSpec(
                "retry_policy",
                "Retry policy",
                "combo",
                options=[("default", "default"), ("aggressive", "aggressive"), ("safe", "safe")],
            ),
            _ControlSpec("cost_estimate", "Cost estimate", "readonly"),
        ]
        self._advanced_form = _ControlsForm(advanced_specs)
        layout.addWidget(self._advanced_form)

        self._hint = QLabel("This stage runs the intelligence task you choose.")
        self._hint.setWordWrap(True)
        self._hint.setObjectName("controlHint")
        layout.addWidget(self._hint)

        self._advanced_form.setVisible(False)
        self._hint.setVisible(False)

        self._primary_form.settingChanged.connect(self._emit_primary)
        self._advanced_form.settingChanged.connect(self._emit_advanced)

    def set_stage(self, stage: StageViewModel) -> None:
        meta = stage.ui_metadata if isinstance(stage.ui_metadata, dict) else {}
        self._providers = meta.get("providers", [])
        self._models = meta.get("models", [])
        selected_provider = meta.get("selected_provider", "")
        selected_models = stage.current_settings.get("selected_models", {})
        model_id = ""
        if isinstance(selected_models, dict) and selected_provider:
            models = selected_models.get(selected_provider, [])
            if isinstance(models, list) and models:
                model_id = str(models[0])
        self._primary_form.set_options("provider", self._providers)
        self._primary_form.set_options("model_id", self._models)
        settings = dict(stage.current_settings)
        settings["provider"] = selected_provider
        settings["model_id"] = model_id
        self._selected_provider = selected_provider
        self._primary_form.set_values(settings)

        prompt_presets = meta.get("prompt_presets", [])
        prompt_options = [(item.get("label", item.get("id", "")), item.get("id", "")) for item in prompt_presets if isinstance(item, dict)]
        prompt_options.append(("Custom", "custom"))
        self._advanced_form.set_options("prompt_profile", prompt_options)
        self._advanced_form.set_values(settings)
        if stage.error:
            self._advanced_form.set_values({"cost_estimate": "n/a"})

    def set_density(self, density: str) -> None:
        show_advanced = density == "full"
        self._advanced_form.setVisible(show_advanced)
        self._hint.setVisible(show_advanced)

    def _emit_primary(self, key: str, value: object) -> None:
        if key == "provider":
            self._selected_provider = str(value or "")
            self.settingsChanged.emit(
                {
                    "selected_providers": [self._selected_provider] if self._selected_provider else [],
                    "selected_models": {self._selected_provider: []} if self._selected_provider else {},
                }
            )
            return
        if key == "model_id":
            provider = self._selected_provider
            selected_models = {provider: [str(value)]} if provider and value else {}
            payload = {
                "selected_providers": [provider] if provider else [],
                "selected_models": selected_models,
            }
            self.settingsChanged.emit(payload)
            return
        self.settingsChanged.emit({key: value})

    def _emit_advanced(self, key: str, value: object) -> None:
        self.settingsChanged.emit({key: value})


def _specs_from_fields(fields: List[SettingField]) -> List[_ControlSpec]:
    specs: List[_ControlSpec] = []
    for field in fields:
        if field.options:
            specs.append(
                _ControlSpec(
                    key=field.key,
                    label=field.label,
                    kind="combo",
                    options=[(opt.label, opt.value) for opt in field.options],
                    editable=field.editable,
                )
            )
            continue
        kind = "toggle" if isinstance(field.value, bool) else "text"
        specs.append(
            _ControlSpec(
                key=field.key,
                label=field.label,
                kind=kind,
                options=[],
                editable=field.editable,
            )
        )
    return specs


def _model_key_for(schema: List[SettingField]) -> str:
    keys = {field.key for field in schema}
    if "model" in keys:
        return "model"
    if "model_id" in keys:
        return "model_id"
    return "model"


def _options_for_key(schema: List[SettingField], key: str) -> List[Tuple[str, str]]:
    for field in schema:
        if field.key != key:
            continue
        if field.options:
            return [(opt.label, opt.value) for opt in field.options]
    return []


def _create_stage_controls(stage: StageViewModel) -> QWidget:
    stage_id = stage.stage_id
    if stage_id == "input":
        return _InputStageControls()
    if stage_id == "transcription":
        model_key = _model_key_for(stage.settings_schema)
        primary_specs = [
            _ControlSpec("plugin_id", "Provider", "combo"),
            _ControlSpec(model_key, "Model", "combo"),
            _ControlSpec(
                "quality_mode",
                "Quality mode",
                "combo",
                options=[("Fast", "fast"), ("Balanced", "balanced"), ("Accurate", "accurate")],
            ),
        ]
        advanced_specs = [
            _ControlSpec("language", "Language", "combo", options=[("auto", "auto")], editable=True),
            _ControlSpec("diarization", "Diarization", "toggle"),
            _ControlSpec(
                "punctuation_mode",
                "Punctuation",
                "combo",
                options=[("auto", "auto"), ("on", "on"), ("off", "off")],
            ),
            _ControlSpec(
                "timestamps",
                "Timestamps",
                "combo",
                options=[("segments", "segments"), ("words", "words")],
            ),
            _ControlSpec("temperature", "Temperature", "text"),
            _ControlSpec("beam_size", "Beam size", "text"),
        ]
        return _FormStageControls(primary_specs, advanced_specs)
    if stage_id == "llm_processing":
        return _LlmStageControls()
    if stage_id == "management":
        primary_specs = [
            _ControlSpec(
                "summary_type",
                "Summary type",
                "combo",
                options=[("Executive", "executive"), ("Detailed", "detailed")],
            ),
            _ControlSpec(
                "summary_length",
                "Length",
                "combo",
                options=[("Short", "short"), ("Medium", "medium"), ("Long", "long")],
            ),
        ]
        advanced_specs = [
            _ControlSpec(
                "tone",
                "Tone",
                "combo",
                options=[("neutral", "neutral"), ("formal", "formal"), ("casual", "casual")],
            ),
            _ControlSpec("include_decisions", "Include decisions", "toggle"),
            _ControlSpec("include_action_items", "Include action items", "toggle"),
            _ControlSpec(
                "formatting_style",
                "Formatting",
                "combo",
                options=[("bullets", "bullets"), ("paragraphs", "paragraphs")],
            ),
            _ControlSpec("language_override", "Language override", "text"),
        ]
        return _FormStageControls(primary_specs, advanced_specs)
    if stage_id == "service":
        primary_specs = [
            _ControlSpec(
                "export_format",
                "Export format",
                "combo",
                options=[("Markdown", "md"), ("PDF", "pdf"), ("DOCX", "docx")],
            ),
        ]
        advanced_specs = [
            _ControlSpec("naming_pattern", "Naming pattern", "text"),
            _ControlSpec("include_metadata", "Include metadata", "toggle"),
            _ControlSpec("overwrite_policy", "Overwrite policy", "combo", options=[("ask", "ask"), ("overwrite", "overwrite"), ("skip", "skip")]),
            _ControlSpec("auto_export", "Auto-export", "toggle"),
        ]
        return _ServiceStageControls(primary_specs, advanced_specs)
    return _InlineStageControls()


class StageTileWidget(QFrame):
    selected = Signal(str)
    settingsChanged = Signal(str, dict)
    runRequested = Signal(str)
    rerunRequested = Signal(str)
    presentationChanged = Signal(str, bool, str)
    disableChanged = Signal(str, bool)
    filesChanged = Signal(list)
    openOutputRequested = Signal(str)

    def __init__(self, stage: StageViewModel) -> None:
        super().__init__()
        self.stage_id = stage.stage_id
        self.density = "mini"
        self._stage = stage
        self._primary_action = "run"
        self._orientation = "horizontal"

        self.setObjectName("stageTile")
        self.setFrameShape(QFrame.Box)
        # Size is controlled by the pipeline chain layout along the primary axis.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._layout = QVBoxLayout(self)
        # Horizontal mode uses a fixed tile height (UI.txt); content must fit.
        self._layout.setContentsMargins(6, 4, 6, 4)
        self._layout.setSpacing(2)

        self._header_row = QHBoxLayout()
        self._icon = QLabel()
        self._icon.setFixedSize(16, 16)
        self._icon.setAlignment(Qt.AlignCenter)
        self._name = QLabel(stage.short_name or stage.display_name)
        self._name.setWordWrap(False)
        self._status = QLabel("")
        self._status.setObjectName("stageStatus")
        self._status.setWordWrap(False)
        self._badge = QLabel("")
        self._badge.setObjectName("stageBadge")
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setVisible(False)
        self._run_btn = QToolButton()
        self._run_btn.setText("Run")
        self._run_btn.setFixedSize(QSize(22, 22))
        self._open_btn = QToolButton()
        self._open_btn.setText("Open")
        self._open_btn.setFixedSize(QSize(22, 22))
        self._open_btn.setVisible(False)
        self._menu_btn = QToolButton()
        self._menu_btn.setText("...")
        self._menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._menu = QMenu(self)
        self._menu_btn.setMenu(self._menu)
        self._header_row.addWidget(self._icon)
        self._header_row.addWidget(self._name)
        self._header_row.addWidget(self._badge)
        self._header_row.addStretch()
        self._header_row.addWidget(self._status)
        self._header_row.addWidget(self._open_btn)
        self._header_row.addWidget(self._run_btn)
        self._header_row.addWidget(self._menu_btn)
        self._layout.addLayout(self._header_row)

        self._ring = ProgressRingWidget()
        self._meta = QLabel("")
        self._meta.setWordWrap(False)
        self._ring_in_header = False
        self._body = QWidget()
        self._body_layout = QHBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(6)
        self._right = QWidget()
        right_layout = QVBoxLayout(self._right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)
        right_layout.addWidget(self._meta)
        self._body_layout.addWidget(self._ring)
        self._body_layout.addWidget(self._right, 1)
        self._layout.addWidget(self._body)

        if stage.stage_id == "input":
            self._controls = _InputTileControls()
            self._controls.filesChanged.connect(self._emit_files)
        elif stage.stage_id == "llm_processing":
            self._controls = _LlmTileControls()
            self._controls.settingsChanged.connect(self._emit_settings)
        else:
            self._controls = _StageTileControls()
            self._controls.settingsChanged.connect(self._emit_settings)
        # Controls live under the meta line (right side of the body row).
        right_layout.addWidget(self._controls)
        right_layout.addStretch()

        self._run_btn.clicked.connect(self._emit_run)
        self._open_btn.clicked.connect(self._emit_open_output)

        self._build_menu()
        self.set_stage(stage)
        self.set_density(self.density)

    def set_stage(self, stage: StageViewModel) -> None:
        self._stage = stage
        icon_type = _STAGE_ICON_MAP.get(stage.stage_id, QStyle.SP_FileIcon)
        self._icon.setPixmap(self.style().standardIcon(icon_type).pixmap(16, 16))
        self._name.setText(stage.short_name or stage.display_name)
        self._status.setText(stage.status.title() if stage.status else "Idle")
        status_key = stage.status or "idle"
        color = _STATUS_COLORS.get(status_key, _STATUS_COLORS["idle"])
        self._status.setStyleSheet(f"color: {color.name()};")
        progress = stage.progress
        if progress is None:
            self._ring.set_indeterminate(True)
        else:
            self._ring.set_indeterminate(False)
            self._ring.set_value(progress)
        meta = ""
        if stage.stage_id == "input":
            files = stage.current_settings.get("files", [])
            count = len(files) if isinstance(files, list) else 0
            if count == 0:
                meta = "No files"
            elif count == 1:
                meta = "1 file"
            else:
                meta = f"{count} files"
            if stage.is_dirty and count:
                meta = f"{meta} (updated)"
        elif stage.is_dirty:
            meta = "Needs rerun"
        elif stage.error:
            meta = "Error"
        self._meta.setText(meta)
        self._update_badge(stage)
        self._update_tooltip(stage)
        if hasattr(self._controls, "set_stage"):
            self._controls.set_stage(stage)
        if isinstance(self._controls, _InputTileControls):
            files = stage.current_settings.get("files", [])
            self._controls.set_files(files if isinstance(files, list) else [])
        self._primary_action = self._primary_action_for(stage)
        if stage.stage_id == "service":
            self._run_btn.setText("Export")
        else:
            self._run_btn.setText("Rerun" if self._primary_action == "rerun" else "Run")
        enabled = stage.can_rerun if self._primary_action == "rerun" else stage.can_run
        self._run_btn.setEnabled(enabled)
        if hasattr(self, "_disable_action"):
            self._disable_action.setChecked(not stage.is_enabled)
        # Stage updates can change badges/status; re-apply density visibility rules.
        self.set_density(self.density)

    @staticmethod
    def _primary_action_for(stage: StageViewModel) -> str:
        if stage.can_rerun and (stage.is_dirty or stage.status in {"completed", "failed", "skipped"}):
            return "rerun"
        return "run"

    def _update_badge(self, stage: StageViewModel) -> None:
        badge = self._badge_for(stage)
        if not badge:
            self._badge.setVisible(False)
            return
        text, fg, bg = badge
        self._badge.setText(text)
        self._badge.setStyleSheet(
            f"color: {fg}; background-color: {bg}; border-radius: 8px; padding: 1px 6px;"
        )
        self._badge.setVisible(True)

    def _badge_for(self, stage: StageViewModel) -> Optional[Tuple[str, str, str]]:
        if stage.status == "disabled":
            return ("Disabled", "#6B7280", "#E5E7EB")
        if stage.error:
            return ("Error", "#991B1B", "#FEE2E2")
        if stage.warnings:
            return ("Warning", "#92400E", "#FEF3C7")
        if stage.stage_id == "input":
            files = stage.current_settings.get("files", [])
            if not files:
                return ("No file", "#6B7280", "#F3F4F6")
            return ("Loaded", "#166534", "#DCFCE7")
        if stage.stage_id == "transcription" and stage.status == "completed":
            return ("Cached", "#6B7280", "#F3F4F6")
        if stage.stage_id == "llm_processing" and stage.warnings:
            return ("Warning", "#92400E", "#FEF3C7")
        if stage.stage_id == "management":
            if stage.is_dirty:
                return ("Outdated", "#92400E", "#FEF3C7")
            if stage.status == "completed":
                return ("Synced", "#166534", "#DCFCE7")
        if stage.stage_id == "service":
            if stage.status == "completed":
                return ("Exported", "#166534", "#DCFCE7")
            if stage.status in {"idle", "ready", "running"}:
                return ("Not exported", "#6B7280", "#F3F4F6")
        return None

    def _update_tooltip(self, stage: StageViewModel) -> None:
        lines = [stage.display_name]
        if stage.error:
            lines.append(f"Error: {stage.error}")
        if stage.warnings:
            lines.append(f"Warning: {stage.warnings[0]}")
        self.setToolTip("\n".join(lines))

    def set_orientation(self, orientation: str) -> None:
        normalized = "vertical" if orientation == "vertical" else "horizontal"
        if normalized == self._orientation:
            return
        self._orientation = normalized
        self.set_density(self.density)
        self.apply_fixed_size()

    def set_density(self, density: str) -> None:
        self.density = density
        if density == "collapsed":
            self._layout.setContentsMargins(6, 4, 6, 4)
            self._layout.setSpacing(2)
            self._controls.setVisible(False)
            self._run_btn.setVisible(False)
            self._open_btn.setVisible(False)
            self._ring.setVisible(True)
            self._meta.setVisible(False)
            self._status.setVisible(False)
            self._badge.setVisible(False)
        elif density == "mini":
            self._layout.setContentsMargins(6, 4, 6, 4)
            self._layout.setSpacing(2)
            self._controls.setVisible(True)
            self._run_btn.setVisible(True)
            self._open_btn.setVisible(self.stage_id == "service")
            self._ring.setVisible(True)
            self._meta.setVisible(True)
            self._status.setVisible(True)
            self._badge.setVisible(bool(self._badge.text().strip()))
        else:
            self._layout.setContentsMargins(6, 4, 6, 4)
            self._layout.setSpacing(2)
            self._controls.setVisible(True)
            self._run_btn.setVisible(True)
            self._open_btn.setVisible(self.stage_id == "service")
            self._ring.setVisible(True)
            self._meta.setVisible(True)
            self._status.setVisible(True)
            self._badge.setVisible(bool(self._badge.text().strip()))
        if hasattr(self._controls, "set_density"):
            self._controls.set_density(density)
        self.apply_fixed_size()
        self.updateGeometry()
        self.adjustSize()

    def apply_fixed_size(self, orientation: str | None = None) -> None:
        orientation = self._orientation if orientation is None else orientation
        if orientation == "vertical":
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.setFixedWidth(_TILE_WIDTH_V)
            self.setMinimumHeight(_TILE_MIN_HEIGHTS_V.get(self.density, _TILE_MIN_HEIGHTS_V["mini"]))
            self.setMaximumHeight(16777215)
            self._ring.setFixedSize(QSize(40, 40))
            self._controls.setMinimumHeight(0)
            self._controls.setMaximumHeight(16777215)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setFixedHeight(_TILE_HEIGHT_H)
            self.setMinimumWidth(_TILE_MIN_WIDTHS_H.get(self.density, _TILE_MIN_WIDTHS_H["mini"]))
            self.setMaximumWidth(16777215)
            self._ring.setFixedSize(QSize(44, 44))
            # Horizontal tiles have a fixed 26px controls row (UI.txt).
            self._controls.setFixedHeight(26)
        self._apply_ring_placement()
        self.updateGeometry()

    def _apply_ring_placement(self) -> None:
        # Vertical collapsed tiles are only 52px tall; place the ring into the header
        # and hide the body row to avoid clipping.
        collapsed_vertical = self._orientation == "vertical" and self.density == "collapsed"
        if collapsed_vertical:
            self._body.setVisible(False)
            if not self._ring_in_header:
                self._body_layout.removeWidget(self._ring)
                insert_at = self._header_row.indexOf(self._status)
                if insert_at < 0:
                    insert_at = max(0, self._header_row.count() - 1)
                self._header_row.insertWidget(insert_at, self._ring)
                self._ring_in_header = True
            return
        self._body.setVisible(True)
        if self._ring_in_header:
            self._header_row.removeWidget(self._ring)
            self._body_layout.insertWidget(0, self._ring)
            self._ring_in_header = False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.stage_id)
        super().mousePressEvent(event)

    def _emit_run(self) -> None:
        if self._primary_action == "rerun":
            self.rerunRequested.emit(self.stage_id)
        else:
            self.runRequested.emit(self.stage_id)

    def _emit_settings(self, settings: dict) -> None:
        self.settingsChanged.emit(self.stage_id, settings)

    def _emit_files(self, files: list[str]) -> None:
        self.filesChanged.emit(files)

    def _emit_open_output(self) -> None:
        self.openOutputRequested.emit(self.stage_id)

    def _build_menu(self) -> None:
        density_menu = self._menu.addMenu("Density")
        for label, density in [("Collapsed", "collapsed"), ("Mini", "mini"), ("Full", "full")]:
            action = density_menu.addAction(label)
            action.triggered.connect(lambda _=False, d=density: self._set_density_action(d))
        hide_action = self._menu.addAction("Hide stage")
        hide_action.triggered.connect(lambda: self._emit_presentation(False, self.density))
        self._disable_action = self._menu.addAction("Disable stage")
        self._disable_action.setCheckable(True)
        self._disable_action.triggered.connect(self._toggle_disabled)

    def _set_density_action(self, density: str) -> None:
        self.set_density(density)
        self._emit_presentation(True, density)

    def _emit_presentation(self, visible: bool, density: str) -> None:
        self.presentationChanged.emit(self.stage_id, visible, density)

    def _toggle_disabled(self, checked: bool) -> None:
        self.disableChanged.emit(self.stage_id, checked)


class InlineSettingsRow(QWidget):
    settingsChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._fields: Dict[str, QWidget] = {}
        self._values: Dict[str, object] = {}

    def set_fields(
        self,
        schema: List[SettingField],
        inline_keys: List[str],
        current: dict,
        *,
        max_fields: int = 4,
    ) -> None:
        for i in reversed(range(self._layout.count())):
            item = self._layout.takeAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        self._fields = {}
        self._values = dict(current)

        fields = inline_fields_from_schema(schema, inline_keys)[: max(0, int(max_fields))]
        for field in fields:
            widget = self._build_field(field, current.get(field.key, field.value))
            self._fields[field.key] = widget
            self._layout.addWidget(widget)
        self._layout.addStretch()

    def _build_field(self, field: SettingField, value: object) -> QWidget:
        if field.options:
            combo = QComboBox()
            combo.setFixedHeight(24)
            for opt in field.options:
                combo.addItem(opt.label, opt.value)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            else:
                combo.setCurrentText(str(value or ""))
            combo.currentIndexChanged.connect(self._emit)
            return combo
        if isinstance(value, bool) or str(value).lower() in {"true", "false"}:
            box = QCheckBox(field.label)
            box.setChecked(bool(value))
            box.setFixedHeight(24)
            box.stateChanged.connect(self._emit)
            return box
        if field.editable:
            line = QLineEdit()
            line.setFixedHeight(24)
            line.setText(str(value or ""))
            line.editingFinished.connect(self._emit)
            return line
        return QLabel(str(value or ""))

    def _emit(self) -> None:
        payload: Dict[str, object] = {}
        for key, widget in self._fields.items():
            if isinstance(widget, QComboBox):
                payload[key] = widget.currentData() or widget.currentText()
            elif isinstance(widget, QCheckBox):
                payload[key] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                payload[key] = widget.text()
        if payload:
            self.settingsChanged.emit(payload)


class _InputTileControls(QWidget):
    filesChanged = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._files: List[str] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._select_btn = QToolButton()
        self._select_btn.setText("Select")
        self._select_btn.setFixedHeight(26)
        self._clear_btn = QToolButton()
        self._clear_btn.setText("Clear")
        self._clear_btn.setFixedHeight(26)
        layout.addWidget(self._select_btn)
        layout.addWidget(self._clear_btn)
        self._summary = QLabel("No files")
        self._summary.setToolTip("No files selected")
        self._summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self._summary, 1)
        self._select_btn.clicked.connect(self._pick_files)
        self._clear_btn.clicked.connect(self._clear)

    def set_files(self, files: list[str]) -> None:
        self._files = list(files)
        if not self._files:
            self._summary.setText("No files")
            self._summary.setToolTip("No files selected")
            return
        def _basename(path: str) -> str:
            return str(path).replace("\\", "/").split("/")[-1]

        first = _basename(self._files[0])
        if len(self._files) == 1:
            self._summary.setText(first)
        else:
            self._summary.setText(f"{first} +{len(self._files) - 1}")
        self._summary.setToolTip("\n".join(_basename(p) for p in self._files))

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select files")
        if not files:
            return
        self._files = list(files)
        self.filesChanged.emit(list(self._files))

    def _clear(self) -> None:
        if not self._files:
            return
        self._files = []
        self.filesChanged.emit([])


class _StageTileControls(QWidget):
    settingsChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stage: StageViewModel | None = None
        self._max_inline_fields = 4
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._plugin_combo = QComboBox()
        self._plugin_combo.setFixedHeight(26)
        self._plugin_combo.setVisible(False)
        layout.addWidget(self._plugin_combo)

        self._inline = InlineSettingsRow()
        layout.addWidget(self._inline, 1)

        self._plugin_combo.currentIndexChanged.connect(self._emit_plugin)
        self._inline.settingsChanged.connect(self.settingsChanged.emit)

    def set_stage(self, stage: StageViewModel) -> None:
        self._stage = stage
        if stage.plugin_options:
            self._plugin_combo.blockSignals(True)
            self._plugin_combo.clear()
            self._plugin_combo.addItem("Provider", "")
            for opt in stage.plugin_options:
                self._plugin_combo.addItem(opt.label, opt.value)
            idx = self._plugin_combo.findData(stage.plugin_id)
            if idx >= 0:
                self._plugin_combo.setCurrentIndex(idx)
            self._plugin_combo.blockSignals(False)
            self._plugin_combo.setVisible(True)
            inline_keys = stage.inline_settings_keys[:3]
        else:
            self._plugin_combo.setVisible(False)
            inline_keys = stage.inline_settings_keys[:4]
        self._inline.set_fields(
            stage.settings_schema,
            inline_keys,
            stage.current_settings,
            max_fields=self._max_inline_fields,
        )

    def set_density(self, density: str) -> None:
        # Mini: keep only the most important knobs visible; Full: show more inline controls.
        self._max_inline_fields = 2 if density == "mini" else 4
        if self._stage:
            self.set_stage(self._stage)

    def _emit_plugin(self) -> None:
        if not self._plugin_combo.isVisible():
            return
        value = self._plugin_combo.currentData()
        if value:
            self.settingsChanged.emit({"plugin_id": str(value)})


class _LlmTileControls(QWidget):
    settingsChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._provider = ""
        self._density = "mini"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._provider_combo = QComboBox()
        self._provider_combo.setFixedHeight(26)
        self._model_combo = QComboBox()
        self._model_combo.setFixedHeight(26)
        self._task_combo = QComboBox()
        self._task_combo.setFixedHeight(26)

        layout.addWidget(self._provider_combo)
        layout.addWidget(self._model_combo)
        layout.addWidget(self._task_combo)
        layout.addStretch()

        self._provider_combo.currentIndexChanged.connect(self._emit_provider)
        self._model_combo.currentIndexChanged.connect(self._emit_model)
        self._task_combo.currentIndexChanged.connect(self._emit_task)

    def set_stage(self, stage: StageViewModel) -> None:
        meta = stage.ui_metadata if isinstance(stage.ui_metadata, dict) else {}
        providers = meta.get("providers", [])
        models = meta.get("models", [])
        prompt_presets = meta.get("prompt_presets", [])
        selected_provider = str(meta.get("selected_provider", "") or "")

        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()
        for label, pid in providers:
            self._provider_combo.addItem(label, pid)
        idx = self._provider_combo.findData(selected_provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.blockSignals(False)
        self._provider = str(self._provider_combo.currentData() or "")

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for label, mid in models:
            self._model_combo.addItem(label, mid)
        # Try to restore current model selection for the provider.
        selected_models = stage.current_settings.get("selected_models", {})
        if isinstance(selected_models, dict) and self._provider:
            current = selected_models.get(self._provider, [])
            if isinstance(current, list) and current:
                mid = str(current[0])
                idx = self._model_combo.findData(mid)
                if idx >= 0:
                    self._model_combo.setCurrentIndex(idx)
        self._model_combo.blockSignals(False)

        self._task_combo.blockSignals(True)
        self._task_combo.clear()
        self._task_combo.addItem("Task", "")
        for preset in prompt_presets if isinstance(prompt_presets, list) else []:
            if not isinstance(preset, dict):
                continue
            pid = str(preset.get("id", "")).strip()
            if not pid:
                continue
            label = str(preset.get("label", "")).strip() or pid
            self._task_combo.addItem(label, pid)
        profile = str(stage.current_settings.get("prompt_profile", "") or "")
        idx = self._task_combo.findData(profile)
        if idx >= 0:
            self._task_combo.setCurrentIndex(idx)
        self._task_combo.blockSignals(False)
        self._task_combo.setVisible(self._density == "full")

    def set_density(self, density: str) -> None:
        self._density = density
        self._task_combo.setVisible(density == "full")

    def _emit_provider(self) -> None:
        provider = str(self._provider_combo.currentData() or "")
        self._provider = provider
        payload = {
            "selected_providers": [provider] if provider else [],
            "selected_models": {provider: []} if provider else {},
        }
        self.settingsChanged.emit(payload)

    def _emit_model(self) -> None:
        provider = self._provider
        model_id = str(self._model_combo.currentData() or "")
        payload = {
            "selected_providers": [provider] if provider else [],
            "selected_models": {provider: [model_id]} if provider and model_id else {},
        }
        self.settingsChanged.emit(payload)

    def _emit_task(self) -> None:
        preset_id = str(self._task_combo.currentData() or "")
        if preset_id:
            self.settingsChanged.emit({"prompt_profile": preset_id})


class ProgressRingWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0
        self._indeterminate = False
        self.setFixedSize(QSize(40, 40))

    def set_value(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def set_indeterminate(self, value: bool) -> None:
        self._indeterminate = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(4, 4, -4, -4)
        pen_bg = QPen(QColor("#E5E7EB"), 4)
        painter.setPen(pen_bg)
        painter.drawEllipse(rect)

        if self._indeterminate:
            pen = QPen(QColor("#9CA3AF"), 4)
            painter.setPen(pen)
            painter.drawArc(rect, 0 * 16, 120 * 16)
            text = "..."
        else:
            pen = QPen(QColor("#3B82F6"), 4)
            painter.setPen(pen)
            span = int(360 * self._value / 100)
            painter.drawArc(rect, 90 * 16, -span * 16)
            text = f"{self._value}%"
        painter.setPen(QColor("#111827"))
        painter.drawText(self.rect(), Qt.AlignCenter, text)
