from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import (
    AppPaths,
    PluginActionService,
    PluginCatalogService,
    PluginHealthService,
    PluginModelsService,
    SettingsService,
    UiSettingsStore,
)
from aimn.core.contracts import PluginDescriptor
from aimn.core.release_profile import active_release_profile
from aimn.ui.i18n import UiI18n
from aimn.ui.services.async_worker import run_async
from aimn.ui.theme import DEFAULT_THEME_ID, THEME_IDS, normalize_theme_id
from aimn.ui.widgets.credentials_hub import CredentialsHubPanel
from aimn.ui.widgets.model_cards import ModelCardsPanel
from aimn.ui.widgets.stage_nav_bar_v2 import StageNavBarV2
from aimn.ui.widgets.standard_components import StandardSelectableChip
from aimn.ui.widgets.tiles import ListTileModel, SelectableListTile

_LOGGER = logging.getLogger("aimn.ui.settings")

_UI_MEETING_RENAME_SETTINGS_ID = "ui.meeting_rename"
_UI_APP_PREFERENCES_SETTINGS_ID = "ui.app_preferences"
_UI_PATH_PREFERENCES_SETTINGS_ID = "ui.path_preferences"
_SETTINGS_STAGE_IDS = {
    "input",
    "media_convert",
    "transcription",
    "llm_processing",
    "management",
    "service",
}

_LOG = logging.getLogger("aimn.ui.settings")

_EXPECTED_PROVIDER_HEALTH_CODES = {
    "api_key_missing",
    "auth_error",
    "provider_blocked",
    "model_not_found",
    "not_available",
    "rate_limited",
    "request_failed",
    "bad_request",
    "empty_response",
}


def _is_secret(key: str) -> bool:
    lowered = str(key or "").lower()
    if lowered in {
        "key",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
    }:
        return True
    if lowered.startswith("api_key_") or lowered.endswith("_api_key") or lowered.endswith("apikey"):
        return True
    if lowered.endswith("_token") or lowered.endswith("_secret") or lowered.endswith("_password"):
        return True
    return lowered.endswith("_key") or lowered.endswith("_keys") or lowered.startswith("key_")


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)


def _is_expected_provider_health_issue(issue_codes: str) -> bool:
    codes = {
        str(item or "").strip().lower()
        for item in str(issue_codes or "").split(",")
        if str(item or "").strip()
    }
    if not codes:
        return False
    for code in codes:
        if code in _EXPECTED_PROVIDER_HEALTH_CODES:
            return True
        if any(token in code for token in _EXPECTED_PROVIDER_HEALTH_CODES):
            return True
    return False


