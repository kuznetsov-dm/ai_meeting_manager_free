from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from aimn.core.contracts import PluginCatalogProtocol


class PluginSettingsPanel(QGroupBox):
    settings_changed = Signal()

    def __init__(self, title: str, catalog: PluginCatalogProtocol, repo_root: Optional[Path] = None) -> None:
        super().__init__(title)
        self._catalog = catalog
        self._repo_root = repo_root
        self._layout = QFormLayout()
        self._fields: Dict[str, QWidget] = {}
        self._hidden_keys: Set[str] = set()
        self.setLayout(self._layout)

    def set_plugin(self, plugin_id: Optional[str], hidden_keys: Optional[Iterable[str]] = None) -> None:
        self._hidden_keys = set(hidden_keys or [])
        for i in reversed(range(self._layout.count())):
            item = self._layout.itemAt(i)
            if item:
                widget = item.widget()
                if widget:
                    widget.setParent(None)
        self._fields.clear()

        if not plugin_id:
            self._layout.addRow(QLabel("No plugin selected"))
            return

        schema = self._catalog.schema_for(plugin_id)
        if not schema:
            self._layout.addRow(QLabel("No settings for plugin"))
            return

        for setting in schema.settings:
            if setting.key in self._hidden_keys:
                continue
            if setting.value in ("true", "false"):
                field = QCheckBox()
                field.setChecked(setting.value == "true")
                field.stateChanged.connect(lambda _=None: self.settings_changed.emit())
            elif setting.options:
                field = QComboBox()
                for option in setting.options:
                    field.addItem(option.label, option.value)
                field.setEditable(setting.editable)
                index = field.findData(setting.value)
                if index >= 0:
                    field.setCurrentIndex(index)
                else:
                    field.setCurrentText(setting.value)
                field.currentIndexChanged.connect(lambda _=None: self.settings_changed.emit())
                if setting.editable:
                    field.editTextChanged.connect(lambda _=None: self.settings_changed.emit())
            else:
                field = QLineEdit(setting.value)
                if "key" in setting.key.lower() or "token" in setting.key.lower():
                    field.setEchoMode(QLineEdit.Password)
                field.editingFinished.connect(self.settings_changed.emit)
            self._fields[setting.key] = field
            self._layout.addRow(setting.label, field)

        self._add_model_status_row(plugin_id)

    def _add_model_status_row(self, plugin_id: str) -> None:
        if not self._repo_root:
            return
        if not plugin_id.startswith("text_processing."):
            return

        model_id = None
        for key in ("model_id", "embeddings_model_id"):
            field = self._fields.get(key)
            if isinstance(field, QLineEdit):
                value = field.text().strip()
                if value:
                    model_id = value
                    break
        if not model_id:
            return

        available = self._embeddings_available(model_id)
        label = QLabel("available" if available else "missing")
        label.setStyleSheet("color: #15803d;" if available else "color: #b91c1c;")
        self._layout.addRow("Embeddings Model", label)
        field = self._fields.get("embeddings_enabled")
        if isinstance(field, QCheckBox) and available:
            field.setChecked(True)

    def _embeddings_available(self, model_id: Optional[str]) -> bool:
        if not self._repo_root:
            return False
        try:
            from aimn.core.api import embeddings_available
        except Exception:
            return False
        return embeddings_available(model_id=model_id, model_path=None, app_root=self._repo_root)

    def values(self) -> Dict[str, object]:
        data: Dict[str, object] = {}
        for key, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                data[key] = widget.text()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
                data[key] = value if value is not None else widget.currentText()
        return data

    def set_values(self, values: Dict[str, object]) -> None:
        for key, value in values.items():
            widget = self._fields.get(key)
            if widget is None:
                continue
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QLineEdit):
                widget.setText("" if value is None else str(value))
            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
                else:
                    widget.setCurrentText("" if value is None else str(value))


class PluginSelector(QWidget):
    def __init__(
        self,
        title: str,
        catalog: PluginCatalogProtocol,
        stage_id: str,
        hidden_settings: Optional[Iterable[str]] = None,
        repo_root: Optional[Path] = None,
        *,
        allow_mock_plugins: bool = False,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._stage_id = stage_id
        self._hidden_settings = list(hidden_settings or [])
        self._repo_root = repo_root
        self._allow_mock_plugins = allow_mock_plugins

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        self.combo = QComboBox()
        self._plugins = []
        self._reload_plugins()
        layout.addWidget(self.combo)

        self.settings_panel = PluginSettingsPanel("Settings", catalog, repo_root=repo_root)
        layout.addWidget(self.settings_panel)
        self.combo.currentIndexChanged.connect(self._on_plugin_changed)
        self._on_plugin_changed()

    def refresh(self) -> None:
        self._reload_plugins()
        self._on_plugin_changed()

    def set_allow_mock_plugins(self, allow: bool) -> None:
        if self._allow_mock_plugins == allow:
            return
        self._allow_mock_plugins = allow
        self.refresh()

    def selected_plugin_id(self) -> Optional[str]:
        return self.combo.currentData()

    def selected_params(self) -> Dict[str, object]:
        return self.settings_panel.values()

    def select_plugin(self, plugin_id: Optional[str]) -> None:
        if not plugin_id:
            return
        index = self.combo.findData(plugin_id)
        if index >= 0:
            self.combo.setCurrentIndex(index)

    def apply_params(self, params: Dict[str, object]) -> None:
        self.settings_panel.set_values(params)

    def _reload_plugins(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        plugins = [plugin for plugin in self._catalog.plugins_for_stage(self._stage_id) if plugin.installed]
        if not self._allow_mock_plugins:
            if any(not _is_mock_plugin(plugin.plugin_id) for plugin in plugins):
                plugins = [plugin for plugin in plugins if not _is_mock_plugin(plugin.plugin_id)]
        self._plugins = plugins
        for plugin in self._plugins:
            self.combo.addItem(self._catalog.display_name(plugin.plugin_id), plugin.plugin_id)
        self.combo.setEnabled(bool(self._plugins))
        self.combo.blockSignals(False)

    def _on_plugin_changed(self) -> None:
        plugin_id = self.combo.currentData()
        self.settings_panel.set_plugin(plugin_id, hidden_keys=self._hidden_settings)


def _is_mock_plugin(plugin_id: str) -> bool:
    lowered = plugin_id.lower()
    return ".fake" in lowered or ".mock" in lowered
