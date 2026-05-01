from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aimn.ui.tabs.contracts import SettingField, StageViewModel


class SettingsTab(QWidget):
    settingsChanged = Signal(str, dict)
    customActionRequested = Signal(str, dict)

    def __init__(self, settings_service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._service = settings_service
        self._stage: StageViewModel | None = None
        self._fields: dict[str, QWidget] = {}
        self._custom_panel: QWidget | None = None
        self._density = "full"
        self._layout_mode = "form"  # form|grid
        self._grid_columns = 4
        # Drawer ("grid") must fit content without forcing scroll.
        self._grid_max_height = 2000
        self._rendering = False
        self._tearing_down = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._plugin_row = QWidget()
        plugin_layout = QHBoxLayout(self._plugin_row)
        plugin_layout.setContentsMargins(0, 0, 0, 0)
        plugin_layout.setSpacing(8)
        plugin_layout.addWidget(QLabel("Provider"))
        self._plugin_combo = QComboBox()
        self._plugin_combo.currentIndexChanged.connect(self._on_plugin_combo_changed)
        self._plugin_combo.setMaximumWidth(240)
        self._plugin_combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        plugin_layout.addWidget(self._plugin_combo, 0)
        self._plugin_note = QLabel("")
        self._plugin_note.setObjectName("pipelineMetaLabel")
        plugin_layout.addWidget(self._plugin_note, 1)
        plugin_layout.addStretch(1)
        layout.addWidget(self._plugin_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._form_container = QWidget()
        self._form_layout = QVBoxLayout(self._form_container)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setSpacing(8)
        self._scroll.setWidget(self._form_container)
        layout.addWidget(self._scroll, 1)

        self._actions = QWidget()
        actions_layout = QHBoxLayout(self._actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.addStretch()
        self._reset_btn = QPushButton("Reset to defaults")
        self._reset_btn.clicked.connect(lambda *_args: self._reset_to_defaults())
        actions_layout.addWidget(self._reset_btn)
        layout.addWidget(self._actions)

    def set_layout_mode(self, mode: str, *, columns: int = 4) -> None:
        self._layout_mode = "grid" if str(mode).lower().strip() == "grid" else "form"
        self._grid_columns = max(2, min(6, int(columns)))
        if self._layout_mode == "grid":
            # Grid mode: hide scrollbars but allow wheel scrolling if content exceeds max height.
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._actions.setVisible(False)
        else:
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self._actions.setVisible(True)
            self._scroll.setMinimumHeight(0)
            self._scroll.setMaximumHeight(16777215)
            self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if self._stage:
            self.set_stage(self._stage)

    def set_stage(self, stage: StageViewModel) -> None:
        self._rendering = True
        try:
            self.setUpdatesEnabled(False)
            self._stage = stage
            self._render_plugins(stage)
            self._clear_form()
            self._render_custom_panel(stage)
            self._render_fields(stage)
            self._apply_field_conditions()
            if self._layout_mode != "grid":
                self._form_layout.addStretch()
            self._sync_scroll_height()
            QTimer.singleShot(0, self._sync_scroll_height)
            QTimer.singleShot(20, self._sync_scroll_height)
        finally:
            self.setUpdatesEnabled(True)
            self._rendering = False

    def set_density(self, density: str) -> None:
        density = str(density or "").strip() or "full"
        if density == self._density:
            return
        self._density = density
        if self._stage:
            self.set_stage(self._stage)

    def on_activated(self) -> None:
        return

    def on_deactivated(self) -> None:
        return

    def _render_plugins(self, stage: StageViewModel) -> None:
        self._plugin_combo.blockSignals(True)
        self._plugin_combo.clear()
        hide_provider_row = bool(getattr(stage, "ui_metadata", {}) and stage.ui_metadata.get("hide_provider_row"))
        if hide_provider_row:
            self._plugin_combo.addItem("Multiple", "")
            self._plugin_combo.setCurrentIndex(0)
            self._plugin_combo.setEnabled(False)
            self._plugin_note.setText("")
            self._plugin_combo.setVisible(False)
            self._plugin_row.setVisible(False)
            self._plugin_combo.blockSignals(False)
            return
        options = self._service.stage_plugin_options(stage.stage_id)
        for plugin_id, label in options:
            self._plugin_combo.addItem(label, plugin_id)
        selected = self._service.selected_plugin(stage.stage_id)
        index = self._plugin_combo.findData(selected)
        if index >= 0:
            self._plugin_combo.setCurrentIndex(index)
        # Keep row height stable to avoid UI "jumping" between stages.
        if options:
            self._plugin_combo.setEnabled(True)
            self._plugin_note.setText("")
        else:
            note = "Built-in"
            if stage.stage_id == "media_convert":
                note = "Built-in (FFmpeg)"
            # Show a disabled combo with a single item instead of hiding widgets.
            self._plugin_combo.addItem(note, "")
            self._plugin_combo.setCurrentIndex(0)
            self._plugin_combo.setEnabled(False)
            self._plugin_note.setText("")
        self._plugin_combo.setVisible(True)
        self._plugin_row.setVisible(True)
        self._plugin_combo.blockSignals(False)

    def _render_fields(self, stage: StageViewModel) -> None:
        inline_keys = set(stage.inline_settings_keys)
        basic_fields = [field for field in stage.settings_schema if field.key in inline_keys]
        advanced_fields = [field for field in stage.settings_schema if field.key not in inline_keys]

        if basic_fields:
            self._form_layout.addWidget(
                self._build_group("Basic", basic_fields, stage.current_settings)
            )
        # Drawer density ("mini") must not expose advanced / free-text settings.
        show_advanced = self._density == "full"
        if advanced_fields and show_advanced:
            self._form_layout.addWidget(
                self._build_group("Advanced", advanced_fields, stage.current_settings)
            )

        if self._density == "mini" and not basic_fields and stage.settings_schema:
            note = QLabel("Advanced settings are available in the Settings tab.")
            note.setObjectName("pipelineMetaLabel")
            self._form_layout.addWidget(note)
        elif not stage.settings_schema and not self._custom_panel:
            note = QLabel("No settings available for this stage.")
            self._form_layout.addWidget(note)
        return

    def _render_custom_panel(self, stage: StageViewModel) -> None:
        panel = self._service.build_custom_panel(stage.stage_id, self)
        if panel:
            # By default, SettingsTab owns custom panels and is responsible for cleanup.
            # Some callers may opt out by setting `aimn_external_owned=True` on the widget.
            if panel.property("aimn_external_owned") is None:
                panel.setProperty("aimn_external_owned", False)
            if hasattr(panel, "apply_stage"):
                panel.apply_stage(stage)
            if hasattr(panel, "set_density"):
                panel.set_density(self._density)
            if hasattr(panel, "settingsChanged"):
                try:
                    panel.settingsChanged.connect(self._on_custom_panel_changed, Qt.UniqueConnection)
                except Exception:
                    pass
            if hasattr(panel, "refreshModelsRequested"):
                try:
                    panel.refreshModelsRequested.connect(
                        self._on_custom_panel_refresh_models_requested, Qt.UniqueConnection
                    )
                except Exception:
                    pass
            self._custom_panel = panel
            self._form_layout.insertWidget(0, panel)
        return

    def _on_custom_panel_changed(self, *_args) -> None:
        self._emit_changes()
        # Custom panels can change their intrinsic height (e.g., input file list).
        # Keep drawer sizing in sync without requiring a stage re-render.
        QTimer.singleShot(0, self._sync_scroll_height)

    def _on_custom_panel_refresh_models_requested(self, provider_id: str) -> None:
        if not self._stage:
            return
        pid = str(provider_id or "").strip()
        if not pid:
            return
        self.customActionRequested.emit(self._stage.stage_id, {"type": "refresh_models", "provider_id": pid})

    def _clear_form(self) -> None:
        self._tearing_down = True
        external_owned = False
        if self._custom_panel is not None:
            try:
                external_owned = bool(self._custom_panel.property("aimn_external_owned"))
            except Exception:
                external_owned = False
        for i in reversed(range(self._form_layout.count())):
            item = self._form_layout.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                # Custom panels can be externally owned (opt-out of deletion).
                if self._custom_panel is not None and w is self._custom_panel and external_owned:
                    continue
                # Avoid use-after-free crashes during rapid UI updates (Qt deletes widgets eagerly
                # when parent changes). deleteLater() makes teardown safe across re-entrant signals.
                w.deleteLater()
        self._fields = {}
        if self._custom_panel:
            # If owned, request deletion; otherwise detach only.
            if not external_owned:
                self._custom_panel.deleteLater()
            self._custom_panel = None
        self._tearing_down = False

    def _build_group(
        self,
        title: str,
        fields: list[SettingField],
        values: dict,
    ) -> QWidget:
        group = QGroupBox(title)
        if self._layout_mode == "grid":
            layout = QGridLayout(group)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setHorizontalSpacing(12)
            layout.setVerticalSpacing(10)
            cols = max(2, int(self._grid_columns))
            for idx, field in enumerate(fields):
                widget = self._service.build_field_widget(field, values.get(field.key))
                self._tune_grid_widget(widget)
                widget.setProperty("setting_key", field.key)
                self._fields[field.key] = widget
                container = QWidget()
                box = QVBoxLayout(container)
                box.setContentsMargins(0, 0, 0, 0)
                box.setSpacing(4)
                label = QLabel(field.label)
                label.setObjectName("statusMeta")
                box.addWidget(label)
                box.addWidget(widget)
                row = idx // cols
                col = idx % cols
                layout.addWidget(container, row, col)
                self._service.attach_change_handler(widget, self._emit_changes)
        else:
            layout = QFormLayout(group)
            for field in fields:
                widget = self._service.build_field_widget(field, values.get(field.key))
                widget.setProperty("setting_key", field.key)
                self._fields[field.key] = widget
                layout.addRow(field.label, widget)
                self._service.attach_change_handler(widget, self._emit_changes)
        return group

    @staticmethod
    def _tune_grid_widget(widget: QWidget) -> None:
        # Keep controls compact so 3-4 columns fit without scrolling.
        if isinstance(widget, QListWidget):
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            if widget.objectName() == "projectsMultiSelectList":
                widget.setMinimumHeight(160)
                widget.setMaximumHeight(240)
                widget.setMinimumWidth(220)
                widget.setMaximumWidth(360)
            else:
                widget.setMinimumHeight(110)
                widget.setMaximumHeight(170)
                widget.setMinimumWidth(180)
                widget.setMaximumWidth(300)
            return
        widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        widget.setMinimumWidth(120)
        widget.setMaximumWidth(220)

    def _sync_scroll_height(self) -> None:
        """
        In drawer mode ("grid"), the UI must show everything without scrolling.
        We achieve this by sizing the scroll area to the content sizeHint (no internal scroll).
        If the window is too small, the user can resize the main window.
        """
        if self._layout_mode != "grid":
            return
        try:
            if self._form_container.layout():
                self._form_container.layout().activate()
        except Exception:
            pass
        self._form_container.adjustSize()
        content_h = int(self._form_container.sizeHint().height()) + 10
        height = max(160, min(int(self._grid_max_height), content_h))
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._scroll.setMinimumHeight(height)
        self._scroll.setMaximumHeight(height)

    def _collect_values(self) -> dict:
        payload = {"plugin_id": self._plugin_combo.currentData(), "params": self._service.collect_widget_values(self._fields)}
        if self._custom_panel and hasattr(self._custom_panel, "collect_settings"):
            extra = self._custom_panel.collect_settings()
            if isinstance(extra, dict):
                stage_payload = extra.get("__stage_payload__")
                if isinstance(stage_payload, dict):
                    payload.update(stage_payload)
                    extra = {k: v for k, v in extra.items() if k != "__stage_payload__"}
                extra_stage_payloads = extra.get("__extra_stage_payloads__")
                if isinstance(extra_stage_payloads, dict):
                    payload["__extra_stage_payloads__"] = {
                        str(extra_stage_id): dict(extra_payload)
                        for extra_stage_id, extra_payload in extra_stage_payloads.items()
                        if str(extra_stage_id or "").strip() and isinstance(extra_payload, dict)
                    }
                    extra = {k: v for k, v in extra.items() if k != "__extra_stage_payloads__"}
                if extra:
                    payload["params"].update(extra)
        return payload

    def _emit_changes(self, *_args) -> None:
        if self._rendering or self._tearing_down:
            return
        if not self._stage:
            return
        payload = self._collect_values()
        self.settingsChanged.emit(self._stage.stage_id, payload)

    def _on_plugin_combo_changed(self, *_args) -> None:
        self._apply_field_conditions()
        self._emit_changes()

    def _apply_field_conditions(self) -> None:
        """
        UI-only conditional enable/disable logic for a few fields.

        Backlog_my.txt:
        - "Two Pass" is applicable for Auto and None, not for Forced.
        - Forced language enables language_code; other modes disable it.
        """
        if not self._stage:
            return
        stage = self._stage
        if stage.stage_id != "transcription":
            return
        mode_widget = self._fields.get("language_mode")
        code_widget = self._fields.get("language_code")
        two_pass_widget = self._fields.get("two_pass")
        if not mode_widget:
            return

        mode = ""
        if isinstance(mode_widget, QComboBox):
            mode = str(mode_widget.currentData() or mode_widget.currentText() or "").strip()

            if not bool(mode_widget.property("aimn_conditions_wired")):
                try:
                    mode_widget.currentIndexChanged.connect(
                        lambda *_a: self._apply_field_conditions(), Qt.UniqueConnection
                    )
                except Exception:
                    pass
                mode_widget.setProperty("aimn_conditions_wired", True)

        forced = mode == "forced"
        if code_widget is not None:
            code_widget.setEnabled(forced)
        if two_pass_widget is not None:
            two_pass_widget.setEnabled((not forced) and mode in {"auto", "none"})

    def _reset_to_defaults(self, *_args) -> None:
        if not self._stage:
            return
        defaults = self._service.stage_defaults(self._stage.stage_id)
        for key, widget in self._fields.items():
            self._service.apply_widget_value(widget, defaults.get(key))
        if self._custom_panel and hasattr(self._custom_panel, "apply_defaults"):
            self._custom_panel.apply_defaults(defaults)
        self._emit_changes()
