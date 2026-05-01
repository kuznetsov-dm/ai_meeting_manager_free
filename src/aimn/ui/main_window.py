from __future__ import annotations

import tomllib

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import AppPaths
from aimn.core.release_profile import active_release_profile
from aimn.ui import assets as ui_assets
from aimn.ui.i18n import UiI18n
from aimn.ui.management_tab_v2 import ManagementTabV2
from aimn.ui.meetings_tab_v2 import MeetingsTabV2
from aimn.ui.plugins_tab_v2 import PluginsTabV2
from aimn.ui.settings_tab_v2 import SettingsTabV2
from aimn.ui.theme import build_app_stylesheet, normalize_theme_id
from aimn.ui.widgets.tiles import SelectableTile, TileModel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(1320, 800)

        self._paths = AppPaths.resolve()
        self._app_root = self._paths.app_root
        self._release_profile = active_release_profile(self._app_root)
        self._i18n = UiI18n(self._app_root, namespace="app")
        self.setWindowTitle(self._tr("title", "AI Meeting Notes"))
        self._runtime_info: dict[str, object] = {}
        self._tab_order: list[str] = ["meetings"]

        self._tabs = QTabWidget()
        self._tabs.setMovable(True)
        self._tabs.currentChanged.connect(self._sync_nav_tiles)
        self._meetings_tab = MeetingsTabV2(self._app_root)
        self._meetings_tab.runtimeInfoChanged.connect(self._on_runtime_info_changed)
        self._tabs.addTab(self._meetings_tab, self._tr("tab.meetings", "Meetings"))
        self._management_tab = None
        if self._release_profile.management_tab_visible():
            self._management_tab = ManagementTabV2(self._app_root)
            self._management_tab.evidenceOpenRequested.connect(self._on_management_evidence_open_requested)
            self._tabs.addTab(self._management_tab, self._tr("tab.management", "Management"))
            self._tab_order.append("management")
        self._settings_tab = SettingsTabV2(self._app_root)
        self._settings_tab.uiPreferencesChanged.connect(self._on_ui_preferences_changed)
        self._settings_tab.pathPreferencesChanged.connect(self._on_path_preferences_changed)
        self._settings_tab.pluginModelsChanged.connect(self._meetings_tab.on_plugin_models_changed)
        self._plugins_tab = PluginsTabV2(self._app_root)
        self._plugins_tab.openPluginSettingsRequested.connect(self._on_open_plugin_settings_requested)
        self._plugins_tab.pluginsChanged.connect(self._meetings_tab.refresh_plugin_catalog_state)
        self._tabs.addTab(self._settings_tab, self._tr("tab.settings", "Settings"))
        self._tab_order.append("settings")
        self._tabs.addTab(self._plugins_tab, self._tr("tab.plugins", "Plugins"))
        self._tab_order.append("plugins")
        self._tabs.tabBar().hide()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_nav_tiles(), 0)
        layout.addWidget(self._tabs, 1)
        self.setCentralWidget(container)

        status_bar = QStatusBar()
        self._status_text = QLabel(self._tr("status.ready", "Ready"))
        self._status_text.setObjectName("statusText")
        self._status_version = QLabel(self._app_version())
        self._status_version.setObjectName("statusMeta")
        status_bar.addWidget(self._status_text, 1)
        status_bar.addPermanentWidget(self._status_version)
        self.setStatusBar(status_bar)

    def _tr(self, key: str, default: str) -> str:
        return self._i18n.t(key, default)

    def _build_nav_tiles(self) -> QWidget:
        header = QFrame()
        header.setObjectName("appHeader")

        row = QHBoxLayout(header)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        logo_tile = QFrame()
        logo_tile.setObjectName("pipelineTileV2")
        logo_tile.setFixedSize(QSize(74, 74))
        logo_layout = QHBoxLayout(logo_tile)
        logo_layout.setContentsMargins(4, 4, 4, 4)
        logo_layout.setSpacing(0)
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setScaledContents(True)
        logo.setMinimumSize(QSize(66, 66))
        logo.setPixmap(ui_assets.pixmap("logo_mark_light.png", size=66))
        logo_layout.addWidget(logo, 1)
        row.addWidget(logo_tile, 0)

        self._nav_tiles: dict[str, SelectableTile] = {}
        tabs = [("tab_meetings", self._tr("tab.meetings", "Meetings"), "meetings")]
        if self._management_tab is not None:
            tabs.append(("tab_management", self._tr("tab.management", "Management"), "management"))
        tabs.extend(
            [
                ("tab_settings", self._tr("tab.settings", "Settings"), "settings"),
                ("tab_plugins", self._tr("tab.plugins", "Plugins"), "plugins"),
            ]
        )
        for tid, title, key in tabs:
            tile = SelectableTile(
                TileModel(tile_id=tid, title=title, subtitle=""),
                parent=header,
            )
            tile.clicked.connect(lambda _tid, _key=key: self._tabs.setCurrentIndex(self._tab_order.index(_key)))
            self._nav_tiles[tid] = tile
            row.addWidget(tile, 0)

        row.addStretch(1)
        self._system_tile = QFrame()
        self._system_tile.setObjectName("pipelineTileV2")
        self._system_tile.setFixedSize(QSize(460, 74))
        tile_layout = QHBoxLayout(self._system_tile)
        tile_layout.setContentsMargins(10, 8, 10, 8)
        tile_layout.setSpacing(10)

        left = QWidget(self._system_tile)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        self._system_title = QLabel(self._tr("system.title", "Status"))
        self._system_title.setObjectName("pipelineTileName")
        self._system_primary = QLabel(self._tr("system.idle", "Idle"))
        self._system_primary.setObjectName("pipelineTileStatus")
        left_layout.addWidget(self._system_title)
        left_layout.addWidget(self._system_primary, 1)
        tile_layout.addWidget(left, 0)

        self._system_info = QLabel("")
        self._system_info.setObjectName("pipelineMetaLabel")
        self._system_info.setWordWrap(True)
        self._system_info.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        tile_layout.addWidget(self._system_info, 1)
        row.addWidget(self._system_tile, 0, Qt.AlignRight)

        self._render_runtime_tile()
        self._sync_nav_tiles(self._tabs.currentIndex())
        return header

    def _sync_nav_tiles(self, index: int) -> None:
        key = self._tab_order[int(index)] if 0 <= int(index) < len(self._tab_order) else ""
        selected_id = {
            "meetings": "tab_meetings",
            "management": "tab_management",
            "settings": "tab_settings",
            "plugins": "tab_plugins",
        }.get(key)
        if key == "management" and self._management_tab is not None:
            try:
                reload_if_stale = getattr(self._management_tab, "reload_if_stale", None)
                if callable(reload_if_stale):
                    reload_if_stale(max_age_seconds=2.5)
                else:
                    self._management_tab.reload()
            except Exception:
                pass
        for tid, tile in getattr(self, "_nav_tiles", {}).items():
            tile.set_selected(tid == selected_id)

    def _on_ui_preferences_changed(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        theme = payload.get("theme")
        if isinstance(theme, str) and theme.strip():
            normalized = normalize_theme_id(theme)
            app = QApplication.instance()
            app.setProperty("aimn_theme_id", normalized)
            app.setStyleSheet(build_app_stylesheet(normalized))

        locale = payload.get("locale")
        if isinstance(locale, str) and locale.strip():
            # Full locale application for all tabs happens on restart; update shell labels now.
            self._i18n = UiI18n(self._app_root, namespace="app")
            self.setWindowTitle(self._tr("title", "AI Meeting Notes"))
            self._status_text.setText(self._tr("status.ready", "Ready"))
            self._tabs.setTabText(0, self._tr("tab.meetings", "Meetings"))
            offset = 1
            if self._management_tab is not None:
                self._tabs.setTabText(offset, self._tr("tab.management", "Management"))
                offset += 1
            self._tabs.setTabText(offset, self._tr("tab.settings", "Settings"))
            self._tabs.setTabText(offset + 1, self._tr("tab.plugins", "Plugins"))
            label_map = {
                "tab_meetings": self._tr("tab.meetings", "Meetings"),
                "tab_management": self._tr("tab.management", "Management"),
                "tab_settings": self._tr("tab.settings", "Settings"),
                "tab_plugins": self._tr("tab.plugins", "Plugins"),
            }
            for tile_id, tile in self._nav_tiles.items():
                title = label_map.get(tile_id, "")
                tile.apply(TileModel(tile_id=tile_id, title=title, subtitle=""))
            self._sync_nav_tiles(self._tabs.currentIndex())
            self._render_runtime_tile()
            for tab in (self._meetings_tab, self._management_tab, self._settings_tab, self._plugins_tab):
                if tab is None:
                    continue
                refresh_locale = getattr(tab, "refresh_locale", None)
                if callable(refresh_locale):
                    try:
                        refresh_locale()
                    except Exception:
                        pass

    def _on_path_preferences_changed(self, payload: dict) -> None:
        apply_preferences = getattr(self._meetings_tab, "apply_path_preferences", None)
        if callable(apply_preferences):
            try:
                apply_preferences(payload if isinstance(payload, dict) else {})
            except Exception:
                pass

    def _on_runtime_info_changed(self, payload: dict) -> None:
        self._runtime_info = dict(payload) if isinstance(payload, dict) else {}
        self._render_runtime_tile()

    def _on_management_evidence_open_requested(self, payload: dict) -> None:
        self._tabs.setCurrentIndex(0)
        navigate = getattr(self._meetings_tab, "navigate_to_management_evidence", None)
        if callable(navigate):
            try:
                navigate(payload if isinstance(payload, dict) else {})
            except Exception:
                pass

    def _on_open_plugin_settings_requested(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        self._tabs.setCurrentIndex(2)
        navigate = getattr(self._settings_tab, "navigate_to_plugin", None)
        if callable(navigate):
            try:
                navigate(pid)
            except Exception:
                pass

    def _render_runtime_tile(self) -> None:
        if not hasattr(self, "_system_tile"):
            return
        info = dict(self._runtime_info or {})
        self._system_title.setText(self._tr("system.title", "Status"))
        stage_name = str(info.get("stage_name", "") or "").strip()
        summary = str(info.get("summary", "") or "").strip()
        plugin_name = str(info.get("plugin_name", "") or "").strip()
        running = bool(info.get("running", False))
        if stage_name:
            primary = stage_name
        elif summary:
            primary = summary
        else:
            primary = self._tr("system.idle", "Idle")
        self._system_primary.setText(primary)

        plugin_prefix = self._tr("system.plugin_prefix", "Plugin:")
        info_lines: list[str] = []
        if plugin_name:
            info_lines.append(f"{plugin_prefix} {plugin_name}")
        if summary and summary != primary:
            info_lines.append(summary)
        for item in list(info.get("log_lines", []) or [])[:3]:
            text = str(item or "").strip()
            if text:
                info_lines.append(text)
        self._system_info.setText("\n".join(info_lines[:4]))

        tooltip_lines = [self._system_title.text(), primary]
        tooltip_lines.extend(info_lines)
        self._system_tile.setToolTip("\n".join([line for line in tooltip_lines if line]))
        self._system_tile.setProperty("attention", bool(running))
        try:
            style = self._system_tile.style()
            style.unpolish(self._system_tile)
            style.polish(self._system_tile)
            self._system_tile.update()
        except Exception:
            pass

    def _app_version(self) -> str:
        repo_root = self._paths.repo_root
        try:
            data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
            return str(data.get("project", {}).get("version", ""))
        except Exception:
            return ""

    def closeEvent(self, event) -> None:  # noqa: N802
        self._meetings_tab.shutdown()
        if self._management_tab is not None:
            self._management_tab.shutdown()
        super().closeEvent(event)
