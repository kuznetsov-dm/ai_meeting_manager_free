from __future__ import annotations

import html
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import PluginActionService, PluginCatalogService, SettingsService
from aimn.core.contracts import PluginDescriptor, PluginUiSchema
from aimn.core.plugin_health_service import PluginHealthService
from aimn.ui.i18n import UiI18n
from aimn.ui.services.async_worker import run_async

_LOGGER = logging.getLogger("aimn.ui.credentials_hub")
_VALIDATION_CACHE_KEY = "_credentials_validation"
_EXPECTED_PROVIDER_VALIDATION_TOKENS = (
    "api_key_missing",
    "auth_error",
    "provider_blocked",
    "blocked by google ai studio",
    "model_not_found",
    "not_available",
    "rate_limited",
    "request_failed",
    "bad_request",
    "empty_response",
    "status=400",
    "status=401",
    "status=402",
    "status=403",
    "status=404",
    "access denied",
    "no endpoints found",
    "not a valid model id",
)


def _is_secret_field_name(key: str) -> bool:
    lowered = str(key or "").strip().lower()
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


def _cap_get(payload: object, *keys: str, default: object = None) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(str(key))
    return current if current is not None else default


def _action_status_message_data(result: object) -> tuple[str, str, dict[str, object]]:
    if isinstance(result, dict):
        status = str(result.get("status", "") or "").strip().lower()
        message = str(result.get("message", "") or "").strip()
        data = result.get("data")
        return status, message, data if isinstance(data, dict) else {}
    status = str(getattr(result, "status", "") or "").strip().lower()
    message = str(getattr(result, "message", "") or "").strip()
    data = getattr(result, "data", None)
    return status, message, data if isinstance(data, dict) else {}


def _is_success_status(value: str) -> bool:
    return str(value or "").strip().lower() in {"ok", "success", "passed", "healthy"}


def _is_expected_provider_validation_failure(*parts: object) -> bool:
    haystack = " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())
    if not haystack:
        return False
    return any(token in haystack for token in _EXPECTED_PROVIDER_VALIDATION_TOKENS)


