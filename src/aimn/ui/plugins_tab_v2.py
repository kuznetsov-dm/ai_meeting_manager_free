from __future__ import annotations

from math import ceil
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import PluginCatalogService, PluginPackageService, PluginSyncService
from aimn.core.release_profile import active_release_profile
from aimn.ui.i18n import UiI18n
from aimn.ui.widgets.stage_nav_bar_v2 import StageNavBarV2
from aimn.ui.widgets.tiles import ListTileModel, SelectableListTile

_PRIMARY_STAGE_IDS = {
    "input",
    "media_convert",
    "transcription",
    "llm_processing",
    "management",
    "service",
}

class PluginsTabV2(QWidget):
    """
    Plugins navigation v2 (matches Meetings concept):
    - Top: stage tiles (plus "Other")
    - Selected stage: left plugins + right details
    - No stage selected: full-width plugin tiles only
    """
    openPluginSettingsRequested = Signal(str)
    pluginsChanged = Signal()

    def __init__(self, app_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_root = app_root
        self._i18n = UiI18n(app_root, namespace="plugins")
        self._release_profile = active_release_profile(app_root)
        self._catalog_service = PluginCatalogService(app_root)
        self._package_service = PluginPackageService(app_root)
        self._sync_service = PluginSyncService(app_root)
        self._payload: dict[str, object] = {}
        self._source = ""
        self._path: Path | None = None
        self._active_stage_id: str = "transcription"
        self._active_plugin_id: str = ""
        self._last_overview_cols: int = 0
        self._overview_reflow_scheduled: bool = False
        self._tiles: dict[str, SelectableListTile] = {}
        self._tiles_order: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(self._tr("title", "Plugins"))
        title.setObjectName("pageTitle")
        header.addWidget(title, 1)
        self._restart_notice = QLabel(self._tr("restart_notice", "Restart required to apply plugin changes."))
        self._restart_notice.setObjectName("pipelineMetaLabel")
        self._restart_notice.setVisible(False)
        header.addWidget(self._restart_notice, 0)
        self._install_btn = QPushButton(self._tr("button.install_package", "Install package"))
        self._install_btn.clicked.connect(self._install_package)
        self._install_btn.setVisible(self._release_profile.package_management_enabled())
        header.addWidget(self._install_btn, 0)
        self._sync_catalog_btn = QPushButton(self._tr("button.sync_catalog", "Sync catalog"))
        self._sync_catalog_btn.clicked.connect(self._sync_catalog)
        self._sync_catalog_btn.setVisible(self._release_profile.plugin_marketplace_visible())
        header.addWidget(self._sync_catalog_btn, 0)
        self._import_license_btn = QPushButton(self._tr("button.import_license", "Import license"))
        self._import_license_btn.clicked.connect(self._import_entitlements)
        header.addWidget(self._import_license_btn, 0)
        layout.addLayout(header)

        self._registry_label = QLabel("")
        self._registry_label.setObjectName("pipelineMetaLabel")
        self._registry_label.setWordWrap(True)
        layout.addWidget(self._registry_label, 0)

        self._stage_bar = StageNavBarV2(
            subtitle=self._tr("title", "Plugins"),
            allow_clear_selection=True,
        )
        self._stage_bar.set_label_provider(self._stage_label)
        self._stage_bar.stageSelected.connect(self._on_stage_selected)
        layout.addWidget(self._stage_bar, 0)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._tiles_scroll = QScrollArea()
        self._tiles_scroll.setWidgetResizable(True)
        self._tiles_scroll.setFrameShape(QScrollArea.NoFrame)
        self._tiles_scroll.setMinimumWidth(460)
        self._tiles_scroll.setMaximumWidth(460)
        self._tiles_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._tiles_container = QWidget()
        self._tiles_grid = QGridLayout(self._tiles_container)
        self._tiles_grid.setContentsMargins(0, 0, 0, 0)
        self._tiles_grid.setHorizontalSpacing(0)
        self._tiles_grid.setVerticalSpacing(10)
        self._tiles_scroll.setWidget(self._tiles_container)
        body.addWidget(self._tiles_scroll, 0)

        self._details_scroll = QScrollArea()
        self._details_scroll.setWidgetResizable(True)
        self._details_scroll.setFrameShape(QScrollArea.NoFrame)
        self._details_container = QWidget()
        self._details_layout = QVBoxLayout(self._details_container)
        self._details_layout.setContentsMargins(0, 0, 0, 0)
        self._details_layout.setSpacing(10)

        self._hero_card = QFrame()
        self._hero_card.setObjectName("pluginHeroCard")
        self._hero_card.setProperty("card", True)
        hero_layout = QVBoxLayout(self._hero_card)
        hero_layout.setContentsMargins(14, 12, 14, 12)
        hero_layout.setSpacing(6)

        self._hero_title = QLabel("")
        self._hero_title.setObjectName("pluginHeroTitle")
        self._hero_title.setWordWrap(True)
        hero_layout.addWidget(self._hero_title)

        self._hero_tagline = QLabel("")
        self._hero_tagline.setObjectName("pluginHeroTagline")
        self._hero_tagline.setWordWrap(True)
        hero_layout.addWidget(self._hero_tagline)

        self._hero_body = QLabel("")
        self._hero_body.setObjectName("pluginHeroBody")
        self._hero_body.setTextFormat(Qt.RichText)
        self._hero_body.setWordWrap(True)
        hero_layout.addWidget(self._hero_body)

        self._actions_row = QWidget()
        actions_layout = QHBoxLayout(self._actions_row)
        actions_layout.setContentsMargins(0, 2, 0, 0)
        actions_layout.setSpacing(8)
        self._catalog_install_btn = QPushButton(self._tr("button.install_catalog", "Install from catalog"))
        self._catalog_install_btn.clicked.connect(self._install_selected_from_catalog)
        self._catalog_install_btn.setVisible(self._release_profile.package_management_enabled())
        actions_layout.addWidget(self._catalog_install_btn, 0)
        self._update_btn = QPushButton(self._tr("button.update_package", "Update package"))
        self._update_btn.clicked.connect(self._update_selected_plugin)
        self._update_btn.setVisible(self._release_profile.package_management_enabled())
        actions_layout.addWidget(self._update_btn, 0)
        self._remove_btn = QPushButton(self._tr("button.remove_plugin", "Remove installed override"))
        self._remove_btn.clicked.connect(self._remove_selected_plugin)
        self._remove_btn.setVisible(self._release_profile.package_management_enabled())
        actions_layout.addWidget(self._remove_btn, 0)
        actions_layout.addStretch(1)
        hero_layout.addWidget(self._actions_row)

        self._details_layout.addWidget(self._hero_card, 0)

        self._howto_card = QFrame()
        self._howto_card.setObjectName("pluginHowToCard")
        self._howto_card.setProperty("card", True)
        howto_layout = QVBoxLayout(self._howto_card)
        howto_layout.setContentsMargins(14, 12, 14, 12)
        howto_layout.setSpacing(6)
        howto_title = QLabel(self._tr("howto_title", "How to use"))
        howto_title.setObjectName("panelTitle")
        howto_layout.addWidget(howto_title)
        self._howto_body = QLabel("")
        self._howto_body.setObjectName("pluginHowTo")
        self._howto_body.setWordWrap(True)
        howto_layout.addWidget(self._howto_body)
        self._details_layout.addWidget(self._howto_card, 0)

        self._models_card = QFrame()
        self._models_card.setObjectName("pluginModelsCard")
        self._models_card.setProperty("card", True)
        models_layout = QVBoxLayout(self._models_card)
        models_layout.setContentsMargins(14, 12, 14, 12)
        models_layout.setSpacing(6)
        self._models_title = QLabel(self._tr("models_title", "Available models"))
        self._models_title.setObjectName("panelTitle")
        models_layout.addWidget(self._models_title)
        self._models_body = QLabel("")
        self._models_body.setObjectName("pipelineMetaLabel")
        self._models_body.setWordWrap(True)
        models_layout.addWidget(self._models_body)
        self._models_card.setVisible(False)
        self._details_layout.addWidget(self._models_card, 0)

        self._tech_card = QFrame()
        self._tech_card.setObjectName("pluginTechCard")
        self._tech_card.setProperty("card", True)
        tech_layout = QVBoxLayout(self._tech_card)
        tech_layout.setContentsMargins(14, 12, 14, 12)
        tech_layout.setSpacing(6)
        tech_title = QLabel(self._tr("tech_title", "Technical details"))
        tech_title.setObjectName("panelTitle")
        tech_layout.addWidget(tech_title)

        self._details_meta = QWidget()
        self._details_meta_layout = QVBoxLayout(self._details_meta)
        self._details_meta_layout.setContentsMargins(0, 0, 0, 0)
        self._details_meta_layout.setSpacing(2)
        tech_layout.addWidget(self._details_meta)
        self._details_layout.addWidget(self._tech_card, 0)

        self._details_layout.addStretch(1)

        self._details_scroll.setWidget(self._details_container)
        body.addWidget(self._details_scroll, 1)

        layout.addLayout(body, 1)
        self.reload()

    def _tr(self, key: str, default: str) -> str:
        return self._i18n.t(key, default)

    def _stage_label(self, stage_id: str) -> str:
        sid = str(stage_id or "").strip()
        defaults = {
            "input": "Input",
            "media_convert": "Convert",
            "transcription": "Transcription",
            "llm_processing": "AI Processing",
            "management": "Management",
            "service": "Service",
            "other": "Other",
        }
        return self._tr(f"stage.{sid}", defaults.get(sid, sid))

    def _fmt(self, key: str, default: str, **kwargs: object) -> str:
        template = self._tr(key, default)
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def reload(self) -> None:
        snapshot = self._catalog_service.load()
        registry = snapshot.registry
        self._payload = registry.payload if isinstance(registry.payload, dict) else {}
        self._source = registry.source
        self._path = registry.path
        path_text = str(self._path) if self._path else ""
        self._registry_label.setText(
            self._fmt(
                "registry_priority",
                "Configuration priority: runtime > user > default | Active source: {source}{path}",
                source=self._source,
                path=(f" ({path_text})" if path_text else ""),
            )
        )

        self._stage_bar.set_selected(self._active_stage_id)
        self._render()
        if self._active_stage_id and (not self._active_plugin_id) and self._tiles_order:
            self._select_plugin(self._tiles_order[0])
        else:
            self._refresh_action_buttons(None)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._active_stage_id:
            return
        cols = self._overview_columns()
        if cols != self._last_overview_cols:
            self._render()

    def _on_stage_selected(self, stage_id: str) -> None:
        self._active_stage_id = str(stage_id or "").strip()
        self._active_plugin_id = ""
        self._render()
        if self._active_stage_id and self._tiles_order:
            self._select_plugin(self._tiles_order[0])

    def _render(self) -> None:
        snapshot = self._catalog_service.load()
        catalog = snapshot.catalog

        self.setToolTip(
            self._fmt(
                "registry_priority",
                "Configuration priority: runtime > user > default | Active source: {source}{path}",
                source=self._source,
                path="",
            )
        )

        for i in reversed(range(self._tiles_grid.count())):
            item = self._tiles_grid.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._tiles = {}
        self._tiles_order = []

        overview_mode = not bool(self._active_stage_id)
        self._apply_layout_mode(overview_mode)
        if overview_mode:
            self._schedule_overview_reflow()

        plugins = self._plugins_for_active_stage(catalog)

        if not plugins:
            empty = QLabel(self._empty_stage_message())
            empty.setObjectName("pipelineMetaLabel")
            empty.setWordWrap(True)
            self._tiles_grid.addWidget(empty, 0, 0, 1, 2)
            return

        cols = self._overview_columns() if overview_mode else 1
        self._last_overview_cols = cols if overview_mode else 0
        for col in range(8):
            self._tiles_grid.setColumnStretch(col, 0)
        for col in range(cols):
            self._tiles_grid.setColumnStretch(col, 1)
        for idx, plugin in enumerate(plugins):
            row = idx // cols
            col = idx % cols
            subtitle = self._tile_subtitle(plugin, catalog)
            status_label, status_bg, status_fg = self._plugin_status(plugin)
            model = ListTileModel(
                tile_id=plugin.plugin_id,
                title=catalog.display_name(plugin.plugin_id),
                subtitle=subtitle,
                status_label=status_label,
                status_bg=status_bg,
                status_fg=status_fg,
                meta_lines=self._plugin_meta_lines(plugin, catalog),
                tooltip=plugin.plugin_id,
                selected=(not overview_mode and plugin.plugin_id == self._active_plugin_id),
                disabled=(not plugin.installed) or (plugin.runtime_state == "visible_locked"),
                checked=bool(plugin.runtime_state == "active"),
            )
            tile = SelectableListTile(model, parent=self._tiles_container)
            tile.clicked.connect(self._select_plugin)
            tile.doubleClicked.connect(self._on_tile_double_clicked)
            tile.toggled.connect(self._on_tile_toggled)
            self._tiles[plugin.plugin_id] = tile
            self._tiles_order.append(plugin.plugin_id)
            self._tiles_grid.addWidget(tile, row, col)
        self._tiles_grid.setRowStretch((len(plugins) // cols) + 1, 1)

        if not overview_mode and self._active_plugin_id:
            self._select_plugin(self._active_plugin_id)

    def _select_plugin(self, plugin_id: str) -> None:
        if not self._active_stage_id:
            self._active_plugin_id = ""
            for tile in self._tiles.values():
                tile.set_selected(False)
            return
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        self._active_plugin_id = pid
        for tid, tile in self._tiles.items():
            tile.set_selected(tid == pid)

        catalog = self._catalog_service.load().catalog
        plugin = catalog.plugin_by_id(pid)
        if not plugin:
            self._hero_title.setText("")
            self._hero_tagline.setText("")
            self._hero_body.setText("")
            self._howto_body.setText("")
            self._models_card.setVisible(False)
            self._models_body.setText("")
            self._refresh_action_buttons(None)
            return
        nav_stage = _nav_stage_for_plugin(plugin.stage_id)
        title = catalog.display_name(pid)
        tagline = self._tagline(plugin, catalog)
        body = self._marketing_body(plugin, catalog, nav_stage=nav_stage)

        self._hero_title.setText(title)
        self._hero_tagline.setText(tagline)
        self._hero_body.setText(body)

        self._howto_body.setText(self._howto_text(plugin, nav_stage))
        self._render_meta_lines(plugin, catalog, nav_stage=nav_stage)
        self._render_models_list(plugin, catalog)
        self._refresh_action_buttons(plugin)

    def _on_tile_double_clicked(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        self._select_plugin(pid)
        self.openPluginSettingsRequested.emit(pid)

    def _on_tile_toggled(self, plugin_id: str, enabled: bool) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        self._catalog_service.set_plugin_enabled(pid, enabled)
        self._restart_notice.setVisible(True)
        # Preserve current stage and selected plugin after reload.
        selected = self._active_plugin_id or pid
        self.reload()
        self._select_plugin(selected)
        self.pluginsChanged.emit()

    def _install_package(self) -> None:
        if not self._release_profile.package_management_enabled():
            return
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            self._tr("dialog.install_package", "Install plugin package"),
            str(self._app_root),
            "Plugin packages (*.zip);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            result = self._package_service.install_from_path(Path(file_path))
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._tr("dialog.install_failed_title", "Install failed"),
                str(exc),
            )
            return
        self._restart_notice.setVisible(True)
        self.reload()
        self._select_plugin(result.plugin_id)
        self.pluginsChanged.emit()
        QMessageBox.information(
            self,
            self._tr("dialog.install_done_title", "Plugin installed"),
            self._fmt(
                "dialog.install_done_message",
                "Installed {plugin_id} {version}.",
                plugin_id=result.plugin_id,
                version=result.version,
            ),
        )

    def _sync_catalog(self) -> None:
        try:
            result = self._sync_service.sync_catalog()
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._tr("dialog.sync_catalog_failed_title", "Catalog sync failed"),
                str(exc),
            )
            return
        self.reload()
        self.pluginsChanged.emit()
        QMessageBox.information(
            self,
            self._tr("dialog.sync_catalog_done_title", "Catalog synced"),
            self._fmt(
                "dialog.sync_catalog_done_message",
                "Catalog synced from {source}. Plugins discovered: {count}.",
                source=result.source,
                count=result.plugin_count,
            ),
        )

    def _import_entitlements(self) -> None:
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            self._tr("dialog.import_license", "Import license"),
            str(self._app_root),
            "JSON files (*.json);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            result = self._sync_service.import_entitlements(file_path)
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._tr("dialog.import_license_failed_title", "License import failed"),
                str(exc),
            )
            return
        self.reload()
        self.pluginsChanged.emit()
        QMessageBox.information(
            self,
            self._tr("dialog.import_license_done_title", "License imported"),
            self._fmt(
                "dialog.import_license_done_message",
                "License imported ({reason}). Platform edition enabled: {enabled}.",
                reason=result.reason,
                enabled="yes" if result.platform_edition_enabled else "no",
            ),
        )

    def _update_selected_plugin(self) -> None:
        if not self._release_profile.package_management_enabled():
            return
        plugin = self._catalog_service.load().catalog.plugin_by_id(self._active_plugin_id)
        if not plugin:
            return
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            self._tr("dialog.update_package", "Update plugin package"),
            str(self._app_root),
            "Plugin packages (*.zip);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            result = self._package_service.install_from_path(
                Path(file_path),
                expected_plugin_id=plugin.plugin_id,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._tr("dialog.update_failed_title", "Update failed"),
                str(exc),
            )
            return
        self._restart_notice.setVisible(True)
        self.reload()
        self._select_plugin(result.plugin_id)
        self.pluginsChanged.emit()
        QMessageBox.information(
            self,
            self._tr("dialog.update_done_title", "Plugin updated"),
            self._fmt(
                "dialog.update_done_message",
                "Updated {plugin_id} to {version}.",
                plugin_id=result.plugin_id,
                version=result.version,
            ),
        )

    def _remove_selected_plugin(self) -> None:
        if not self._release_profile.package_management_enabled():
            return
        plugin = self._catalog_service.load().catalog.plugin_by_id(self._active_plugin_id)
        if not plugin or plugin.source_kind != "installed":
            return
        result = QMessageBox.question(
            self,
            self._tr("dialog.remove_title", "Remove plugin override"),
            self._fmt(
                "dialog.remove_confirm",
                "Remove installed override for {plugin_id}?",
                plugin_id=plugin.plugin_id,
            ),
        )
        if result != QMessageBox.Yes:
            return
        try:
            self._package_service.remove_installed_plugin(plugin.plugin_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._tr("dialog.remove_failed_title", "Remove failed"),
                str(exc),
            )
            return
        self._restart_notice.setVisible(True)
        self.reload()
        self._select_plugin(plugin.plugin_id)
        self.pluginsChanged.emit()

    def _install_selected_from_catalog(self) -> None:
        if not self._release_profile.package_management_enabled():
            return
        plugin = self._catalog_service.load().catalog.plugin_by_id(self._active_plugin_id)
        if not plugin or not plugin.download_url:
            return
        if plugin.runtime_state == "installable_locked":
            QMessageBox.warning(
                self,
                self._tr("dialog.install_failed_title", "Install failed"),
                self._tr(
                    "dialog.catalog_locked_message",
                    "This catalog plugin is still locked by edition or entitlement.",
                ),
            )
            return
        try:
            result = self._package_service.install_from_catalog(plugin.plugin_id)
        except Exception as exc:
            QMessageBox.warning(
                self,
                self._tr("dialog.install_failed_title", "Install failed"),
                str(exc),
            )
            return
        self._restart_notice.setVisible(True)
        self.reload()
        self._select_plugin(result.plugin_id)
        QMessageBox.information(
            self,
            self._tr("dialog.install_done_title", "Plugin installed"),
            self._fmt(
                "dialog.install_catalog_done_message",
                "Installed {plugin_id} {version} from catalog ({trust_level}/{verification_state}).",
                plugin_id=result.plugin_id,
                version=result.version,
                trust_level=result.trust_level or "untrusted_local",
                verification_state=result.verification_state or "untrusted",
            ),
        )

    def _refresh_action_buttons(self, plugin) -> None:
        if not self._release_profile.package_management_enabled():
            self._catalog_install_btn.setEnabled(False)
            self._catalog_install_btn.setVisible(False)
            self._update_btn.setEnabled(False)
            self._remove_btn.setEnabled(False)
            return
        show_catalog_install = bool(plugin and plugin.download_url and (plugin.remote_only or plugin.has_update))
        self._catalog_install_btn.setVisible(show_catalog_install)
        if show_catalog_install and plugin:
            if plugin.remote_only:
                self._catalog_install_btn.setText(self._tr("button.install_catalog", "Install from catalog"))
                self._catalog_install_btn.setEnabled(plugin.runtime_state == "installable")
            else:
                self._catalog_install_btn.setText(self._tr("button.update_catalog", "Update from catalog"))
                self._catalog_install_btn.setEnabled(bool(plugin.has_update))
        else:
            self._catalog_install_btn.setText(self._tr("button.install_catalog", "Install from catalog"))
            self._catalog_install_btn.setEnabled(False)
        can_update = bool(plugin and plugin.source_kind == "installed")
        self._update_btn.setEnabled(can_update)
        self._remove_btn.setEnabled(can_update)

    def _empty_stage_message(self) -> str:
        sid = str(self._active_stage_id or "").strip().lower()
        if self._release_profile.profile_id == "core_free" and sid == "management":
            return self._tr(
                "empty.management_core_free",
                "Management extensions are available in Pro. Core Free keeps the stage only for pipeline compatibility.",
            )
        if self._release_profile.profile_id == "core_free" and sid == "service":
            return self._tr(
                "empty.service_core_free",
                "Service extensions are not bundled in Core Free. Add them in another release profile later.",
            )
        return self._tr("no_plugins_for_section", "No plugins available for this section.")

    def _plugin_status(self, plugin) -> tuple[str, str, str]:
        if plugin.remote_only and plugin.runtime_state == "installable":
            return self._tr("status.installable", "Installable"), "#DBEAFE", "#1D4ED8"
        if plugin.remote_only and plugin.runtime_state == "installable_locked":
            return self._tr("status.catalog_locked", "Locked in catalog"), "#FEE2E2", "#B91C1C"
        if plugin.has_update:
            return self._tr("status.update_available", "Update available"), "#DBEAFE", "#1D4ED8"
        if not plugin.installed:
            return self._tr("status.not_installed", "Not installed"), "#FEE2E2", "#B91C1C"
        if plugin.runtime_state == "visible_locked":
            if plugin.access_state == "platform_locked":
                return self._tr("status.platform_locked", "Platform locked"), "#EDE9FE", "#6D28D9"
            if plugin.access_state == "subscription_required":
                return self._tr("status.subscription_required", "Subscription required"), "#FEE2E2", "#B91C1C"
            if plugin.access_state == "purchase_required":
                return self._tr("status.purchase_required", "Purchase required"), "#FEE2E2", "#B91C1C"
            if plugin.access_state == "revoked":
                return self._tr("status.revoked", "Access revoked"), "#FEE2E2", "#B91C1C"
            return self._tr("status.locked", "Locked"), "#FEE2E2", "#B91C1C"
        if plugin.access_state == "grace" and plugin.runtime_state == "active":
            return self._tr("status.grace", "Grace period"), "#FEF3C7", "#92400E"
        if plugin.runtime_state == "active":
            return self._tr("status.active", "Active"), "#DCFCE7", "#166534"
        return self._tr("status.available", "Available"), "#FEF3C7", "#92400E"

    @staticmethod
    def _plugin_meta_lines(plugin, catalog) -> list[str]:
        lines: list[str] = []
        if plugin.source_kind:
            lines.append(f"Source: {plugin.source_kind}")
        if plugin.remote_only and plugin.remote_version:
            lines.append(f"Catalog version: {plugin.remote_version}")
        elif plugin.has_update and plugin.remote_version:
            lines.append(f"Update: {plugin.remote_version}")
        if plugin.pricing_model:
            lines.append(f"License: {plugin.pricing_model}")
        tags = getattr(plugin, "tags", None)
        if isinstance(tags, list):
            for item in tags:
                text = str(item or "").strip()
                if text:
                    lines.append(text)
                if len(lines) >= 2:
                    break
        provider = catalog.provider_label(plugin.plugin_id)
        if provider:
            lines.append(f"Provider: {provider}")
        if plugin.version and len(lines) < 3:
            lines.append(f"Version: {plugin.version}")
        return lines[:3] or [f"ID: {plugin.plugin_id}"]

    def _plugins_for_active_stage(self, catalog) -> list:
        plugins = sorted(catalog.all_plugins(), key=lambda p: (catalog.display_name(p.plugin_id), p.plugin_id))
        if not self._active_stage_id:
            return plugins
        if self._active_stage_id == "other":
            return [plugin for plugin in plugins if _nav_stage_for_plugin(plugin.stage_id) == "other"]
        return [plugin for plugin in plugins if _nav_stage_for_plugin(plugin.stage_id) == self._active_stage_id]

    def _apply_layout_mode(self, overview_mode: bool) -> None:
        self._details_scroll.setVisible(not overview_mode)
        if overview_mode:
            self._tiles_scroll.setMinimumWidth(0)
            self._tiles_scroll.setMaximumWidth(16777215)
            self._tiles_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            return
        self._tiles_scroll.setMinimumWidth(460)
        self._tiles_scroll.setMaximumWidth(460)
        self._tiles_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def _schedule_overview_reflow(self) -> None:
        if self._overview_reflow_scheduled:
            return
        self._overview_reflow_scheduled = True
        QTimer.singleShot(0, self._apply_overview_reflow)

    def _apply_overview_reflow(self) -> None:
        self._overview_reflow_scheduled = False
        if self._active_stage_id:
            return
        cols = self._overview_columns()
        if cols != self._last_overview_cols:
            self._render()

    def _overview_columns(self) -> int:
        viewport_width = int(self._tiles_scroll.viewport().width() or 0)
        host_width = int(self.width() or 0)
        if host_width > 0:
            # When switching from fixed two-pane mode, viewport can report stale width
            # for one event loop tick. Prefer the host width to avoid initial under-layout.
            viewport_width = max(viewport_width, host_width - 28)
        if viewport_width <= 0:
            return 2
        # Keep card width close to the regular one (~460px): when there's extra space,
        # add columns instead of stretching existing cards.
        target_max_tile_width = 460
        cols = max(1, int(ceil(viewport_width / float(target_max_tile_width))))
        return max(2, min(cols, 8))

    def _render_models_list(self, plugin, catalog) -> None:
        lines = self._model_lines(plugin, catalog)
        if not lines:
            self._models_card.setVisible(False)
            self._models_body.setText("")
            return
        self._models_card.setVisible(True)
        self._models_body.setText("\n".join(f"- {line}" for line in lines))

    def _model_lines(self, plugin, catalog) -> list[str]:
        rows: list[str] = []
        seen: set[str] = set()

        def add(label: str, value: str) -> None:
            lid = str(label or "").strip()
            vid = str(value or "").strip()
            if not vid:
                return
            row = f"{lid} ({vid})" if lid and lid != vid else vid
            key = row.lower()
            if key in seen:
                return
            seen.add(key)
            rows.append(row)

        for model_id, meta in sorted((plugin.model_info or {}).items(), key=lambda item: item[0]):
            if not isinstance(meta, dict):
                continue
            add(str(meta.get("model_name", "")).strip(), str(model_id))

        schema = catalog.schema_for(plugin.plugin_id)
        if schema:
            for setting in schema.settings:
                key = str(setting.key or "").strip().lower()
                if "model" not in key:
                    continue
                if setting.options:
                    for option in setting.options:
                        add(str(option.label or "").strip(), str(option.value))
                else:
                    add("", str(setting.value or "").strip())

        return rows

    def _render_meta_lines(self, plugin, catalog, *, nav_stage: str) -> None:
        for i in reversed(range(self._details_meta_layout.count())):
            item = self._details_meta_layout.takeAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        status = self._plugin_status(plugin)[0]
        lines = [
            self._fmt("meta.status", "Status: {status}", status=status),
            self._fmt("meta.section", "Section: {section}", section=_nav_stage_label(nav_stage)),
            self._fmt("meta.id", "ID: {plugin_id}", plugin_id=plugin.plugin_id),
        ]
        provider = catalog.provider_label(plugin.plugin_id)
        if provider:
            lines.insert(2, self._fmt("meta.provider", "Provider: {provider}", provider=provider))
        if plugin.version:
            lines.append(self._fmt("meta.version", "Version: {version}", version=plugin.version))
        if plugin.has_update and plugin.remote_version:
            lines.append(
                self._fmt("meta.catalog_version", "Catalog version: {version}", version=plugin.remote_version)
            )
        if plugin.trust_level:
            lines.append(
                self._fmt("meta.trust", "Trust: {value}", value=plugin.trust_level)
            )
        if plugin.verification_state:
            lines.append(
                self._fmt("meta.verification", "Verification: {value}", value=plugin.verification_state)
            )
        for idx, line in enumerate(lines):
            label = QLabel(line)
            label.setObjectName("listTileMetaPrimary" if idx == 0 else "listTileMeta")
            label.setWordWrap(True)
            self._details_meta_layout.addWidget(label)

    @staticmethod
    def _tagline(plugin, catalog) -> str:
        highlight = str(getattr(plugin, "highlights", "") or "").strip()
        if highlight:
            return highlight
        provider = str(catalog.provider_label(plugin.plugin_id) or "").strip()
        if provider:
            return provider
        return "This plugin adds capabilities to the meeting pipeline."

    @staticmethod
    def _marketing_body(plugin, catalog, *, nav_stage: str) -> str:
        desc = str(getattr(plugin, "description", "") or "").strip()
        if not desc:
            desc = str(catalog.provider_description(plugin.plugin_id) or "").strip()
        if not desc:
            desc = "This plugin adds capabilities to the meeting pipeline."

        highlight = str(getattr(plugin, "highlights", "") or "").strip()
        parts: list[str] = [f"<b>What it does</b><br>{_esc(desc)}"]
        if highlight:
            parts.append(f"<b>Why enable it</b><br>{_esc(highlight)}")
        parts.append(f"<b>Where it works</b><br>{_esc(_nav_stage_blurb(nav_stage))}")
        return "<br><br>".join(parts)

    def _howto_text(self, plugin, nav_stage: str) -> str:
        if plugin.remote_only:
            if plugin.runtime_state == "installable":
                return self._tr(
                    "howto.remote_installable",
                    "This plugin is visible from the remote catalog. Download/install flow is the next integration step.",
                )
            return self._tr(
                "howto.remote_locked",
                "This catalog plugin is visible for discovery, but it stays locked until the required edition or entitlement is active.",
            )
        steps = getattr(plugin, "howto", None)
        if isinstance(steps, list):
            normalized = [str(item or "").strip() for item in steps]
            normalized = [item for item in normalized if item]
            if normalized:
                return "\n".join(f"{idx + 1}. {line}" for idx, line in enumerate(normalized))
        if nav_stage == "transcription":
            return (
                "1. Open Settings > Transcription.\n"
                "2. Select model and verify binary path.\n"
                "3. Run a meeting to produce transcript."
            )
        if nav_stage == "llm_processing":
            return (
                "1. Open Settings > AI Processing.\n"
                "2. Select provider and model.\n"
                "3. Run a meeting to produce summary."
            )
        if nav_stage == "management":
            return (
                "1. Run AI Processing to generate summary.\n"
                "2. Management plugins extract tasks, projects, and agendas.\n"
                "3. Review results in the meeting workspace."
            )
        if nav_stage == "service":
            return (
                "1. Enable plugin.\n"
                "2. Use it in Meetings (search, indexing, integrations).\n"
                "3. Check logs for external service failures."
            )
        return "Enable the plugin to make it available in the app."

    @staticmethod
    def _tile_subtitle(plugin, catalog) -> str:
        highlight = str(getattr(plugin, "highlights", "") or "").strip()
        if highlight:
            return highlight
        provider = str(catalog.provider_label(plugin.plugin_id) or "").strip()
        if provider:
            return provider
        return _nav_stage_label(_nav_stage_for_plugin(plugin.stage_id))


def _nav_stage_for_plugin(stage_id: str) -> str:
    sid = str(stage_id or "").strip()
    return sid if sid in _PRIMARY_STAGE_IDS else "other"


def _esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
    )


def _nav_stage_label(nav_stage: str) -> str:
    return {
        "transcription": "Transcription",
        "llm_processing": "AI Processing",
        "management": "Management",
        "service": "Service",
        "other": "Other",
    }.get(str(nav_stage or "").strip(), str(nav_stage or "").strip() or "Other")


def _nav_stage_blurb(nav_stage: str) -> str:
    return {
        "transcription": "Converts audio into text so meetings can be analyzed further.",
        "llm_processing": "Builds summaries and structure from meeting text.",
        "management": "Turns results into tasks, projects, and agendas.",
        "service": "Adds service features: search, indexing, and integrations.",
        "other": "Additional app capabilities.",
    }.get(str(nav_stage or "").strip(), "Additional app capabilities.")
