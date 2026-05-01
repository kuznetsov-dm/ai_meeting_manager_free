from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox, QLineEdit, QListWidget, QListWidgetItem, QWidget

from aimn.ui.tabs.contracts import SettingField


class PipelineSettingsUiService:
    def __init__(
        self,
        *,
        selected_plugin_provider: Callable[[str], str],
        plugin_options_provider: Callable[[str], List[Tuple[str, str]]],
        defaults_provider: Callable[[str], Dict[str, object]],
        custom_panel_factory: Callable[[str, QWidget | None], QWidget | None],
    ) -> None:
        self._selected_plugin_provider = selected_plugin_provider
        self._plugin_options_provider = plugin_options_provider
        self._defaults_provider = defaults_provider
        self._custom_panel_factory = custom_panel_factory

    def stage_plugin_options(self, stage_id: str) -> List[Tuple[str, str]]:
        return self._plugin_options_provider(stage_id)

    def selected_plugin(self, stage_id: str) -> str:
        return self._selected_plugin_provider(stage_id)

    def stage_defaults(self, stage_id: str) -> Dict[str, object]:
        return self._defaults_provider(stage_id)

    def build_custom_panel(self, stage_id: str, parent: QWidget | None) -> QWidget | None:
        return self._custom_panel_factory(stage_id, parent)

    @staticmethod
    def _parse_multi_value(raw: object) -> list[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for chunk in text.split(","):
            item = str(chunk or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @staticmethod
    def build_field_widget(field: SettingField, value: object) -> QWidget:
        if bool(field.multi_select) and field.options:
            selected = set(PipelineSettingsUiService._parse_multi_value(value))
            lst = QListWidget()
            lst.setObjectName("projectsMultiSelectList" if field.key == "prompt_project_ids" else "settingsMultiSelectList")
            lst.setSelectionMode(QAbstractItemView.NoSelection)
            lst.setAlternatingRowColors(True)
            added = 0
            for opt in field.options:
                opt_value = str(opt.value or "").strip()
                if not opt_value:
                    continue
                item = QListWidgetItem(str(opt.label or opt_value))
                item.setData(Qt.UserRole, opt_value)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if opt_value in selected else Qt.Unchecked)
                lst.addItem(item)
                added += 1
            if added == 0:
                item = QListWidgetItem("No available options")
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
                lst.addItem(item)
            return lst
        if field.options:
            combo = QComboBox()
            combo.setEditable(bool(field.editable))
            for opt in field.options:
                combo.addItem(opt.label, opt.value)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            else:
                combo.setCurrentText("" if value is None else str(value))
            return combo
        if isinstance(value, bool) or str(value).lower() in {"true", "false"}:
            box = QCheckBox()
            box.setChecked(bool(value))
            return box
        edit = QLineEdit("" if value is None else str(value))
        key = field.key.lower()
        if "key" in key or "token" in key or "secret" in key:
            edit.setEchoMode(QLineEdit.Password)
        return edit

    @staticmethod
    def attach_change_handler(widget: QWidget, handler: Callable[[], None]) -> None:
        if isinstance(widget, QListWidget):
            widget.itemChanged.connect(lambda *_args: handler())
            return
        if isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(lambda *_args: handler())
            if widget.isEditable():
                widget.editTextChanged.connect(lambda *_args: handler())
            return
        if isinstance(widget, QCheckBox):
            widget.stateChanged.connect(lambda *_args: handler())
            return
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(lambda *_args: handler())

    @staticmethod
    def collect_widget_values(fields: Dict[str, QWidget]) -> Dict[str, object]:
        values: Dict[str, object] = {}
        for key, widget in fields.items():
            if isinstance(widget, QListWidget):
                selected: list[str] = []
                for idx in range(widget.count()):
                    item = widget.item(idx)
                    if item.checkState() != Qt.Checked:
                        continue
                    value = str(item.data(Qt.UserRole) or "").strip()
                    if value:
                        selected.append(value)
                values[key] = ",".join(selected)
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
                values[key] = value if value is not None else widget.currentText()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                values[key] = widget.text()
        return values

    @staticmethod
    def apply_widget_value(widget: QWidget, value: object) -> None:
        if isinstance(widget, QListWidget):
            selected = set(PipelineSettingsUiService._parse_multi_value(value))
            for idx in range(widget.count()):
                item = widget.item(idx)
                item_value = str(item.data(Qt.UserRole) or "").strip()
                if not item_value:
                    continue
                item.setCheckState(Qt.Checked if item_value in selected else Qt.Unchecked)
            return
        if isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index >= 0:
                widget.setCurrentIndex(index)
            else:
                widget.setCurrentText("" if value is None else str(value))
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
            return
        if isinstance(widget, QLineEdit):
            widget.setText("" if value is None else str(value))