def _validation_cache_payload(settings: dict[str, object] | None) -> dict[str, object]:
    raw = settings.get(_VALIDATION_CACHE_KEY) if isinstance(settings, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def _validation_cache_status(settings: dict[str, object] | None) -> tuple[str, str]:
    payload = _validation_cache_payload(settings)
    state = str(payload.get("state", "") or "").strip().lower()
    text = str(payload.get("text", "") or "").strip()
    if state in {"ok", "error"} and text:
        return state, text
    return "", ""


@dataclass(frozen=True)
class CredentialFieldSpec:
    key: str
    label: str
    placeholder: str = ""
    help_text: str = ""


@dataclass(frozen=True)
class CredentialPluginSpec:
    plugin_id: str
    title: str
    subtitle: str
    description: str
    stage_id: str
    stage_label: str
    fields: tuple[CredentialFieldSpec, ...]
    validate_action_id: str = ""
    validate_payload: dict[str, Any] | None = None
    links: tuple[tuple[str, str], ...] = ()


def build_credentials_hub_specs(
    catalog,
    *,
    action_ids_by_plugin: dict[str, set[str]] | None = None,
    stage_label: Callable[[str], str] | None = None,
) -> list[CredentialPluginSpec]:
    specs: list[CredentialPluginSpec] = []
    action_index = dict(action_ids_by_plugin or {})
    for plugin in sorted(catalog.all_plugins(), key=lambda item: (catalog.display_name(item.plugin_id), item.plugin_id)):
        schema = catalog.schema_for(plugin.plugin_id)
        fields = _credential_fields_for_plugin(plugin, schema)
        if not fields:
            continue
        validate_action_id, validate_payload = _resolve_validate_action(plugin, action_index.get(plugin.plugin_id, set()))
        stage_name = stage_label(plugin.stage_id) if callable(stage_label) else str(plugin.stage_id or "").strip()
        subtitle = str(plugin.provider_name or plugin.name or "").strip() or stage_name
        description = _credentials_description(plugin)
        links = _credentials_links(plugin)
        specs.append(
            CredentialPluginSpec(
                plugin_id=plugin.plugin_id,
                title=str(plugin.product_name or plugin.name or plugin.plugin_id).strip() or plugin.plugin_id,
                subtitle=subtitle,
                description=description,
                stage_id=str(plugin.stage_id or "").strip(),
                stage_label=stage_name,
                fields=tuple(fields),
                validate_action_id=validate_action_id,
                validate_payload=validate_payload,
                links=tuple(links),
            )
        )
    return specs


def _credential_fields_for_plugin(plugin: PluginDescriptor, schema: PluginUiSchema | None) -> list[CredentialFieldSpec]:
    schema_fields: dict[str, CredentialFieldSpec] = {}
    for setting in getattr(schema, "settings", []) or []:
        key = str(getattr(setting, "key", "") or "").strip()
        if not key or not _is_secret_field_name(key):
            continue
        schema_fields[key] = CredentialFieldSpec(
            key=key,
            label=str(getattr(setting, "label", "") or key).strip() or key,
        )

    cap_fields = _cap_get(getattr(plugin, "capabilities", {}), "credentials_hub", "fields", default=[])
    if isinstance(cap_fields, list) and cap_fields:
        resolved: list[CredentialFieldSpec] = []
        seen: set[str] = set()
        for entry in cap_fields:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key", "") or "").strip()
            if not key:
                continue
            base = schema_fields.get(key)
            label = str(entry.get("label", "") or (base.label if base else key)).strip() or key
            placeholder = str(entry.get("placeholder", "") or "").strip()
            help_text = str(entry.get("help_text", "") or entry.get("help", "") or "").strip()
            resolved.append(
                CredentialFieldSpec(
                    key=key,
                    label=label,
                    placeholder=placeholder,
                    help_text=help_text,
                )
            )
            seen.add(key)
        for key, field in schema_fields.items():
            if key not in seen:
                resolved.append(field)
        return resolved

    if schema_fields:
        return list(schema_fields.values())

    required = _cap_get(getattr(plugin, "capabilities", {}), "health", "required_settings", default=[])
    resolved: list[CredentialFieldSpec] = []
    seen: set[str] = set()
    if isinstance(required, list):
        for group in required:
            if not isinstance(group, dict):
                continue
            label = str(group.get("label", "") or "Credential").strip()
            keys = group.get("keys")
            if not isinstance(keys, list):
                continue
            for key in keys:
                clean_key = str(key or "").strip()
                if not clean_key or clean_key in seen or not _is_secret_field_name(clean_key):
                    continue
                resolved.append(CredentialFieldSpec(key=clean_key, label=label))
                seen.add(clean_key)
    return resolved


def _resolve_validate_action(plugin: PluginDescriptor, action_ids: set[str]) -> tuple[str, dict[str, Any]]:
    configured = _cap_get(getattr(plugin, "capabilities", {}), "credentials_hub", "validate_action", default="")
    payload = _cap_get(getattr(plugin, "capabilities", {}), "credentials_hub", "validate_payload", default={})
    action_id = str(configured or "").strip()
    if action_id:
        return action_id, dict(payload) if isinstance(payload, dict) else {}
    for candidate in ("test_connection", "health_check", "health", "check_server"):
        if candidate in set(action_ids or set()):
            return candidate, {}
    return "", {}


def _credentials_description(plugin: PluginDescriptor) -> str:
    configured = _cap_get(getattr(plugin, "capabilities", {}), "credentials_hub", "description", default="")
    text = str(configured or "").strip()
    if text:
        return text
    return str(plugin.provider_description or plugin.description or "").strip()


def _credentials_links(plugin: PluginDescriptor) -> list[tuple[str, str]]:
    raw = _cap_get(getattr(plugin, "capabilities", {}), "credentials_hub", "links", default=[])
    if not isinstance(raw, list):
        return []
    links: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "") or "").strip()
        url = str(entry.get("url", "") or "").strip()
        if label and url:
            links.append((label, url))
    return links


