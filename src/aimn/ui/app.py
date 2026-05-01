from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from aimn.core.api import AppPaths, UiSettingsStore
from aimn.ui import assets as ui_assets
from aimn.ui.logging_setup import (
    enable_faulthandler,
    install_exception_hook,
    install_qt_message_handler,
    setup_logging,
)
from aimn.ui.main_window import MainWindow
from aimn.ui.theme import build_app_stylesheet, normalize_theme_id


def run() -> int:
    app_root = AppPaths.resolve().app_root
    setup_logging(app_root)
    enable_faulthandler(app_root)
    install_exception_hook()
    install_qt_message_handler()
    app = QApplication(sys.argv)
    ui_store = UiSettingsStore(app_root / "config" / "settings")
    theme_id = normalize_theme_id(str(ui_store.get("ui.theme") or ""))
    app.setProperty("aimn_theme_id", theme_id)
    app.setStyleSheet(build_app_stylesheet(theme_id))
    app.setWindowIcon(ui_assets.icon())
    logging.getLogger("aimn.ui").info("ui_start pid=%s", os.getpid())
    window = MainWindow()
    window.setWindowIcon(ui_assets.icon())
    window.show()
    return app.exec()