class SettingsTabV2(QWidget):
    """
    Settings navigation v2 (matches Meetings concept):
    - Top: stage tiles (plus "Other")
    - Left: contextual sections (plugins for the selected stage)
    - Right: settings form for the selected section/plugin
    """

    uiPreferencesChanged = Signal(dict)
    pathPreferencesChanged = Signal(dict)
    pluginModelsChanged = Signal(str)

    def __init__(self, app_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_root = app_root
        self._i18n = UiI18n(app_root, namespace="settings")
        self._paths = AppPaths.resolve(app_root)
        self._release_profile = active_release_profile(app_root)
        self._catalog_service = PluginCatalogService(app_root)
        self._models_service = PluginModelsService(app_root)
        self._health_service = PluginHealthService(app_root, catalog_service=self._catalog_service)
        self._action_service = PluginActionService(app_root, catalog_service=self._catalog_service)
        self._catalog = self._catalog_service.load().catalog
        self._store = SettingsService(self._paths.config_dir / "settings", repo_root=app_root)
        self._ui_store = UiSettingsStore(self._paths.config_dir / "settings")

        self._active_stage_id: str = "transcription"
        self._active_section_id: str = ""
        self._field_widgets: dict[str, QWidget] = {}
        self._section_tiles: dict[str, SelectableListTile] = {}
        self._sections_order: list[str] = []
        self._rendering_form = False
        self._updating_prompt_manager_widgets = False
        self._active_prompt_profile_index = -1
        self._prompt_profiles: list[dict[str, str]] = []
        self._prompt_profiles_list: QListWidget | None = None
        self._prompt_profile_id: QLineEdit | None = None
        self._prompt_profile_label: QLineEdit | None = None
        self._prompt_profile_prompt: QPlainTextEdit | None = None
        self._prompt_profile_refine_btn: QPushButton | None = None
        self._prompt_active_profile: QWidget | None = None
        self._prompt_active_profile_buttons: dict[str, StandardSelectableChip] = {}
        self._prompt_active_profile_value: str = ""
        self._prompt_custom_default: QPlainTextEdit | None = None
        self._path_field_widgets: dict[str, QWidget] = {}
        self._secret_status_labels: dict[str, QLabel] = {}
        self._dirty_secret_fields: set[str] = set()
        self._secret_validation_timer = QTimer(self)
        self._secret_validation_timer.setSingleShot(True)
        self._secret_validation_timer.setInterval(700)
        self._secret_validation_timer.timeout.connect(self._run_secret_validation)
        self._secret_validation_request_id = 0
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(400)
        self._auto_save_timer.timeout.connect(self._save)
        self._pending_auto_save_section_id: str = ""
        self._models_panel: ModelCardsPanel | None = None
        self._credentials_hub: CredentialsHubPanel | None = None
        self._show_advanced = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self._stage_bar = StageNavBarV2(subtitle=self._tr("stage_bar.subtitle", "Settings"))
        self._stage_bar.set_label_provider(self._stage_label)
        self._stage_bar.stageSelected.connect(self._on_stage_selected)
        layout.addWidget(self._stage_bar, 0)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._sections_scroll = QScrollArea()
        self._sections_scroll.setWidgetResizable(True)
        self._sections_scroll.setFrameShape(QScrollArea.NoFrame)
        self._sections_scroll.setFixedWidth(440)
        self._sections_container = QWidget()
        self._sections_grid = QGridLayout(self._sections_container)
        self._sections_grid.setContentsMargins(0, 0, 0, 0)
        self._sections_grid.setHorizontalSpacing(0)
        self._sections_grid.setVerticalSpacing(10)
        self._sections_scroll.setWidget(self._sections_container)
        body.addWidget(self._sections_scroll, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(10)
        self._scroll.setWidget(self._container)
        body.addWidget(self._scroll, 1)

        layout.addLayout(body, 1)
        self.reload()

    def _tr(self, key: str, default: str) -> str:
        return self._i18n.t(key, default)

    def _fmt(self, key: str, default: str, **kwargs: object) -> str:
        template = self._tr(key, default)
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def _stage_label(self, stage_id: str) -> str:
        sid = str(stage_id or "").strip()
        defaults = {
            "input": "Input",
            "media_convert": "Convert",
            "transcription": "Transcription",
            "text_processing": "Semantic Processing",
            "llm_processing": "AI Processing",
            "management": "Management",
            "service": "Service",
            "other": "Other",
        }
        return self._tr(f"stage.{sid}", defaults.get(sid, sid))

    def reload(self) -> None:
        self._paths = AppPaths.resolve(self._app_root)
        self._catalog = self._catalog_service.load().catalog
        self._stage_bar.set_selected(self._active_stage_id)
        self._render_sections()

        if self._active_section_id:
            self._select_section(self._active_section_id)
            return
        if self._sections_order:
            self._select_section(self._sections_order[0])

    def navigate_to_plugin(self, plugin_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        if not pid:
            return False
        self._catalog = self._catalog_service.load().catalog
        plugin = self._catalog.plugin_by_id(pid)
        if plugin is None:
            return False
        stage_id = str(getattr(plugin, "stage_id", "") or "").strip()
        if stage_id not in _SETTINGS_STAGE_IDS:
            return False
        self._active_stage_id = stage_id
        self._stage_bar.set_selected(stage_id)
        self._render_sections()
        if pid in self._section_tiles:
            self._select_section(pid)
            return True
        if self._sections_order:
            self._select_section(self._sections_order[0])
        return False

    def _on_stage_selected(self, stage_id: str) -> None:
        self._active_stage_id = str(stage_id or "").strip() or "other"
        self._active_section_id = ""
        self._render_sections()
        if self._sections_order:
            self._select_section(self._sections_order[0])

    def _render_sections(self) -> None:
        for i in reversed(range(self._sections_grid.count())):
            item = self._sections_grid.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._section_tiles = {}
        self._sections_order = []

        if self._active_stage_id == "other":
            items = [
                (
                    self._tr("section.interface", "Interface"),
                    _UI_APP_PREFERENCES_SETTINGS_ID,
                    self._tr("section.interface_subtitle", "Language and visual theme"),
                ),
                (
                    self._tr("section.folders", "Folders"),
                    _UI_PATH_PREFERENCES_SETTINGS_ID,
                    self._tr("section.folders_subtitle", "Default input, monitoring, and output folders"),
                ),
                (
                    self._tr("section.credentials", "Credentials"),
                    "__credentials_hub__",
                    self._tr("section.credentials_subtitle", "API keys, tokens, and live validation in one place"),
                ),
                (
                    self._tr("section.about_paths", "About / Paths"),
                    "__other_about__",
                    self._tr("section.about_paths_subtitle", "Paths and config locations"),
                ),
                (
                    self._tr("section.meeting_rename", "Meeting Rename"),
                    _UI_MEETING_RENAME_SETTINGS_ID,
                    self._tr("section.meeting_rename_subtitle", "Rename policy and source-file safety"),
                ),
            ]
            tiles: list[ListTileModel] = []
            for label, sid, subtitle in items:
                tiles.append(
                    ListTileModel(
                        tile_id=sid,
                        title=label,
                        subtitle=subtitle,
                        status_label=self._tr("status.system", "System"),
                        status_bg="#DBEAFE",
                        status_fg="#1D4ED8",
                        meta_lines=[self._tr("meta.builtin_panel", "Built-in panel")],
                        tooltip=sid,
                    )
                )
            self._add_section_tiles(tiles)
            return

        plugins = self._plugins_for_stage(self._active_stage_id)
        tiles: list[ListTileModel] = []
        for plugin in plugins:
            title = self._catalog.display_name(plugin.plugin_id)
            provider = self._catalog.provider_label(plugin.plugin_id)
            subtitle = provider or plugin.stage_id
            status_label, status_bg, status_fg = self._plugin_status(plugin)
            tiles.append(
                ListTileModel(
                    tile_id=plugin.plugin_id,
                    title=title,
                    subtitle=subtitle,
                    status_label=status_label,
                    status_bg=status_bg,
                    status_fg=status_fg,
                    meta_lines=self._plugin_meta_lines(plugin),
                    tooltip=plugin.plugin_id,
                    disabled=(not plugin.installed) or (not plugin.entitled),
                )
            )

        if not plugins:
            empty = QLabel(self._empty_stage_message(self._active_stage_id))
            empty.setObjectName("pipelineMetaLabel")
            empty.setWordWrap(True)
            self._sections_grid.addWidget(empty, 0, 0, 1, 2)
            self._sections_order = ["__empty__"]
            return

        self._add_section_tiles(tiles)

    def _add_section_tiles(self, tiles: list[ListTileModel]) -> None:
        cols = 1
        for idx, model in enumerate(tiles):
            row = idx // cols
            col = idx % cols
            tile = SelectableListTile(model, parent=self._sections_container)
            tile.clicked.connect(self._select_section)
            self._section_tiles[model.tile_id] = tile
            self._sections_grid.addWidget(tile, row, col)
            self._sections_order.append(model.tile_id)
        self._sections_grid.setRowStretch((len(tiles) // cols) + 1, 1)

    def _empty_stage_message(self, stage_id: str) -> str:
        sid = str(stage_id or "").strip().lower()
        if self._release_profile.profile_id == "core_free" and sid == "management":
            return self._tr(
                "empty.management_core_free",
                "This release keeps the management stage for compatibility, but management plugins are available only in Pro.",
            )
        if self._release_profile.profile_id == "core_free" and sid == "service":
            return self._tr(
                "empty.service_core_free",
                "This release keeps the service stage for compatibility, but service plugins are not bundled in Core Free.",
            )
        return self._tr("empty.no_stage_settings", "No settings for this stage.")

    def _plugins_for_stage(self, stage_id: str) -> list[PluginDescriptor]:
        plugins = [p for p in self._catalog.plugins_for_stage(stage_id)]
        plugins.sort(key=lambda p: (self._catalog.display_name(p.plugin_id), p.plugin_id))
        return plugins

    def _select_section(self, section_id: str) -> None:
        sid = str(section_id or "").strip()
        self._active_section_id = sid
        for tid, tile in self._section_tiles.items():
            tile.set_selected(tid == sid)
        self._render_form()

    def _clear_form(self) -> None:
        self._secret_validation_request_id += 1
        self._secret_validation_timer.stop()
        for i in reversed(range(self._grid.count())):
            item = self._grid.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._field_widgets = {}
        self._models_panel = None
        self._credentials_hub = None
        self._path_field_widgets = {}
        self._secret_status_labels = {}
        self._dirty_secret_fields = set()
        self._updating_prompt_manager_widgets = False
        self._active_prompt_profile_index = -1
        self._prompt_profiles = []
        self._prompt_profiles_list = None
        self._prompt_profile_id = None
        self._prompt_profile_label = None
        self._prompt_profile_prompt = None
        self._prompt_profile_refine_btn = None
        self._prompt_active_profile = None
        self._prompt_active_profile_buttons = {}
        self._prompt_active_profile_value = ""
        self._prompt_custom_default = None

    def _render_form(self) -> None:
        self._clear_form()
        self._rendering_form = True

        if not self._active_section_id or self._active_section_id == "__empty__":
            self._advanced_toggle.setVisible(False)
            self._rendering_form = False
            return

        if self._active_section_id == "__other_about__":
            self._advanced_toggle.setVisible(False)
            rows = [
                (self._tr("about.repo_root", "Repo root"), str(self._app_root)),
                (self._tr("about.output_dir", "Output dir"), str(self._paths.output_dir)),
                (self._tr("about.config_dir", "Config dir"), str(self._paths.config_dir / "settings")),
                (self._tr("about.secrets_file", "Secrets file"), str(self._paths.config_dir / "secrets.toml")),
            ]
            for idx, (k, v) in enumerate(rows):
                self._grid.addWidget(QLabel(k), idx, 0)
                val = QLabel(v)
                val.setTextInteractionFlags(Qt.TextSelectableByMouse)
                self._grid.addWidget(val, idx, 1)
            self._rendering_form = False
            return

        if self._active_section_id == "__credentials_hub__":
            self._advanced_toggle.setVisible(False)
            header = QLabel(self._tr("credentials.title", "Credentials"))
            header.setObjectName("panelTitle")
            self._grid.addWidget(header, 0, 0, 1, 4)
            note = QLabel(
                self._tr(
                    "credentials.note",
                    "Manage provider secrets in one place. Enter or update a key to trigger live validation when the plugin supports it.",
                )
            )
            note.setObjectName("pipelineMetaLabel")
            note.setWordWrap(True)
            self._grid.addWidget(note, 1, 0, 1, 4)
            self._credentials_hub = CredentialsHubPanel(
                self._app_root,
                self._store,
                self._catalog_service,
                self._action_service,
                self._health_service,
                stage_label=self._stage_label,
                parent=self,
            )
            self._credentials_hub.settingsChanged.connect(self._on_credentials_hub_settings_changed)
            self._grid.addWidget(self._credentials_hub, 2, 0, 1, 4)
            self._rendering_form = False
            return

        if self._active_section_id == _UI_APP_PREFERENCES_SETTINGS_ID:
            self._render_ui_preferences_form()
            self._rendering_form = False
            return

        if self._active_section_id == _UI_PATH_PREFERENCES_SETTINGS_ID:
            self._render_path_preferences_form()
            self._rendering_form = False
            return

        if self._active_section_id == _UI_MEETING_RENAME_SETTINGS_ID:
            self._render_meeting_rename_form()
            self._rendering_form = False
            return

        columns = 4
        header = QLabel(self._catalog.display_name(self._active_section_id))
        header.setObjectName("panelTitle")
        self._grid.addWidget(header, 0, 0, 1, columns)

        row_offset = 1
        if self._plugin_has_models(self._active_section_id):
            self._models_panel = ModelCardsPanel(self._app_root, self._store, self._models_service, self)
            self._models_panel.modelsChanged.connect(self.pluginModelsChanged.emit)
            self._models_panel.set_advanced_mode(True)
            self._models_panel.set_plugin(self._active_section_id)
            self._grid.addWidget(self._models_panel, row_offset, 0, 1, columns)
            row_offset += 1

        schema = self._catalog.schema_for(self._active_section_id)
        if not schema:
            next_row = row_offset
            next_row = self._render_prompt_manager_editor_if_supported(next_row, columns)
            next_row = self._render_prompt_preview_if_supported(next_row, columns)
            if next_row == row_offset:
                self._grid.addWidget(
                    QLabel(self._tr("empty.no_schema", "No settings schema for this plugin.")),
                    row_offset,
                    0,
                )
            else:
                self._grid.addWidget(QWidget(), next_row, 0)
            self._rendering_form = False
            return

        current = self._store.get_settings(self._active_section_id, include_secrets=True)
        idx = 0

        basic_settings = []
        advanced_settings = []
        for setting in schema.settings:
            if self._should_hide_setting(self._active_section_id, setting.key):
                continue
            if getattr(setting, "advanced", False) or self._is_advanced_by_heuristic(setting.key):
                advanced_settings.append(setting)
            else:
                basic_settings.append(setting)

        visible_settings = list(basic_settings) + list(advanced_settings)
        for setting in visible_settings:
            key = setting.key
            value = current.get(key, setting.value)
            if key not in current:
                legacy = {
                    "embeddings_model_id": "model_id",
                    "embeddings_model_path": "model_path",
                    "embeddings_allow_download": "allow_download",
                }
                legacy_key = legacy.get(key)
                if legacy_key and legacy_key in current:
                    value = current.get(legacy_key, setting.value)
            secret = _is_secret(key)

            widget = self._build_widget(setting.options or [], value, secret=secret, editable=setting.editable)
            self._field_widgets[key] = widget
            self._wire_auto_save(widget)

            field = QWidget()
            box = QVBoxLayout(field)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            label = QLabel(setting.label or key)
            label.setObjectName("statusMeta")
            box.addWidget(label)
            box.addWidget(widget)
            if secret and isinstance(widget, QLineEdit):
                status_label = QLabel("")
                status_label.setWordWrap(True)
                status_label.setVisible(False)
                self._secret_status_labels[key] = status_label
                self._set_secret_inline_status(key, state="idle", text="")
                box.addWidget(status_label)
                widget.textChanged.connect(
                    lambda _text, field_key=key: self._on_secret_field_edited(field_key)
                )

            row = (idx // columns) + row_offset
            col = idx % columns
            self._grid.addWidget(field, row, col)
            idx += 1

        next_row = (idx + columns - 1) // columns + row_offset
        next_row = self._render_prompt_manager_editor_if_supported(next_row, columns)
        next_row = self._render_prompt_preview_if_supported(next_row, columns)
        self._grid.addWidget(QWidget(), next_row, 0)
        self._rendering_form = False

    def _render_meeting_rename_form(self) -> None:
        columns = 2
        header = QLabel(self._tr("meeting_rename.title", "Meeting Rename"))
        header.setObjectName("panelTitle")
        self._grid.addWidget(header, 0, 0, 1, columns)

        note = QLabel(
            self._tr(
                "meeting_rename.note",
                "Configure how Rename updates meeting files. Full mode can also rename source files "
                "inside app-managed import folders.",
            )
        )
        note.setObjectName("pipelineMetaLabel")
        note.setWordWrap(True)
        self._grid.addWidget(note, 1, 0, 1, columns)

        current = self._store.get_settings(_UI_MEETING_RENAME_SETTINGS_ID, include_secrets=False)
        mode_value = (
            str(current.get("rename_mode", "")).strip().lower()
            if isinstance(current, dict)
            else ""
        )
        if mode_value not in {"metadata_only", "artifacts_and_manifest", "full_with_source"}:
            mode_value = "artifacts_and_manifest"
        allow_source = bool(current.get("allow_source_rename", False)) if isinstance(current, dict) else False

        fields = [
            (
                "rename_mode",
                self._tr("meeting_rename.field.mode", "Rename Mode"),
                self._build_widget(
                    [
                        {"label": self._tr("meeting_rename.mode.metadata", "Metadata only"), "value": "metadata_only"},
                        {
                            "label": self._tr(
                                "meeting_rename.mode.artifacts",
                                "Artifacts + manifest (recommended)",
                            ),
                            "value": "artifacts_and_manifest",
                        },
                        {
                            "label": self._tr(
                                "meeting_rename.mode.full",
                                "Full + source file (advanced)",
                            ),
                            "value": "full_with_source",
                        },
                    ],
                    mode_value,
                    secret=False,
                    editable=False,
                ),
            ),
            (
                "allow_source_rename",
                self._tr("meeting_rename.field.allow_source", "Allow Source Rename"),
                self._build_widget([], allow_source, secret=False, editable=False),
            ),
        ]

        self._field_widgets = {}
        for idx, (key, label_text, widget) in enumerate(fields):
            self._field_widgets[key] = widget
            self._wire_auto_save(widget)
            field = QWidget()
            box = QVBoxLayout(field)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            label = QLabel(label_text)
            label.setObjectName("statusMeta")
            box.addWidget(label)
            box.addWidget(widget)
            row = 2 + idx
            self._grid.addWidget(field, row, 0, 1, columns)

        hint = QLabel(
            self._tr(
                "meeting_rename.hint",
                "When enabled, each rename asks confirmation before source file rename.",
            )
        )
        hint.setObjectName("pipelineMetaLabel")
        hint.setWordWrap(True)
        self._grid.addWidget(hint, 4, 0, 1, columns)

    def _render_ui_preferences_form(self) -> None:
        columns = 2
        header = QLabel(self._tr("ui.title", "Interface Preferences"))
        header.setObjectName("panelTitle")
        self._grid.addWidget(header, 0, 0, 1, columns)

        note = QLabel(
            self._tr(
                "ui.note",
                "Theme is applied immediately. Language is applied after restart.",
            )
        )
        note.setObjectName("pipelineMetaLabel")
        note.setWordWrap(True)
        self._grid.addWidget(note, 1, 0, 1, columns)

        locale_value = str(self._ui_store.get("ui.locale") or "").strip().lower() or "en"
        if locale_value not in {"en", "ru"}:
            locale_value = "en"
        theme_value = normalize_theme_id(str(self._ui_store.get("ui.theme") or "").strip().lower() or DEFAULT_THEME_ID)

        fields = [
            (
                "ui.locale",
                self._tr("ui.locale", "Language"),
                self._build_widget(
                    [
                        {"label": self._tr("ui.locale.english", "English"), "value": "en"},
                        {"label": self._tr("ui.locale.russian", "Russian"), "value": "ru"},
                    ],
                    locale_value,
                    secret=False,
                    editable=False,
                ),
            ),
            (
                "ui.theme",
                self._tr("ui.theme", "Theme"),
                self._build_widget(
                    [
                        {"label": self._tr("ui.theme.light", "Light"), "value": "light"},
                        {"label": self._tr("ui.theme.dark", "Dark"), "value": "dark"},
                        {"label": self._tr("ui.theme.light_mono", "Light Monochrome"), "value": "light_mono"},
                        {"label": self._tr("ui.theme.dark_mono", "Dark Monochrome"), "value": "dark_mono"},
                    ],
                    theme_value,
                    secret=False,
                    editable=False,
                ),
            ),
        ]

        self._field_widgets = {}
        for idx, (key, label_text, widget) in enumerate(fields):
            self._field_widgets[key] = widget
            self._wire_auto_save(widget)
            field = QWidget()
            box = QVBoxLayout(field)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            label = QLabel(label_text)
            label.setObjectName("statusMeta")
            box.addWidget(label)
            box.addWidget(widget)
            row = 2 + idx
            self._grid.addWidget(field, row, 0, 1, columns)

    def _render_path_preferences_form(self) -> None:
        columns = 3
        header = QLabel(self._tr("paths.title", "Default Folders"))
        header.setObjectName("panelTitle")
        self._grid.addWidget(header, 0, 0, 1, columns)

        note = QLabel(
            self._tr(
                "paths.note",
                "Input folder can be monitored for auto-processing. Output folder is applied after restart.",
            )
        )
        note.setObjectName("pipelineMetaLabel")
        note.setWordWrap(True)
        self._grid.addWidget(note, 1, 0, 1, columns)

        current = self._store.get_settings(_UI_PATH_PREFERENCES_SETTINGS_ID, include_secrets=False)
        input_dir = str(current.get("default_input_dir", "") or "").strip() if isinstance(current, dict) else ""
        output_dir = str(current.get("default_output_dir", "") or "").strip() if isinstance(current, dict) else ""
        monitor_enabled = bool(current.get("monitor_input_dir", False)) if isinstance(current, dict) else False

        self._field_widgets = {}
        self._path_field_widgets = {}

        row = 2
        row = self._add_path_field(
            row=row,
            key="default_input_dir",
            label=self._tr("paths.input_dir", "Default input folder"),
            value=input_dir,
            button_text=self._tr("paths.browse", "Browse"),
            columns=columns,
        )

        monitor_label = QLabel(self._tr("paths.monitor", "Monitor input folder"))
        monitor_label.setObjectName("statusMeta")
        self._grid.addWidget(monitor_label, row, 0)
        monitor_box = QCheckBox()
        monitor_box.setChecked(bool(monitor_enabled))
        monitor_box.stateChanged.connect(lambda *_args: self._schedule_auto_save())
        self._field_widgets["monitor_input_dir"] = monitor_box
        self._grid.addWidget(monitor_box, row, 1, 1, 2)
        row += 1

        row = self._add_path_field(
            row=row,
            key="default_output_dir",
            label=self._tr("paths.output_dir", "Default output folder"),
            value=output_dir,
            button_text=self._tr("paths.browse", "Browse"),
            columns=columns,
        )

        hint = QLabel(
            self._tr(
                "paths.monitor_hint",
                "When monitoring is enabled, new media files from the input folder are automatically queued for transcription and downstream processing.",
            )
        )
        hint.setObjectName("pipelineMetaLabel")
        hint.setWordWrap(True)
        self._grid.addWidget(hint, row, 0, 1, columns)

    def _add_path_field(
        self,
        *,
        row: int,
        key: str,
        label: str,
        value: str,
        button_text: str,
        columns: int,
    ) -> int:
        field_label = QLabel(str(label or key))
        field_label.setObjectName("statusMeta")
        self._grid.addWidget(field_label, row, 0)

        edit = QLineEdit(str(value or ""))
        edit.setPlaceholderText(self._tr("paths.empty_placeholder", "Not configured"))
        edit.editingFinished.connect(self._schedule_auto_save)
        self._field_widgets[key] = edit
        self._path_field_widgets[key] = edit
        self._grid.addWidget(edit, row, 1)

        browse_btn = QPushButton(str(button_text or "Browse"))
        browse_btn.clicked.connect(lambda _checked=False, field_key=key: self._pick_directory(field_key))
        self._grid.addWidget(browse_btn, row, 2, 1, max(1, columns - 2))
        return row + 1

    def _pick_directory(self, key: str) -> None:
        widget = self._path_field_widgets.get(str(key or "").strip())
        if not isinstance(widget, QLineEdit):
            return
        current = str(widget.text() or "").strip()
        start_dir = current or str(self._app_root)
        picked = QFileDialog.getExistingDirectory(
            self,
            self._tr("paths.pick_dir_title", "Select folder"),
            start_dir,
        )
        if not picked:
            return
        widget.setText(str(Path(picked).expanduser().resolve()))
        self._schedule_auto_save()

    @staticmethod
    def _is_advanced_by_heuristic(key: str) -> bool:
        k = str(key or "").strip().lower()
        if not k:
            return False
        # Keep basic UX focused: secrets, auth, and model choice stay visible.
        if _is_secret(k) or k in {"auth_mode", "model", "model_id"}:
            return False
        if k.endswith("_api_key") or k.endswith("_key") or k.endswith("_token") or k.endswith("_secret"):
            return False
        # Common expert knobs.
        if "prompt" in k:
            return True
        if k in {
            "endpoint",
            "timeout_seconds",
            "max_tokens",
            "temperature",
            "best_of",
            "beam_size",
            "entropy_thold",
            "logprob_thold",
            "no_speech_thold",
            "temperature_inc",
            "max_context",
            "no_context",
            "suppress_nst",
            "strip_nonspeech_tags",
            "nonspeech_tag_regex",
            "stuck_detector_enabled",
            "stuck_min_run",
            "stuck_action",
            "split_on_word",
            "carry_initial_prompt",
            "two_pass",
            "allow_download",
            "model_url",
            "models_dir",
            "whisper_path",
            "binary_path",
            "cache_dir",
            "model_path",
        }:
            return True
        if k.startswith("max_") or k.endswith("_thold") or k.endswith("_threshold"):
            return True
        return False

    def _build_widget(self, options: list[object], value: object, *, secret: bool, editable: bool) -> QWidget:
        if options:
            combo = QComboBox()
            combo.setEditable(bool(editable))
            for opt in options:
                label = str(getattr(opt, "label", "") or getattr(opt, "get", lambda k, d=None: "")("label") or "")
                val = str(getattr(opt, "value", "") or getattr(opt, "get", lambda k, d=None: "")("value") or "")
                combo.addItem(label or val, val)
            index = combo.findData(str(value))
            if index >= 0:
                combo.setCurrentIndex(index)
            else:
                combo.setCurrentText("" if value is None else str(value))
            return combo
        if isinstance(value, bool) or str(value).lower() in {"true", "false"}:
            box = QCheckBox()
            box.setChecked(_coerce_bool(value))
            return box
        edit = QLineEdit("" if value is None else str(value))
        if secret:
            edit.setEchoMode(QLineEdit.Password)
            edit.setPlaceholderText(self._tr("secret.placeholder", "(leave blank to keep existing)"))
        return edit

    def _collect(self) -> tuple[dict[str, object], list[str]]:
        values: dict[str, object] = {}
        secret_fields: list[str] = []
        for key, widget in self._field_widgets.items():
            if isinstance(widget, QComboBox):
                val = widget.currentData()
                values[key] = val if val is not None else widget.currentText()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                values[key] = widget.text()
            if _is_secret(key):
                secret_fields.append(key)
        return values, secret_fields

    def _should_hide_setting(self, plugin_id: str, key: str) -> bool:
        pid = str(plugin_id or "").strip()
        field_key = str(key or "").strip()
        if field_key in {"embeddings_allow_download", "embeddings_enabled"}:
            return True
        if field_key in {"model", "model_id"} and self._plugin_has_models(plugin_id):
            return True
        if pid == "llm.llama_cli" and field_key in {
            "binary_path",
            "model_path",
            "model_quant",
            "allow_download",
            "cache_dir",
            "system_prompt",
            "temperature",
            "ctx_size",
            "gpu_layers",
            "extra_args",
            "timeout_seconds",
            "hf_token",
        }:
            return True
        return False

    def _wire_auto_save(self, widget: QWidget) -> None:
        if widget.property("aimn_auto_save_wired"):
            return
        try:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(lambda *_a: self._schedule_auto_save())
                widget.editTextChanged.connect(lambda *_a: self._schedule_auto_save())
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(lambda *_a: self._schedule_auto_save())
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(lambda *_a: self._schedule_auto_save())
            elif isinstance(widget, QPlainTextEdit):
                widget.textChanged.connect(lambda *_a: self._schedule_auto_save())
        except Exception:
            pass
        widget.setProperty("aimn_auto_save_wired", True)

    def _schedule_auto_save(self) -> None:
        if self._rendering_form:
            return
        if not self._active_section_id or self._active_section_id.startswith("__"):
            return
        self._pending_auto_save_section_id = self._active_section_id
        if self._auto_save_timer.isActive():
            self._auto_save_timer.stop()
        self._auto_save_timer.start()
    def _save(self) -> None:
        if not self._active_section_id or self._active_section_id.startswith("__"):
            return
        if (
            self._pending_auto_save_section_id
            and self._pending_auto_save_section_id != self._active_section_id
        ):
            return

        if self._active_section_id == _UI_APP_PREFERENCES_SETTINGS_ID:
            values, _secret_fields = self._collect()
            locale = str(values.get("ui.locale", "en") or "").strip().lower() or "en"
            if locale not in {"en", "ru"}:
                locale = "en"
            theme = normalize_theme_id(str(values.get("ui.theme", "") or "").strip().lower())
            if theme not in set(THEME_IDS):
                theme = DEFAULT_THEME_ID

            prev_locale = str(self._ui_store.get("ui.locale") or "").strip().lower() or "en"
            prev_theme = normalize_theme_id(str(self._ui_store.get("ui.theme") or "").strip().lower())

            self._ui_store.set("ui.locale", locale)
            self._ui_store.set("ui.theme", theme)
            self._pending_auto_save_section_id = ""

            changed: dict[str, str] = {}
            if prev_locale != locale:
                changed["locale"] = locale
            if prev_theme != theme:
                changed["theme"] = theme
            if changed:
                self.uiPreferencesChanged.emit(changed)
            if prev_locale != locale:
                QMessageBox.information(
                    self,
                    self._tr("ui.locale.restart_title", "Restart required"),
                    self._tr(
                        "ui.locale.restart_message",
                        "Language will be fully applied after restarting the app.",
                    ),
                )
            return

        if self._active_section_id == _UI_PATH_PREFERENCES_SETTINGS_ID:
            values, _secret_fields = self._collect()
            normalized = {
                "default_input_dir": self._normalize_directory_value(values.get("default_input_dir")),
                "default_output_dir": self._normalize_directory_value(values.get("default_output_dir")),
                "monitor_input_dir": _coerce_bool(values.get("monitor_input_dir")),
            }
            self._store.set_settings(
                self._active_section_id,
                normalized,
                secret_fields=[],
                preserve_secrets=[],
            )
            self._pending_auto_save_section_id = ""
            self.pathPreferencesChanged.emit(dict(normalized))
            return

        values, secret_fields = self._collect()
        values.update(self._collect_prompt_manager_values())
        current_plain = self._store.get_settings(self._active_section_id, include_secrets=False)
        merged = dict(current_plain) if isinstance(current_plain, dict) else {}
        merged.update(values)
        self._store.set_settings(
            self._active_section_id,
            merged,
            secret_fields=secret_fields,
            preserve_secrets=secret_fields,
        )
        self._pending_auto_save_section_id = ""
        if self._models_panel:
            self._models_panel.set_plugin(self._active_section_id)

    def _normalize_directory_value(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = self._app_root / candidate
        try:
            return str(candidate.resolve())
        except Exception:
            return str(candidate)

    def _has_embeddings_fields(self) -> bool:
        return any(str(key).startswith("embeddings_") for key in self._field_widgets.keys())

    @staticmethod
    def _merge_live_validation_settings(
        current_plain: dict[str, object],
        values: dict[str, object],
        *,
        secret_fields: list[str],
        dirty_secret_fields: set[str],
    ) -> dict[str, object]:
        merged = dict(current_plain) if isinstance(current_plain, dict) else {}
        secret_keys = {str(key or "").strip() for key in secret_fields if str(key or "").strip()}
        dirty_keys = {str(key or "").strip() for key in dirty_secret_fields if str(key or "").strip()}
        for key, value in values.items():
            clean_key = str(key or "").strip()
            if not clean_key:
                continue
            if clean_key in secret_keys:
                text = str(value or "")
                if clean_key in dirty_keys and text.strip():
                    merged[clean_key] = text
                else:
                    merged.pop(clean_key, None)
                continue
            merged[clean_key] = value
        return merged

    def _live_validation_settings_override(self) -> dict[str, object]:
        if not self._active_section_id or self._active_section_id.startswith("__"):
            return {}
        values, secret_fields = self._collect()
        current_plain = self._store.get_settings(self._active_section_id, include_secrets=False)
        merged = self._merge_live_validation_settings(
            current_plain if isinstance(current_plain, dict) else {},
            values,
            secret_fields=secret_fields,
            dirty_secret_fields=self._dirty_secret_fields,
        )
        merged.update(self._collect_prompt_manager_values())
        return merged

    def _on_secret_field_edited(self, key: str) -> None:
        if self._rendering_form:
            return
        clean_key = str(key or "").strip()
        widget = self._field_widgets.get(clean_key)
        if not clean_key or not isinstance(widget, QLineEdit):
            return
        text = str(widget.text() or "")
        if text.strip():
            self._dirty_secret_fields.add(clean_key)
            self._secret_validation_request_id += 1
            self._set_secret_inline_status(
                clean_key,
                state="checking",
                text=self._tr("secret.status.checking", "Checking credentials..."),
            )
            if self._secret_validation_timer.isActive():
                self._secret_validation_timer.stop()
            self._secret_validation_timer.start()
            return
        self._dirty_secret_fields.discard(clean_key)
        self._secret_validation_request_id += 1
        if self._secret_validation_timer.isActive():
            self._secret_validation_timer.stop()
        self._set_secret_inline_status(
            clean_key,
            state="idle",
            text=self._tr("secret.status.saved", "Saved secret is kept until you enter a new value."),
        )
        if self._dirty_secret_fields:
            for field_key in self._dirty_secret_fields:
                self._set_secret_inline_status(
                    field_key,
                    state="checking",
                    text=self._tr("secret.status.checking", "Checking credentials..."),
                )
            self._secret_validation_timer.start()

    def _set_secret_inline_status(self, key: str, *, state: str, text: str) -> None:
        label = self._secret_status_labels.get(str(key or "").strip())
        if not isinstance(label, QLabel):
            return
        palette = {
            "idle": "#64748B",
            "checking": "#2563EB",
            "ok": "#166534",
            "error": "#B91C1C",
        }
        normalized = str(state or "idle").strip().lower() or "idle"
        label.setProperty("aimn_validation_state", normalized)
        label.setStyleSheet(f"color: {palette.get(normalized, palette['idle'])};")
        label.setText(str(text or ""))
        label.setVisible(bool(str(text or "").strip()))
        label.style().unpolish(label)
        label.style().polish(label)

    def _run_secret_validation(self) -> None:
        if self._secret_validation_timer.isActive():
            self._secret_validation_timer.stop()
        plugin_id = str(self._active_section_id or "").strip()
        if not plugin_id or plugin_id.startswith("__"):
            return
        dirty_keys = tuple(
            key
            for key in sorted(self._dirty_secret_fields)
            if isinstance(self._field_widgets.get(key), QLineEdit)
            and str(getattr(self._field_widgets.get(key), "text", lambda: "")() or "").strip()
        )
        if not dirty_keys:
            return
        request_id = int(self._secret_validation_request_id)
        stage_id = ""
        plugin = self._catalog.plugin_by_id(plugin_id) if self._catalog else None
        if plugin:
            stage_id = str(getattr(plugin, "stage_id", "") or "").strip()
        settings_override = self._live_validation_settings_override()
        _LOGGER.info(
            "secret_validation_started plugin_id=%s stage_id=%s fields=%s",
            plugin_id,
            stage_id,
            ",".join(dirty_keys),
        )

        def _worker() -> object:
            return self._health_service.check_plugin(
                plugin_id,
                stage_id=stage_id,
                settings_override=settings_override or None,
                full_check=False,
                force=True,
                max_age_seconds=30.0,
                allow_disabled=True,
            )

        def _on_finished(done_request_id: int, payload: object) -> None:
            if int(done_request_id) != int(self._secret_validation_request_id):
                return
            if str(self._active_section_id or "").strip() != plugin_id:
                return
            report = payload
            if getattr(report, "healthy", False):
                _LOGGER.info(
                    "secret_validation_ok plugin_id=%s stage_id=%s fields=%s",
                    plugin_id,
                    stage_id,
                    ",".join(dirty_keys),
                )
                for field_key in dirty_keys:
                    self._set_secret_inline_status(
                        field_key,
                        state="ok",
                        text=self._tr("secret.status.valid", "Credentials look valid."),
                    )
                return
            issues = tuple(getattr(report, "issues", ()) or ())
            message = self._tr("health.not_ready_message", "Plugin is not ready.")
            if issues:
                first = issues[0]
                message = str(getattr(first, "summary", "") or getattr(first, "hint", "") or message)
            issue_codes = ",".join(str(getattr(item, "code", "") or "").strip() for item in issues if item)
            log = _LOGGER.info if _is_expected_provider_health_issue(issue_codes) else _LOGGER.warning
            log(
                "secret_validation_failed plugin_id=%s stage_id=%s fields=%s issues=%s message=%s",
                plugin_id,
                stage_id,
                ",".join(dirty_keys),
                issue_codes,
                message,
            )
            for field_key in dirty_keys:
                self._set_secret_inline_status(field_key, state="error", text=message)

        def _on_error(done_request_id: int, error: Exception) -> None:
            if int(done_request_id) != int(self._secret_validation_request_id):
                return
            if str(self._active_section_id or "").strip() != plugin_id:
                return
            message = self._fmt(
                "secret.status.failed",
                "Validation failed: {error}",
                error=str(error),
            )
            _LOGGER.exception(
                "secret_validation_exception plugin_id=%s stage_id=%s fields=%s error=%s",
                plugin_id,
                stage_id,
                ",".join(dirty_keys),
                error,
            )
            for field_key in dirty_keys:
                self._set_secret_inline_status(field_key, state="error", text=message)

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )

    def _on_credentials_hub_settings_changed(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        self._health_service.invalidate_plugin_cache(pid)

    def _plugin_has_models(self, plugin_id: str) -> bool:
        settings = self._store.get_settings(plugin_id, include_secrets=False)
        if any(str(key).startswith("embeddings_") for key in settings.keys()):
            return True
        models = settings.get("models") if isinstance(settings, dict) else None
        if isinstance(models, list) and any(isinstance(entry, dict) and str(entry.get("model_id", "")).strip() for entry in models):
            return True
        plugin = self._catalog.plugin_by_id(str(plugin_id or "").strip())
        caps = plugin.capabilities if plugin and isinstance(plugin.capabilities, dict) else {}
        models_caps = caps.get("models") if isinstance(caps, dict) else None
        if isinstance(models_caps, dict):
            return True
        return bool(self._models_service.load_models_config(plugin_id))

    def _plugin_has_capability(self, plugin_id: str, capability: str) -> bool:
        plugin = self._catalog.plugin_by_id(str(plugin_id or "").strip())
        caps = plugin.capabilities if plugin and isinstance(plugin.capabilities, dict) else {}
        return bool(caps.get(str(capability or "").strip(), False))

    def _collect_prompt_manager_values(self) -> dict[str, object]:
        if not self._plugin_has_capability(self._active_section_id, "prompt_manager"):
            return {}
        if not self._prompt_profiles:
            return {}
        self._sync_active_prompt_profile_from_editor()
        self._refresh_prompt_active_profile_options()
        active_profile = (
            str(self._prompt_active_profile_value or "").strip().lower()
        )
        available_ids = {str(item.get("id", "")).strip().lower() for item in self._prompt_profiles}
        if active_profile and active_profile != "custom" and active_profile not in available_ids:
            active_profile = ""
        if not active_profile:
            active_profile = "standard" if "standard" in available_ids else next(iter(available_ids), "standard")
        custom_default = (
            self._prompt_custom_default.toPlainText().strip()
            if isinstance(self._prompt_custom_default, QPlainTextEdit)
            else ""
        )
        profiles = [
            dict(item)
            for item in self._prompt_profiles
            if str(item.get("id", "")).strip() and str(item.get("prompt", "")).strip()
        ]
        if not profiles:
            profiles = [
                {
                    "id": "standard",
                    "label": "Standard",
                    "prompt": "Create a balanced meeting summary.",
                }
            ]
        return {
            "profiles": profiles,
            "active_profile": active_profile,
            "custom_prompt_default": custom_default,
        }

    def _render_prompt_manager_editor_if_supported(self, start_row: int, columns: int) -> int:
        if not self._plugin_has_capability(self._active_section_id, "prompt_manager"):
            return start_row
        try:
            from aimn.plugins.prompt_manager import (
                default_prompt_manager_settings,
                normalize_presets,
            )
        except Exception:
            return start_row

        self._updating_prompt_manager_widgets = True
        try:
            defaults = default_prompt_manager_settings()
            settings = self._store.get_settings(self._active_section_id, include_secrets=False)
            raw_profiles = settings.get("profiles") if isinstance(settings, dict) else None
            if not isinstance(raw_profiles, list):
                raw_profiles = settings.get("presets") if isinstance(settings, dict) else None
            profiles = normalize_presets(raw_profiles if isinstance(raw_profiles, list) else [])
            if not profiles:
                profiles = normalize_presets(defaults.get("profiles", []))
            self._prompt_profiles = [
                {
                    "id": str(item.preset_id).strip().lower(),
                    "label": str(item.label).strip() or str(item.preset_id).strip().lower(),
                    "prompt": str(item.prompt).strip(),
                }
                for item in profiles
                if str(item.prompt).strip()
            ]
            if not self._prompt_profiles:
                self._prompt_profiles = [
                    {
                        "id": "standard",
                        "label": "Standard",
                        "prompt": "Create a balanced meeting summary.",
                    }
                ]
            active_profile = str(
                settings.get("active_profile", defaults.get("active_profile", "standard"))
                if isinstance(settings, dict)
                else defaults.get("active_profile", "standard")
            ).strip().lower() or "standard"
            custom_default = str(
                settings.get("custom_prompt_default", defaults.get("custom_prompt_default", ""))
                if isinstance(settings, dict)
                else defaults.get("custom_prompt_default", "")
            ).strip()
        finally:
            self._updating_prompt_manager_widgets = False

        title = QLabel("Prompt profiles")
        title.setObjectName("panelTitle")
        self._grid.addWidget(title, start_row, 0, 1, columns)

        note = QLabel(
            "Manage standard and custom prompt profiles. "
            "Service sections remain hidden from editing."
        )
        note.setObjectName("pipelineMetaLabel")
        note.setWordWrap(True)
        self._grid.addWidget(note, start_row + 1, 0, 1, columns)

        default_label = QLabel("Default profile")
        default_label.setObjectName("statusMeta")
        self._grid.addWidget(default_label, start_row + 2, 0, 1, 1)
        self._prompt_active_profile = QWidget()
        prompt_active_layout = QHBoxLayout(self._prompt_active_profile)
        prompt_active_layout.setContentsMargins(0, 0, 0, 0)
        prompt_active_layout.setSpacing(8)
        self._grid.addWidget(self._prompt_active_profile, start_row + 2, 1, 1, 1)

        custom_label = QLabel("Custom default request body")
        custom_label.setObjectName("statusMeta")
        self._grid.addWidget(custom_label, start_row + 2, 2, 1, 2)
        self._prompt_custom_default = QPlainTextEdit()
        self._prompt_custom_default.setMinimumHeight(90)
        self._prompt_custom_default.setPlainText(custom_default)
        self._grid.addWidget(self._prompt_custom_default, start_row + 3, 2, 1, 2)

        list_label = QLabel("Profiles")
        list_label.setObjectName("statusMeta")
        self._grid.addWidget(list_label, start_row + 3, 0, 1, 2)

        self._prompt_profiles_list = QListWidget()
        self._prompt_profiles_list.setMinimumHeight(220)
        self._grid.addWidget(self._prompt_profiles_list, start_row + 4, 0, 1, 2)

        add_btn = QPushButton("Add")
        dup_btn = QPushButton("Duplicate")
        del_btn = QPushButton("Delete")
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(add_btn)
        actions.addWidget(dup_btn)
        actions.addWidget(del_btn)
        actions.addStretch(1)
        actions_box = QWidget()
        actions_box.setLayout(actions)
        self._grid.addWidget(actions_box, start_row + 5, 0, 1, 2)

        id_label = QLabel("Profile ID")
        id_label.setObjectName("statusMeta")
        self._grid.addWidget(id_label, start_row + 4, 2, 1, 1)
        self._prompt_profile_id = QLineEdit()
        self._grid.addWidget(self._prompt_profile_id, start_row + 4, 3, 1, 1)

        profile_label = QLabel("Profile label")
        profile_label.setObjectName("statusMeta")
        self._grid.addWidget(profile_label, start_row + 5, 2, 1, 1)
        self._prompt_profile_label = QLineEdit()
        self._grid.addWidget(self._prompt_profile_label, start_row + 5, 3, 1, 1)

        prompt_header = QWidget()
        prompt_header_box = QHBoxLayout(prompt_header)
        prompt_header_box.setContentsMargins(0, 0, 0, 0)
        prompt_header_box.setSpacing(8)
        prompt_label = QLabel("Request body")
        prompt_label.setObjectName("statusMeta")
        prompt_header_box.addWidget(prompt_label, 0)
        prompt_header_box.addStretch(1)
        self._prompt_profile_refine_btn = QPushButton("Refine with AI")
        prompt_header_box.addWidget(self._prompt_profile_refine_btn, 0)
        self._grid.addWidget(prompt_header, start_row + 6, 0, 1, columns)
        self._prompt_profile_prompt = QPlainTextEdit()
        self._prompt_profile_prompt.setMinimumHeight(180)
        self._grid.addWidget(self._prompt_profile_prompt, start_row + 7, 0, 1, columns)

        self._prompt_profiles_list.currentRowChanged.connect(self._on_prompt_profile_selected)
        self._prompt_profile_id.editingFinished.connect(self._on_prompt_profile_editor_changed)
        self._prompt_profile_label.textChanged.connect(self._on_prompt_profile_editor_changed)
        self._prompt_profile_prompt.textChanged.connect(self._on_prompt_profile_editor_changed)
        self._prompt_custom_default.textChanged.connect(lambda *_args: self._schedule_auto_save())
        self._prompt_profile_refine_btn.clicked.connect(self._on_prompt_refine_with_ai_clicked)
        refine_plugin_id, refine_provider, _refine_action = self._pick_prompt_refine_provider()
        self._prompt_profile_refine_btn.setEnabled(bool(refine_plugin_id))
        if refine_plugin_id and refine_provider:
            self._prompt_profile_refine_btn.setToolTip(f"Uses: {refine_provider}")
        else:
            self._prompt_profile_refine_btn.setToolTip("No configured provider supports refine_prompt action.")
        add_btn.clicked.connect(self._add_prompt_profile)
        dup_btn.clicked.connect(self._duplicate_prompt_profile)
        del_btn.clicked.connect(self._delete_prompt_profile)

        self._refresh_prompt_profiles_list()
        self._refresh_prompt_active_profile_options(active_profile)
        return start_row + 8

    def _refresh_prompt_profiles_list(self) -> None:
        if not isinstance(self._prompt_profiles_list, QListWidget):
            return
        selected = max(0, self._active_prompt_profile_index)
        self._updating_prompt_manager_widgets = True
        try:
            self._prompt_profiles_list.clear()
            for item in self._prompt_profiles:
                pid = str(item.get("id", "")).strip()
                label = str(item.get("label", "")).strip() or pid
                row = QListWidgetItem(f"{label} ({pid})")
                row.setData(Qt.UserRole, pid)
                self._prompt_profiles_list.addItem(row)
            if self._prompt_profiles:
                selected = min(selected, len(self._prompt_profiles) - 1)
                self._prompt_profiles_list.setCurrentRow(selected)
        finally:
            self._updating_prompt_manager_widgets = False
        if self._prompt_profiles:
            self._on_prompt_profile_selected(selected)

    def _refresh_prompt_active_profile_options(self, preferred: str = "") -> None:
        if not isinstance(self._prompt_active_profile, QWidget):
            return
        current = str(preferred or self._prompt_active_profile_value or "").strip().lower()
        available_ids = [str(item.get("id", "")).strip().lower() for item in self._prompt_profiles if str(item.get("id", "")).strip()]
        self._updating_prompt_manager_widgets = True
        try:
            layout = self._prompt_active_profile.layout()
            if layout is None:
                return
            for index in reversed(range(layout.count())):
                item = layout.takeAt(index)
                if item and item.widget():
                    widget = item.widget()
                    widget.setParent(None)
                    widget.deleteLater()
            self._prompt_active_profile_buttons = {}
            for item in self._prompt_profiles:
                pid = str(item.get("id", "")).strip().lower()
                if not pid:
                    continue
                label = str(item.get("label", "")).strip() or pid
                btn = StandardSelectableChip(label)
                btn.setMinimumHeight(32)
                btn.clicked.connect(lambda _checked=False, value=pid: self._set_prompt_active_profile(value))
                layout.addWidget(btn, 0)
                self._prompt_active_profile_buttons[pid] = btn
            custom_btn = StandardSelectableChip("Custom")
            custom_btn.setMinimumHeight(32)
            custom_btn.clicked.connect(lambda _checked=False: self._set_prompt_active_profile("custom"))
            layout.addWidget(custom_btn, 0)
            self._prompt_active_profile_buttons["custom"] = custom_btn
            layout.addStretch(1)
            target = current
            if target not in self._prompt_active_profile_buttons and "standard" in available_ids:
                target = "standard"
            if target not in self._prompt_active_profile_buttons and self._prompt_active_profile_buttons:
                target = next(iter(self._prompt_active_profile_buttons.keys()))
            self._set_prompt_active_profile(target or "custom", schedule_save=False)
        finally:
            self._updating_prompt_manager_widgets = False

    def _set_prompt_active_profile(self, profile_id: str, *, schedule_save: bool = True) -> None:
        selected = str(profile_id or "").strip().lower() or "custom"
        if selected not in self._prompt_active_profile_buttons:
            selected = "custom"
        self._prompt_active_profile_value = selected
        for pid, btn in self._prompt_active_profile_buttons.items():
            is_selected = pid == selected
            btn.apply_state(selected=is_selected, active=is_selected, tone="focus", checked=is_selected)
        if schedule_save and not self._updating_prompt_manager_widgets:
            self._schedule_auto_save()

    def _on_prompt_profile_selected(self, row: int) -> None:
        if self._updating_prompt_manager_widgets:
            return
        self._sync_active_prompt_profile_from_editor()
        self._active_prompt_profile_index = int(row)
        self._updating_prompt_manager_widgets = True
        try:
            if row < 0 or row >= len(self._prompt_profiles):
                if isinstance(self._prompt_profile_id, QLineEdit):
                    self._prompt_profile_id.setText("")
                if isinstance(self._prompt_profile_label, QLineEdit):
                    self._prompt_profile_label.setText("")
                if isinstance(self._prompt_profile_prompt, QPlainTextEdit):
                    self._prompt_profile_prompt.setPlainText("")
                return
            item = self._prompt_profiles[row]
            if isinstance(self._prompt_profile_id, QLineEdit):
                self._prompt_profile_id.setText(str(item.get("id", "")).strip())
            if isinstance(self._prompt_profile_label, QLineEdit):
                self._prompt_profile_label.setText(str(item.get("label", "")).strip())
            if isinstance(self._prompt_profile_prompt, QPlainTextEdit):
                self._prompt_profile_prompt.setPlainText(str(item.get("prompt", "")).strip())
        finally:
            self._updating_prompt_manager_widgets = False

    def _sync_active_prompt_profile_from_editor(self) -> None:
        if self._updating_prompt_manager_widgets:
            return
        row = int(self._active_prompt_profile_index)
        if row < 0 or row >= len(self._prompt_profiles):
            return
        raw_id = self._prompt_profile_id.text() if isinstance(self._prompt_profile_id, QLineEdit) else ""
        normalized_id = self._normalize_prompt_profile_id(raw_id) or f"profile_{row + 1}"
        current_ids = {str(item.get("id", "")).strip().lower() for idx, item in enumerate(self._prompt_profiles) if idx != row}
        unique_id = normalized_id
        n = 2
        while unique_id in current_ids:
            unique_id = f"{normalized_id}_{n}"
            n += 1
        label = self._prompt_profile_label.text() if isinstance(self._prompt_profile_label, QLineEdit) else ""
        prompt = (
            self._prompt_profile_prompt.toPlainText()
            if isinstance(self._prompt_profile_prompt, QPlainTextEdit)
            else ""
        )
        self._prompt_profiles[row] = {
            "id": unique_id,
            "label": str(label or unique_id).strip(),
            "prompt": str(prompt or "").strip(),
        }
        self._updating_prompt_manager_widgets = True
        try:
            if isinstance(self._prompt_profile_id, QLineEdit):
                self._prompt_profile_id.setText(unique_id)
            if isinstance(self._prompt_profiles_list, QListWidget):
                item = self._prompt_profiles_list.item(row)
                if item:
                    item.setText(f"{self._prompt_profiles[row]['label']} ({unique_id})")
                    item.setData(Qt.UserRole, unique_id)
        finally:
            self._updating_prompt_manager_widgets = False

    def _on_prompt_profile_editor_changed(self) -> None:
        if self._updating_prompt_manager_widgets:
            return
        self._sync_active_prompt_profile_from_editor()
        self._refresh_prompt_active_profile_options()
        self._schedule_auto_save()

    def _add_prompt_profile(self) -> None:
        if self._updating_prompt_manager_widgets:
            return
        self._sync_active_prompt_profile_from_editor()
        new_id = self._make_unique_prompt_profile_id("custom_prompt")
        self._prompt_profiles.append(
            {
                "id": new_id,
                "label": "New profile",
                "prompt": "Describe expected output and constraints.",
            }
        )
        self._active_prompt_profile_index = len(self._prompt_profiles) - 1
        self._refresh_prompt_profiles_list()
        self._refresh_prompt_active_profile_options()
        self._schedule_auto_save()

    def _duplicate_prompt_profile(self) -> None:
        if self._updating_prompt_manager_widgets:
            return
        self._sync_active_prompt_profile_from_editor()
        row = int(self._active_prompt_profile_index)
        if row < 0 or row >= len(self._prompt_profiles):
            return
        source = dict(self._prompt_profiles[row])
        source_id = str(source.get("id", "")).strip().lower() or "profile"
        source_label = str(source.get("label", "")).strip() or source_id
        cloned = {
            "id": self._make_unique_prompt_profile_id(f"{source_id}_copy"),
            "label": f"{source_label} Copy",
            "prompt": str(source.get("prompt", "")).strip(),
        }
        self._prompt_profiles.insert(row + 1, cloned)
        self._active_prompt_profile_index = row + 1
        self._refresh_prompt_profiles_list()
        self._refresh_prompt_active_profile_options()
        self._schedule_auto_save()

    def _delete_prompt_profile(self) -> None:
        if self._updating_prompt_manager_widgets:
            return
        row = int(self._active_prompt_profile_index)
        if row < 0 or row >= len(self._prompt_profiles):
            return
        self._sync_active_prompt_profile_from_editor()
        self._prompt_profiles.pop(row)
        if not self._prompt_profiles:
            self._prompt_profiles = [
                {
                    "id": "standard",
                    "label": "Standard",
                    "prompt": "Create a balanced meeting summary.",
                }
            ]
            row = 0
        self._active_prompt_profile_index = max(0, min(row, len(self._prompt_profiles) - 1))
        self._refresh_prompt_profiles_list()
        self._refresh_prompt_active_profile_options()
        self._schedule_auto_save()

    def _make_unique_prompt_profile_id(self, base: str) -> str:
        normalized = self._normalize_prompt_profile_id(base) or "profile"
        existing = {str(item.get("id", "")).strip().lower() for item in self._prompt_profiles}
        if normalized not in existing:
            return normalized
        n = 2
        while True:
            candidate = f"{normalized}_{n}"
            if candidate not in existing:
                return candidate
            n += 1

    @staticmethod
    def _normalize_prompt_profile_id(raw: str) -> str:
        value = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
        clean = "".join(ch for ch in value if ch.isalnum() or ch == "_")
        while "__" in clean:
            clean = clean.replace("__", "_")
        return clean.strip("_")

    @staticmethod
    def _action_result_parts(result: object) -> tuple[str, str, object]:
        if isinstance(result, dict):
            status = str(result.get("status", "") or "").strip().lower()
            message = str(result.get("message", "") or "").strip()
            return status, message, result.get("data")
        status = str(getattr(result, "status", "") or "").strip().lower()
        message = str(getattr(result, "message", "") or "").strip()
        return status, message, getattr(result, "data", None)

    @staticmethod
    def _prompt_refine_action_id(capabilities: object) -> str:
        caps = capabilities if isinstance(capabilities, dict) else {}
        spec = caps.get("prompt_refine") if isinstance(caps, dict) else None
        if isinstance(spec, dict):
            action_id = str(spec.get("action", "") or "").strip()
            return action_id or "refine_prompt"
        if isinstance(spec, str):
            action_id = str(spec).strip()
            return action_id or "refine_prompt"
        if bool(spec):
            return "refine_prompt"
        return "refine_prompt"

    def _pick_prompt_refine_provider(self) -> tuple[str, str, str]:
        snapshot = self._catalog_service.load()
        catalog = snapshot.catalog
        providers: list[tuple[str, str, str, str]] = []
        for plugin in catalog.enabled_plugins():
            pid = str(getattr(plugin, "plugin_id", "") or "").strip()
            if not pid:
                continue
            action_id = self._prompt_refine_action_id(getattr(plugin, "capabilities", {}))
            try:
                actions = self._action_service.list_actions(pid)
            except Exception:
                continue
            available = {
                str(getattr(action, "action_id", "") or "").strip()
                for action in actions
                if str(getattr(action, "action_id", "") or "").strip()
            }
            if action_id not in available:
                continue
            providers.append((catalog.display_name(pid), pid, action_id, str(getattr(plugin, "stage_id", "") or "")))
        if not providers:
            return "", "", ""
        providers.sort(key=lambda item: (item[0].lower(), item[3].lower(), item[1].lower()))
        display_name, pid, action_id, _stage_id = providers[0]
        return pid, display_name, action_id

    def _on_prompt_refine_with_ai_clicked(self) -> None:
        if self._updating_prompt_manager_widgets:
            return
        self._sync_active_prompt_profile_from_editor()
        row = int(self._active_prompt_profile_index)
        if row < 0 or row >= len(self._prompt_profiles):
            QMessageBox.warning(self, "Prompt refine", "Select a profile with prompt text first.")
            return
        prompt_text = str(self._prompt_profiles[row].get("prompt", "")).strip()
        if not prompt_text:
            QMessageBox.warning(self, "Prompt refine", "Current profile prompt is empty.")
            return

        plugin_id, provider_label, action_id = self._pick_prompt_refine_provider()
        if not plugin_id:
            QMessageBox.warning(
                self,
                "Prompt refine",
                (
                    "No enabled plugin supports prompt refinement action.\n"
                    "Enable a provider plugin with `refine_prompt` action and try again."
                ),
            )
            return

        if isinstance(self._prompt_profile_refine_btn, QPushButton):
            self._prompt_profile_refine_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = self._action_service.invoke_action(
                plugin_id,
                action_id,
                {"prompt_text": prompt_text},
            )
        except Exception as exc:
            QMessageBox.warning(self, "Prompt refine", f"Refine failed: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            if isinstance(self._prompt_profile_refine_btn, QPushButton):
                self._prompt_profile_refine_btn.setEnabled(True)

        status, message, data = self._action_result_parts(result)
        if status not in {"ok", "success"}:
            text = message or "refine_prompt_failed"
            QMessageBox.warning(self, "Prompt refine", f"{provider_label}: {text}")
            return
        payload = data if isinstance(data, dict) else {}
        refined = str(payload.get("prompt", payload.get("refined_prompt", "")) or "").strip()
        if not refined:
            QMessageBox.warning(self, "Prompt refine", "Provider returned empty refined prompt.")
            return

        if isinstance(self._prompt_profile_prompt, QPlainTextEdit):
            self._prompt_profile_prompt.setPlainText(refined)
        model_id = str(payload.get("model_id", "") or "").strip()
        note = f"{provider_label} refined the prompt."
        if model_id:
            note = f"{note}\nModel: {model_id}"
        QMessageBox.information(self, "Prompt refine", note)

    def _render_prompt_preview_if_supported(self, start_row: int, columns: int) -> int:
        if not self._plugin_has_capability(self._active_section_id, "prompt_manager"):
            return start_row
        try:
            from aimn.plugins.prompt_manager import (
                build_prompt_preview,
                default_prompt_manager_settings,
                load_prompt_presets,
            )
        except Exception:
            return start_row

        defaults = default_prompt_manager_settings()
        settings = self._store.get_settings(self._active_section_id, include_secrets=False)
        active_profile = str(
            settings.get("active_profile", defaults.get("active_profile", "standard"))
            if isinstance(settings, dict)
            else defaults.get("active_profile", "standard")
        ).strip().lower() or "standard"
        custom_prompt_default = str(
            settings.get("custom_prompt_default", defaults.get("custom_prompt_default", ""))
            if isinstance(settings, dict)
            else defaults.get("custom_prompt_default", "")
        ).strip()

        title = QLabel("Prompt preview (read-only)")
        title.setObjectName("panelTitle")
        self._grid.addWidget(title, start_row, 0, 1, columns)

        note = QLabel(
            "Rendered from current profile + service sections. "
            "Service instructions are hidden from editing but visible here for verification."
        )
        note.setObjectName("pipelineMetaLabel")
        note.setWordWrap(True)
        self._grid.addWidget(note, start_row + 1, 0, 1, columns)

        profile_label = QLabel("Preview profile")
        profile_label.setObjectName("statusMeta")
        self._grid.addWidget(profile_label, start_row + 2, 0, 1, 1)

        profile_selector = QWidget()
        profile_selector_layout = QHBoxLayout(profile_selector)
        profile_selector_layout.setContentsMargins(0, 0, 0, 0)
        profile_selector_layout.setSpacing(8)
        presets = load_prompt_presets()
        preview_buttons: dict[str, StandardSelectableChip] = {}
        preview_profile = {"value": active_profile}
        for preset in presets:
            pid = str(getattr(preset, "preset_id", "") or "").strip().lower()
            if not pid or pid == "custom":
                continue
            label = str(getattr(preset, "label", "") or "").strip() or pid
            btn = StandardSelectableChip(label)
            btn.setMinimumHeight(32)
            btn.clicked.connect(lambda _checked=False, value=pid: _set_preview_profile(value))
            profile_selector_layout.addWidget(btn, 0)
            preview_buttons[pid] = btn
        custom_btn = StandardSelectableChip("Custom")
        custom_btn.setMinimumHeight(32)
        custom_btn.clicked.connect(lambda _checked=False: _set_preview_profile("custom"))
        profile_selector_layout.addWidget(custom_btn, 0)
        preview_buttons["custom"] = custom_btn
        profile_selector_layout.addStretch(1)
        self._grid.addWidget(profile_selector, start_row + 2, 1, 1, 1)

        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        preview.setMinimumHeight(300)
        self._grid.addWidget(preview, start_row + 3, 0, 1, columns)

        def _set_preview_profile(profile_id: str) -> None:
            selected = str(profile_id or "").strip().lower() or "standard"
            if selected not in preview_buttons:
                selected = "custom"
            preview_profile["value"] = selected
            for pid, btn in preview_buttons.items():
                is_selected = pid == selected
                btn.apply_state(selected=is_selected, active=is_selected, tone="focus", checked=is_selected)
            _refresh_preview()

        def _refresh_preview() -> None:
            profile_id = str(preview_profile["value"] or "").strip().lower() or "standard"
            preview.setPlainText(
                build_prompt_preview(
                    profile_id=profile_id,
                    custom_prompt=custom_prompt_default if profile_id == "custom" else "",
                )
            )

        if preview_profile["value"] not in preview_buttons:
            preview_profile["value"] = "standard" if "standard" in preview_buttons else "custom"
        _set_preview_profile(preview_profile["value"])
        _refresh_preview()
        return start_row + 4

    def _plugin_status(self, plugin: PluginDescriptor) -> tuple[str, str, str]:
        if not plugin.installed:
            return self._tr("plugin.status.missing", "Missing"), "#FEE2E2", "#B91C1C"
        if not plugin.entitled:
            if plugin.access_state == "platform_locked":
                return self._tr("plugin.status.platform_locked", "Platform locked"), "#EDE9FE", "#6D28D9"
            if plugin.access_state == "subscription_required":
                return self._tr(
                    "plugin.status.subscription_required",
                    "Subscription required",
                ), "#FEE2E2", "#B91C1C"
            if plugin.access_state == "purchase_required":
                return self._tr("plugin.status.purchase_required", "Purchase required"), "#FEE2E2", "#B91C1C"
            return self._tr("plugin.status.locked", "Locked"), "#FEE2E2", "#B91C1C"
        if plugin.access_state == "grace":
            return self._tr("plugin.status.grace", "Grace period"), "#FEF3C7", "#92400E"
        if plugin.enabled:
            return self._tr("plugin.status.enabled", "Enabled"), "#DCFCE7", "#166534"
        return self._tr("plugin.status.disabled", "Disabled"), "#FEF3C7", "#92400E"

    def _plugin_meta_lines(self, plugin: PluginDescriptor) -> list[str]:
        lines = [self._fmt("plugin.meta.id", "ID: {plugin_id}", plugin_id=plugin.plugin_id)]
        lines.append(self._fmt("plugin.meta.source", "Source: {source}", source=plugin.source_kind))
        provider = self._catalog.provider_label(plugin.plugin_id)
        if provider:
            lines.append(self._fmt("plugin.meta.provider", "Provider: {provider}", provider=provider))
        else:
            lines.append(self._fmt("plugin.meta.stage", "Stage: {stage_id}", stage_id=plugin.stage_id))
        if plugin.pricing_model:
            lines.append(
                self._fmt("plugin.meta.license", "License: {license}", license=plugin.pricing_model)
            )
        elif plugin.version:
            lines.append(self._fmt("plugin.meta.version", "Version: {version}", version=plugin.version))
        return lines[:4]