class _CredentialPluginCard(QFrame):
    secretEdited = Signal(str, str)
    validateRequested = Signal(str)
    clearRequested = Signal(str, str)

    def __init__(
        self,
        spec: CredentialPluginSpec,
        *,
        labels: dict[str, str],
        saved_flags: dict[str, bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        self._labels = dict(labels or {})
        self._edits: dict[str, QLineEdit] = {}
        self._field_presence: dict[str, QLabel] = {}
        self._saved_flags = {str(key): bool(val) for key, val in (saved_flags or {}).items()}

        self.setObjectName("modelSetupCard")
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title = QLabel(spec.title)
        title.setObjectName("listTileTitle")
        title_col.addWidget(title)
        subtitle_text = " / ".join([part for part in (spec.subtitle, spec.stage_label) if part])
        if subtitle_text:
            subtitle = QLabel(subtitle_text)
            subtitle.setObjectName("pipelineMetaLabel")
            subtitle.setWordWrap(True)
            title_col.addWidget(subtitle)
        top.addLayout(title_col, 1)
        self._status = QLabel("")
        self._status.setObjectName("pipelineMetaLabel")
        self._status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._status, 0)
        layout.addLayout(top)

        if spec.description:
            body = QLabel(spec.description)
            body.setObjectName("listTileMeta")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(body)

        if spec.links:
            links = QLabel(
                " | ".join(
                    f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'
                    for label, url in spec.links
                )
            )
            links.setObjectName("listTileMeta")
            links.setWordWrap(True)
            links.setTextFormat(Qt.RichText)
            links.setTextInteractionFlags(Qt.TextBrowserInteraction)
            links.setOpenExternalLinks(True)
            layout.addWidget(links)

        for field in spec.fields:
            field_wrap = QWidget(self)
            field_layout = QVBoxLayout(field_wrap)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)

            label = QLabel(field.label)
            label.setObjectName("statusMeta")
            field_layout.addWidget(label)

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            edit = QLineEdit("")
            edit.setEchoMode(QLineEdit.Password)
            placeholder = field.placeholder or _tr_map(
                self._labels,
                "credentials.placeholder.enter",
                "Enter a new secret value",
            )
            if self._saved_flags.get(field.key):
                placeholder = _tr_map(
                    self._labels,
                    "credentials.placeholder.saved",
                    "Saved secret exists. Enter a new value to replace it.",
                )
            edit.setPlaceholderText(placeholder)
            edit.textChanged.connect(lambda _text, pid=spec.plugin_id, key=field.key: self.secretEdited.emit(pid, key))
            self._edits[field.key] = edit
            row.addWidget(edit, 1)

            clear_btn = QPushButton(_tr_map(self._labels, "credentials.button.clear", "Clear"))
            clear_btn.clicked.connect(lambda *_a, pid=spec.plugin_id, key=field.key: self.clearRequested.emit(pid, key))
            row.addWidget(clear_btn, 0)

            presence = QLabel("")
            presence.setObjectName("pipelineMetaLabel")
            self._field_presence[field.key] = presence
            row.addWidget(presence, 0)
            field_layout.addLayout(row)

            if field.help_text:
                help_label = QLabel(field.help_text)
                help_label.setObjectName("pipelineMetaLabel")
                help_label.setWordWrap(True)
                field_layout.addWidget(help_label)

            layout.addWidget(field_wrap)
            self._refresh_field_presence(field.key, pending=False)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        self._check_btn = QPushButton(_tr_map(self._labels, "credentials.button.check", "Check"))
        self._check_btn.clicked.connect(lambda *_a: self.validateRequested.emit(spec.plugin_id))
        actions.addWidget(self._check_btn, 0)
        layout.addLayout(actions)

        self.set_validation_status(
            "idle",
            _tr_map(self._labels, "credentials.status.missing", "Missing credentials.")
            if not any(self._saved_flags.values())
            else _tr_map(self._labels, "credentials.status.saved", "Credentials are saved."),
        )

    def current_secret_values(self) -> dict[str, str]:
        return {key: str(edit.text() or "") for key, edit in self._edits.items()}

    def mark_field_dirty(self, key: str) -> None:
        self._refresh_field_presence(str(key or "").strip(), pending=True)

    def update_saved_flag(self, key: str, saved: bool) -> None:
        clean_key = str(key or "").strip()
        self._saved_flags[clean_key] = bool(saved)
        self._refresh_field_presence(clean_key, pending=False)
        edit = self._edits.get(clean_key)
        if isinstance(edit, QLineEdit) and not str(edit.text() or "").strip():
            if saved:
                edit.setPlaceholderText(
                    _tr_map(
                        self._labels,
                        "credentials.placeholder.saved",
                        "Saved secret exists. Enter a new value to replace it.",
                    )
                )
            else:
                edit.setPlaceholderText(
                    _tr_map(
                        self._labels,
                        "credentials.placeholder.enter",
                        "Enter a new secret value",
                    )
                )

    def clear_field_value(self, key: str) -> None:
        edit = self._edits.get(str(key or "").strip())
        if isinstance(edit, QLineEdit):
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)

    def set_validation_status(self, state: str, text: str) -> None:
        palette = {
            "idle": "#64748B",
            "checking": "#2563EB",
            "ok": "#166534",
            "error": "#B91C1C",
        }
        normalized = str(state or "idle").strip().lower() or "idle"
        self._status.setStyleSheet(f"color: {palette.get(normalized, palette['idle'])};")
        self._status.setText(str(text or ""))

    def _refresh_field_presence(self, key: str, *, pending: bool) -> None:
        label = self._field_presence.get(str(key or "").strip())
        if not isinstance(label, QLabel):
            return
        if pending:
            label.setStyleSheet("color: #2563EB;")
            label.setText(_tr_map(self._labels, "credentials.field.pending", "Pending"))
            return
        if self._saved_flags.get(str(key or "").strip()):
            label.setStyleSheet("color: #166534;")
            label.setText(_tr_map(self._labels, "credentials.field.saved", "Saved"))
            return
        label.setStyleSheet("color: #92400E;")
        label.setText(_tr_map(self._labels, "credentials.field.missing", "Missing"))


