from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTabWidget, QVBoxLayout

from aimn.ui.plugins_tab_v2 import PluginsTabV2
from aimn.ui.settings_tab_v2 import SettingsTabV2


class PluginsDialog(QDialog):
    def __init__(self, app_root, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plugins & Settings")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.setMovable(True)
        self._tabs.addTab(SettingsTabV2(app_root, self), "Settings")
        self._tabs.addTab(PluginsTabV2(app_root, self), "Plugins")
        layout.addWidget(self._tabs)

    def closeEvent(self, event) -> None:  # noqa: N802
        super().closeEvent(event)