class CredentialsHubPanel(QWidget):
    settingsChanged = Signal(str)

    def __init__(
        self,
        app_root: Path,
        settings_service: SettingsService,
        catalog_service: PluginCatalogService,
        action_service: PluginActionService,
        health_service: PluginHealthService,
        *,
        stage_label: Callable[[str], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_root = Path(app_root)
        self._settings = settings_service
        self._catalog_service = catalog_service
        self._action_service = action_service
        self._health_service = health_service
        self._stage_label = stage_label
        self._i18n = UiI18n(app_root, namespace="settings")
        self._cards: dict[str, _CredentialPluginCard] = {}
        self._specs: dict[str, CredentialPluginSpec] = {}
        self._states: dict[str, dict[str, object]] = {}
        self._labels = {
            "credentials.placeholder.saved": self._i18n.t(
                "credentials.placeholder.saved",
                "Saved secret exists. Enter a new value to replace it.",
            ),
            "credentials.placeholder.enter": self._i18n.t(
                "credentials.placeholder.enter",
                "Enter a new secret value",
            ),
            "credentials.button.clear": self._i18n.t("credentials.button.clear", "Clear"),
            "credentials.button.check": self._i18n.t("credentials.button.check", "Check"),
            "credentials.field.saved": self._i18n.t("credentials.field.saved", "Saved"),
            "credentials.field.missing": self._i18n.t("credentials.field.missing", "Missing"),
            "credentials.field.pending": self._i18n.t("credentials.field.pending", "Pending"),
            "credentials.status.missing": self._i18n.t("credentials.status.missing", "Missing credentials."),
            "credentials.status.saved": self._i18n.t("credentials.status.saved", "Credentials are saved."),
            "credentials.status.checking": self._i18n.t("credentials.status.checking", "Checking credentials..."),
            "credentials.status.verified": self._i18n.t("credentials.status.verified", "Connection verified."),
            "credentials.status.configured": self._i18n.t(
                "credentials.status.configured",
                "Credentials are configured.",
            ),
            "credentials.status.failed": self._i18n.t(
                "credentials.status.failed",
                "Validation failed: {error}",
            ),
            "credentials.status.removed": self._i18n.t(
                "credentials.status.removed",
                "Credential removed.",
            ),
            "credentials.empty": self._i18n.t(
                "credentials.empty",
                "No plugins with credentials were discovered.",
            ),
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(10)
        layout.addWidget(self._body)
        self.reload()

    def reload(self) -> None:
        self._clear()
        catalog = self._catalog_service.load().catalog
        action_ids_by_plugin: dict[str, set[str]] = {}
        for plugin in catalog.all_plugins():
            try:
                action_ids_by_plugin[plugin.plugin_id] = {
                    str(getattr(item, "action_id", "") or "").strip()
                    for item in self._action_service.list_actions(plugin.plugin_id)
                    if str(getattr(item, "action_id", "") or "").strip()
                }
            except Exception:
                action_ids_by_plugin[plugin.plugin_id] = set()
        specs = build_credentials_hub_specs(
            catalog,
            action_ids_by_plugin=action_ids_by_plugin,
            stage_label=self._stage_label,
        )
        if not specs:
            empty = QLabel(_tr_map(self._labels, "credentials.empty", "No plugins with credentials were discovered."))
            empty.setObjectName("pipelineMetaLabel")
            empty.setWordWrap(True)
            self._body_layout.addWidget(empty)
            return
        for spec in specs:
            saved_flags = self._settings.get_secret_flags(spec.plugin_id)
            card = _CredentialPluginCard(spec, labels=self._labels, saved_flags=saved_flags, parent=self._body)
            cached_settings = self._settings.get_settings(spec.plugin_id, include_secrets=False)
            cached_state, cached_text = _validation_cache_status(cached_settings)
            if cached_state and cached_text:
                card.set_validation_status(cached_state, cached_text)
            card.secretEdited.connect(self._on_secret_edited)
            card.validateRequested.connect(self._on_validate_requested)
            card.clearRequested.connect(self._on_clear_requested)
            self._cards[spec.plugin_id] = card
            self._specs[spec.plugin_id] = spec
            self._body_layout.addWidget(card)
            self._states[spec.plugin_id] = {
                "dirty_fields": set(),
                "request_id": 0,
                "timer": self._build_timer(spec.plugin_id),
            }
        self._body_layout.addStretch(1)

    def _clear(self) -> None:
        for state in self._states.values():
            timer = state.get("timer")
            if isinstance(timer, QTimer):
                timer.stop()
                timer.deleteLater()
        self._states = {}
        self._cards = {}
        self._specs = {}
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _build_timer(self, plugin_id: str) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(700)
        timer.timeout.connect(lambda pid=plugin_id: self._flush_plugin_validation(pid))
        return timer

    def _write_validation_cache(self, plugin_id: str, *, state: str, text: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        settings = self._settings.get_settings(pid, include_secrets=False)
        payload = dict(settings if isinstance(settings, dict) else {})
        payload[_VALIDATION_CACHE_KEY] = {
            "state": str(state or "").strip().lower(),
            "text": str(text or "").strip(),
            "updated_at": int(time.time()),
        }
        self._settings.set_settings(pid, payload)

    def _clear_validation_cache(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        settings = self._settings.get_settings(pid, include_secrets=False)
        if not isinstance(settings, dict) or _VALIDATION_CACHE_KEY not in settings:
            return
        payload = dict(settings)
        payload.pop(_VALIDATION_CACHE_KEY, None)
        self._settings.set_settings(pid, payload)

    def _on_secret_edited(self, plugin_id: str, key: str) -> None:
        pid = str(plugin_id or "").strip()
        field = str(key or "").strip()
        state = self._states.get(pid)
        card = self._cards.get(pid)
        if not state or card is None or not field:
            return
        dirty = state.setdefault("dirty_fields", set())
        if isinstance(dirty, set):
            dirty.add(field)
        self._clear_validation_cache(pid)
        card.mark_field_dirty(field)
        card.set_validation_status(
            "checking",
            _tr_map(self._labels, "credentials.status.checking", "Checking credentials..."),
        )
        timer = state.get("timer")
        if isinstance(timer, QTimer):
            timer.stop()
            timer.start()

    def _on_validate_requested(self, plugin_id: str) -> None:
        self._flush_plugin_validation(plugin_id, force=True)

    def _on_clear_requested(self, plugin_id: str, key: str) -> None:
        pid = str(plugin_id or "").strip()
        field = str(key or "").strip()
        if not pid or not field:
            return
        card = self._cards.get(pid)
        state = self._states.get(pid)
        if card is None or state is None:
            return
        timer = state.get("timer")
        if isinstance(timer, QTimer) and timer.isActive():
            timer.stop()
        dirty = state.get("dirty_fields")
        if isinstance(dirty, set):
            dirty.discard(field)
        self._clear_validation_cache(pid)
        self._settings.set_secret(pid, field, None)
        card.clear_field_value(field)
        card.update_saved_flag(field, False)
        card.set_validation_status(
            "idle",
            _tr_map(self._labels, "credentials.status.removed", "Credential removed."),
        )
        self.settingsChanged.emit(pid)

    def _flush_plugin_validation(self, plugin_id: str, *, force: bool = False) -> None:
        pid = str(plugin_id or "").strip()
        state = self._states.get(pid)
        card = self._cards.get(pid)
        spec = self._specs.get(pid)
        if not state or card is None or spec is None:
            return
        timer = state.get("timer")
        if isinstance(timer, QTimer) and timer.isActive():
            timer.stop()

        dirty_fields = state.setdefault("dirty_fields", set())
        if isinstance(dirty_fields, set):
            dirty_now = set(dirty_fields)
        else:
            dirty_now = set()
        values = card.current_secret_values()
        if not dirty_now and not force:
            return
        for field in dirty_now:
            self._settings.set_secret(pid, field, values.get(field, ""))
            card.update_saved_flag(field, bool(str(values.get(field, "") or "").strip()))
        if dirty_now:
            self.settingsChanged.emit(pid)
        dirty_fields.clear()

        request_id = int(state.get("request_id", 0) or 0) + 1
        state["request_id"] = request_id
        card.set_validation_status(
            "checking",
            _tr_map(self._labels, "credentials.status.checking", "Checking credentials..."),
        )

        settings_override = self._settings.get_settings(pid, include_secrets=True)
        _LOGGER.info(
            "credentials_validation_started plugin_id=%s fields=%s action=%s",
            pid,
            ",".join(sorted(dirty_now)),
            str(spec.validate_action_id or "").strip() or "health_check",
        )

        def _worker() -> tuple[str, str]:
            if spec.validate_action_id:
                result = self._action_service.invoke_action(
                    pid,
                    spec.validate_action_id,
                    dict(spec.validate_payload or {}),
                    settings_override=settings_override,
                )
                status, message, data = _action_status_message_data(result)
                if _is_success_status(status):
                    text = (
                        _tr_map(self._labels, "credentials.status.verified", "Connection verified.")
                        if spec.validate_action_id
                        else _tr_map(self._labels, "credentials.status.configured", "Credentials are configured.")
                    )
                    _LOGGER.info(
                        "credentials_validation_ok plugin_id=%s fields=%s action=%s",
                        pid,
                        ",".join(sorted(dirty_now)),
                        str(spec.validate_action_id or "").strip() or "health_check",
                    )
                    return "ok", text
                detail = str(data.get("error", "") or data.get("detail", "") or message or "").strip()
                log = (
                    _LOGGER.info
                    if _is_expected_provider_validation_failure(status, message, detail)
                    else _LOGGER.warning
                )
                log(
                    "credentials_validation_failed plugin_id=%s fields=%s action=%s status=%s message=%s detail=%s",
                    pid,
                    ",".join(sorted(dirty_now)),
                    str(spec.validate_action_id or "").strip() or "health_check",
                    status,
                    message,
                    detail,
                )
                return "error", detail or _tr_map(
                    self._labels,
                    "credentials.status.failed",
                    "Validation failed: {error}",
                ).format(error="unknown error")
            report = self._health_service.check_plugin(
                pid,
                stage_id=str(spec.stage_id or "").strip(),
                settings_override=settings_override,
                full_check=False,
                force=True,
                max_age_seconds=30.0,
                allow_disabled=True,
            )
            if getattr(report, "healthy", False):
                return "ok", _tr_map(
                    self._labels,
                    "credentials.status.configured",
                    "Credentials are configured.",
                )
            issues = tuple(getattr(report, "issues", ()) or ())
            if issues:
                first = issues[0]
                message = str(getattr(first, "summary", "") or getattr(first, "hint", "") or "").strip()
            else:
                message = _tr_map(
                    self._labels,
                    "credentials.status.failed",
                    "Validation failed: {error}",
                ).format(error="unknown error")
            issue_codes = ",".join(str(getattr(item, "code", "") or "").strip() for item in issues if item)
            log = (
                _LOGGER.info
                if _is_expected_provider_validation_failure(issue_codes, message)
                else _LOGGER.warning
            )
            log(
                "credentials_validation_failed plugin_id=%s fields=%s action=%s issues=%s message=%s",
                pid,
                ",".join(sorted(dirty_now)),
                "health_check",
                issue_codes,
                message,
            )
            return "error", message

        def _on_finished(done_request_id: int, payload: object) -> None:
            if int(self._states.get(pid, {}).get("request_id", 0) or 0) != int(done_request_id):
                return
            state_code, message = payload if isinstance(payload, tuple) and len(payload) == 2 else ("error", "")
            card.set_validation_status(str(state_code), str(message or ""))
            normalized_state = "ok" if str(state_code or "").strip().lower() == "ok" else "error"
            self._write_validation_cache(pid, state=normalized_state, text=str(message or ""))

        def _on_error(done_request_id: int, error: Exception) -> None:
            if int(self._states.get(pid, {}).get("request_id", 0) or 0) != int(done_request_id):
                return
            _LOGGER.exception(
                "credentials_validation_exception plugin_id=%s fields=%s action=%s error=%s",
                pid,
                ",".join(sorted(dirty_now)),
                str(spec.validate_action_id or "").strip() or "health_check",
                error,
            )
            card.set_validation_status(
                "error",
                _tr_map(self._labels, "credentials.status.failed", "Validation failed: {error}").format(
                    error=str(error),
                ),
            )
            self._write_validation_cache(
                pid,
                state="error",
                text=_tr_map(self._labels, "credentials.status.failed", "Validation failed: {error}").format(
                    error=str(error),
                ),
            )

        run_async(
            request_id=request_id,
            fn=_worker,
            on_finished=_on_finished,
            on_error=_on_error,
        )


def _tr_map(labels: dict[str, str], key: str, default: str) -> str:
    value = str((labels or {}).get(key, "") or "").strip()
    return value or str(default or "")
