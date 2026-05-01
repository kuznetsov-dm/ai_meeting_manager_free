from __future__ import annotations

import html
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aimn.core.api import (
    PluginActionService,
    PluginCatalogService,
    PluginModelsService,
    SettingsService,
)
from aimn.ui.i18n import UiI18n
from aimn.ui.widgets.standard_components import (
    StandardBadge,
    StandardSelectableChip,
    StandardStatusBadge,
)

try:
    from shiboken6 import isValid as _is_valid
except ImportError:  # pragma: no cover - fallback when shiboken6 is unavailable

    def _is_valid(_obj: object) -> bool:
        return True


_LOG = logging.getLogger(__name__)
_MODEL_UI_RUNTIME_ERRORS = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
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
    if lowered.endswith("_key") or lowered.endswith("_keys"):
        return True
    return lowered.startswith("key_")


@dataclass(frozen=True)
class ModelEntry:
    model_id: str
    title: str
    status_label: str
    status_bg: str
    status_fg: str
    meta_lines: list[str]
    links_html: str = ""
    enabled: bool | None = None
    can_toggle: bool = False
    toggle_label: str = ""
    can_download: bool = False
    can_cancel_download: bool = False
    can_remove: bool = False
    observed_success: bool = False
    quant: str = ""
    file_name: str = ""
    download_job_active: bool = False
    gated: bool = False
    tooltip: str = ""
    primary_action_label: str = ""
    primary_action_tooltip: str = ""


def _tr_map(labels: dict[str, str], key: str, default: str) -> str:
    value = str((labels or {}).get(key, "") or "").strip()
    return value or str(default or "")


def _compose_setup_message(
    labels: dict[str, str],
    *,
    description: str = "",
    highlights: str = "",
    howto: list[str] | None = None,
) -> str:
    lines = [
        _tr_map(
            labels,
            "models.setup.intro",
            "This provider is ready, but it needs a local model before it can generate LLM output.",
        ),
        "",
        _tr_map(labels, "models.setup.choices", "Choose one of the setup paths below:"),
        _tr_map(
            labels,
            "models.setup.option_catalog",
            "1. Add a model from the catalog below, then download it.",
        ),
        _tr_map(
            labels,
            "models.setup.option_custom",
            "2. Add your own model entry or direct model-file URL if the provider supports it.",
        ),
        _tr_map(
            labels,
            "models.setup.option_file",
            "3. Use a local model file from disk if the provider supports direct file selection.",
        ),
    ]
    extra = str(highlights or "").strip() or str(description or "").strip()
    if extra:
        lines.extend(["", extra])
    steps = [str(item or "").strip() for item in (howto or []) if str(item or "").strip()]
    if steps:
        lines.extend(["", _tr_map(labels, "models.setup.help_title", "Plugin setup notes:")])
        lines.extend(f"- {step}" for step in steps[:3])
    return "\n".join(lines).strip()


def _apply_curated_model_metadata(row: dict, curated: dict, model_id: str) -> dict:
    updated = dict(row)
    updated["product_name"] = str(curated.get("model_name", "") or row.get("product_name", "") or model_id).strip()
    updated["description"] = str(curated.get("model_description", "") or curated.get("description", "") or "").strip()
    updated["quant"] = str(curated.get("quant", "") or row.get("quant", "") or "").strip()
    updated["source_url"] = str(curated.get("source_url", "") or "").strip()
    updated["download_url"] = str(curated.get("download_url", "") or "").strip()
    size_hint = str(curated.get("size_hint", "") or "").strip()
    if size_hint:
        updated["size_hint"] = size_hint
    else:
        updated.pop("size_hint", None)

    explicit_file = str(curated.get("file", "") or curated.get("filename", "") or "").strip()
    if explicit_file:
        updated["file"] = explicit_file
    else:
        updated.pop("file", None)
        updated.pop("filename", None)

    explicit_model_path = str(curated.get("model_path", "") or curated.get("path", "") or "").strip()
    if explicit_model_path:
        updated["model_path"] = explicit_model_path
    else:
        updated.pop("model_path", None)
        updated.pop("path", None)

    updated["catalog_source"] = str(curated.get("catalog_source", "") or "recommended").strip() or "recommended"
    updated["user_added"] = False
    return updated


_HF_TOKENS_URL = "https://huggingface.co/settings/tokens"
_HF_TOKEN_DOCS_URL = "https://huggingface.co/docs/hub/security-tokens"
_OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
_OLLAMA_INSTALL_GUIDE_URL = "https://ollama.com/library"
_OLLAMA_RUNTIME_META_KEY = "_ollama_runtime_state"


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_hf_repo_url(url: str) -> bool:
    raw = str(url or "").strip().lower()
    return raw.startswith("https://huggingface.co/") or raw.startswith("http://huggingface.co/")


def _looks_like_http_url(value: str) -> bool:
    raw = str(value or "").strip().lower()
    return raw.startswith("https://") or raw.startswith("http://")


def _preferred_model_link(meta: dict, model_id: str) -> str:
    download_url = str(meta.get("download_url", "") or "").strip()
    if download_url:
        return download_url
    file_name = str(meta.get("file", "") or meta.get("filename", "") or "").strip()
    source_url = str(meta.get("source_url", "") or "").strip().rstrip("/")
    if file_name and _looks_like_hf_repo_url(source_url):
        return f"{source_url}/resolve/main/{file_name}"
    if source_url:
        return source_url
    mid = str(model_id or "").strip()
    if "/" in mid:
        return f"https://huggingface.co/{mid}"
    return ""


def _is_gated_model(meta: dict, model_id: str) -> bool:
    if _boolish(meta.get("gated")) or _boolish(meta.get("requires_hf_token")):
        return True
    source_url = str(meta.get("source_url", "") or "").strip().lower()
    mid = str(model_id or "").strip().lower()
    gated_prefixes = (
        "https://huggingface.co/meta-llama/",
        "https://huggingface.co/google/gemma-",
        "meta-llama/",
        "google/gemma-",
    )
    return any(source_url.startswith(prefix) or mid.startswith(prefix) for prefix in gated_prefixes)


def _external_link_html(url: str, label: str) -> str:
    raw_url = str(url or "").strip()
    raw_label = str(label or "").strip()
    if not raw_url or not raw_label:
        return ""
    return f'<a href="{html.escape(raw_url, quote=True)}">{html.escape(raw_label)}</a>'


def _gated_links_html(labels: dict[str, str], model_url: str) -> str:
    parts = [
        _external_link_html(model_url, _tr_map(labels, "models.links.model_page", "Model page")),
        _external_link_html(_HF_TOKENS_URL, _tr_map(labels, "models.links.get_token", "Get token")),
        _external_link_html(_HF_TOKEN_DOCS_URL, _tr_map(labels, "models.links.token_docs", "Token docs")),
    ]
    links = " | ".join([part for part in parts if part])
    if not links:
        return ""
    return (
        f"{html.escape(_tr_map(labels, 'models.links.gated_help', 'HF access required:'))} {links}"
    )


def _gated_tooltip(labels: dict[str, str], model_url: str) -> str:
    title = _tr_map(labels, "models.tooltip.gated_title", "This model is gated on Hugging Face.")
    step_1 = _tr_map(
        labels,
        "models.tooltip.gated_step_1",
        "1. Open the model page and request or accept access.",
    )
    step_2 = _tr_map(
        labels,
        "models.tooltip.gated_step_2",
        "2. Create a User Access Token in Hugging Face settings.",
    )
    step_3 = _tr_map(
        labels,
        "models.tooltip.gated_step_3",
        "3. Set HUGGINGFACE_HUB_TOKEN, HF_TOKEN, or AIMN_HF_TOKEN before downloading.",
    )
    links_title = _tr_map(labels, "models.tooltip.links", "Links:")
    lines = [title, "", step_1, step_2, step_3, "", links_title]
    if model_url:
        lines.append(f"- {_tr_map(labels, 'models.links.model_page', 'Model page')}: {model_url}")
    lines.append(f"- {_tr_map(labels, 'models.links.get_token', 'Get token')}: {_HF_TOKENS_URL}")
    lines.append(f"- {_tr_map(labels, 'models.links.token_docs', 'Token docs')}: {_HF_TOKEN_DOCS_URL}")
    return "\n".join(lines).strip()


def _friendly_download_error(
    labels: dict[str, str],
    action_message: str,
    result: object,
    *,
    plugin_id: str = "",
) -> str:
    message = str(action_message or "").strip()
    data = _action_result_data(result)
    detail = str(data.get("error", "") or data.get("detail", "") or "").strip()
    pid = str(plugin_id or "").strip()
    combined = " ".join(part for part in (message, detail) if part).strip().lower()
    if message == "model_file_resolution_failed":
        if detail:
            return detail
        return _tr_map(
            labels,
            "models.note.download_help_required",
            "This model may require Hugging Face access. Open the links in the card and configure credentials.",
        )
    if pid == "llm.ollama":
        if "binary not found" in combined or "not found in path" in combined:
            return (
                "Ollama is not installed on this computer. "
                f"Install Ollama first: {_OLLAMA_DOWNLOAD_URL}"
            )
        if "server_not_running" in combined or "connection refused" in combined or "failed to establish a new connection" in combined:
            return (
                "Ollama is not running. Start Ollama and try again. "
                f"If it is not installed yet, install it here: {_OLLAMA_DOWNLOAD_URL}"
            )
    return detail or message


class _ActionWorker(QObject):
    finished_ok = Signal(str, str, object)
    finished_error = Signal(str, str, str)

    def __init__(
        self,
        action_service: PluginActionService,
        plugin_id: str,
        action_id: str,
        payload: dict,
    ) -> None:
        super().__init__()
        self._action_service = action_service
        self._plugin_id = str(plugin_id or "").strip()
        self._action_id = str(action_id or "").strip()
        self._payload = dict(payload or {})

    def run(self) -> None:
        try:
            result = self._action_service.invoke_action(self._plugin_id, self._action_id, self._payload)
        except _MODEL_UI_RUNTIME_ERRORS as exc:
            _LOG.warning(
                "model_action_worker_failed plugin_id=%s action_id=%s error=%s",
                self._plugin_id,
                self._action_id,
                exc,
            )
            self.finished_error.emit(self._plugin_id, self._action_id, str(exc))
            return
        self.finished_ok.emit(self._plugin_id, self._action_id, result)


_ACTION_THREAD_KEEPALIVE: dict[int, tuple[QThread, _ActionWorker]] = {}
_MODEL_JOB_STATES: dict[str, dict[str, object]] = {}


def _keepalive_register(thread: QThread, worker: _ActionWorker) -> int:
    key = id(thread)
    _ACTION_THREAD_KEEPALIVE[key] = (thread, worker)
    return key


def _keepalive_unregister(key: int) -> None:
    _ACTION_THREAD_KEEPALIVE.pop(key, None)


class ModelCard(QFrame):
    def __init__(
        self,
        entry: ModelEntry,
        *,
        labels: dict[str, str] | None = None,
        on_toggle: Callable[[bool], None] | None = None,
        on_primary_action: Callable[[], None] | None = None,
        on_download: Callable[[], None] | None = None,
        on_cancel_download: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._labels = dict(labels or {})
        self.setObjectName("modelCard")
        self.setProperty("aimn_model_id", str(entry.model_id or ""))
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(120)
        if entry.tooltip:
            self.setToolTip(entry.tooltip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(entry.title)
        title.setObjectName("listTileTitle")
        top.addWidget(title, 1)
        if entry.can_toggle:
            favorite_toggle = StandardSelectableChip(_tr_map(self._labels, "models.card.enabled", "Enabled"))
            favorite_toggle.set_compact_mode(True, max_chars=18)
            favorite_toggle.apply_state(
                selected=bool(entry.enabled),
                active=bool(entry.enabled),
                tone="success",
                checked=bool(entry.enabled),
            )
            if entry.tooltip:
                favorite_toggle.setToolTip(entry.tooltip)
            favorite_toggle.clicked.connect(lambda checked=False: on_toggle(bool(checked)) if on_toggle else None)
            top.addWidget(favorite_toggle, 0, Qt.AlignRight)
        if entry.observed_success:
            success_badge = StandardBadge(_tr_map(self._labels, "models.badge.observed_success", "Observed success"))
            success_badge.set_kind("success")
            top.addWidget(success_badge, 0, Qt.AlignRight)
        if entry.gated:
            gated_badge = StandardBadge(_tr_map(self._labels, "models.badge.gated", "Gated"))
            gated_badge.set_kind("warning")
            if entry.tooltip:
                gated_badge.setToolTip(entry.tooltip)
            top.addWidget(gated_badge, 0, Qt.AlignRight)

        layout.addLayout(top)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status = StandardStatusBadge(entry.status_label)
        status.set_kind(self._status_kind(entry))
        if entry.tooltip:
            status.setToolTip(entry.tooltip)
        status_row.addWidget(status, 0, Qt.AlignLeft)
        status_row.addStretch(1)
        if entry.primary_action_label:
            btn = QPushButton(entry.primary_action_label)
            if entry.primary_action_tooltip:
                btn.setToolTip(entry.primary_action_tooltip)
            elif entry.tooltip:
                btn.setToolTip(entry.tooltip)
            btn.clicked.connect(lambda *_a: on_primary_action() if on_primary_action else None)
            status_row.addWidget(btn, 0, Qt.AlignRight)
        layout.addLayout(status_row)

        for idx, line in enumerate(entry.meta_lines):
            label = QLabel(line)
            label.setObjectName("listTileMetaPrimary" if idx == 0 else "listTileMeta")
            label.setWordWrap(True)
            if entry.tooltip:
                label.setToolTip(entry.tooltip)
            layout.addWidget(label)

        if entry.links_html:
            links = QLabel(entry.links_html)
            links.setObjectName("listTileMeta")
            links.setWordWrap(True)
            links.setTextFormat(Qt.RichText)
            links.setTextInteractionFlags(Qt.TextBrowserInteraction)
            links.setOpenExternalLinks(True)
            if entry.tooltip:
                links.setToolTip(entry.tooltip)
            layout.addWidget(links)

        if entry.can_download or entry.can_cancel_download or entry.can_remove:
            actions = QHBoxLayout()
            actions.setSpacing(8)
            actions.addStretch(1)
            if entry.can_download:
                btn = QPushButton(_tr_map(self._labels, "models.button.download", "Download"))
                if entry.tooltip:
                    btn.setToolTip(entry.tooltip)
                btn.clicked.connect(lambda *_a: on_download() if on_download else None)
                actions.addWidget(btn, 0, Qt.AlignRight)
            if entry.can_cancel_download:
                btn = QPushButton(_tr_map(self._labels, "models.button.cancel_download", "Cancel"))
                if entry.tooltip:
                    btn.setToolTip(entry.tooltip)
                btn.clicked.connect(lambda *_a: on_cancel_download() if on_cancel_download else None)
                actions.addWidget(btn, 0, Qt.AlignRight)
            if entry.can_remove:
                btn = QPushButton(_tr_map(self._labels, "models.button.remove", "Remove"))
                if entry.tooltip:
                    btn.setToolTip(entry.tooltip)
                btn.clicked.connect(lambda *_a: on_remove() if on_remove else None)
                actions.addWidget(btn, 0, Qt.AlignRight)
            layout.addLayout(actions)

    @staticmethod
    def _status_kind(entry: ModelEntry) -> str:
        text = f"{str(entry.status_label or '').lower()} {str(entry.status_bg or '').lower()} {str(entry.status_fg or '').lower()}"
        if "unavailable" in text or "error" in text or "fail" in text:
            return "danger"
        if "blocked" in text or "auth issue" in text:
            return "danger"
        if "limited" in text:
            return "warning"
        if "download" in text or "queued" in text:
            return "focus"
        if "needs setup" in text or "not installed" in text or "missing" in text:
            return "warning"
        if "unknown" in text:
            return "neutral"
        if "installed" in text or "active" in text or "ready" in text:
            return "success"
        return "neutral"


class ModelCardsPanel(QWidget):
    modelsChanged = Signal(str)

    def __init__(
        self,
        app_root: Path,
        settings_service: SettingsService,
        models_service: PluginModelsService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_root = Path(app_root)
        self._i18n = UiI18n(app_root, namespace="settings")
        self._settings = settings_service
        self._models = models_service
        self._catalog_service = PluginCatalogService(app_root)
        self._action_service = PluginActionService(app_root, catalog_service=self._catalog_service)

        self._plugin_id: str = ""
        self._action_thread: QThread | None = None
        self._action_worker: _ActionWorker | None = None
        self._job_states = _MODEL_JOB_STATES
        self._catalog_loaded_once: set[str] = set()
        self._pending_model_actions: dict[tuple[str, str], str] = {}
        self._focus_model_after_render: tuple[str, str] = ("", "")
        self._job_poll_timer = QTimer(self)
        self._job_poll_timer.setSingleShot(False)
        self._job_poll_timer.setInterval(700)
        self._job_poll_timer.timeout.connect(self._poll_active_job)
        self._advanced_mode = False
        self._labels = {
            "models.title": self._i18n.t("models.title", "Models"),
            "models.button.refresh_catalog": self._i18n.t(
                "models.button.refresh_catalog",
                "Refresh available models",
            ),
            "models.button.add_selected": self._i18n.t("models.button.add_selected", "Add selected"),
            "models.button.add_custom_toggle": self._i18n.t("models.button.add_custom_toggle", "Add custom model"),
            "models.button.retest_failed": self._i18n.t(
                "models.button.retest_failed",
                "Recheck unavailable",
            ),
            "models.button.add_custom": self._i18n.t("models.button.add_custom", "Add custom"),
            "models.button.pick_local_file": self._i18n.t("models.button.pick_local_file", "Use local model file"),
            "models.button.download": self._i18n.t("models.button.download", "Download"),
            "models.button.remove": self._i18n.t("models.button.remove", "Remove"),
            "models.label.available": self._i18n.t("models.label.available", "Available models"),
            "models.help.selection": self._i18n.t(
                "models.help.selection",
                "All available models appear in stage settings. Add or download models here to use them in a stage.",
            ),
            "models.placeholder.available": self._i18n.t("models.placeholder.available", "Select model"),
            "models.placeholder.custom": self._i18n.t(
                "models.placeholder.custom",
                "Model ID / repo / tag (optional if URL is provided)",
            ),
            "models.placeholder.custom_url": self._i18n.t(
                "models.placeholder.custom_url",
                "Direct model file URL (optional if model ID is provided)",
            ),
            "models.help.custom": self._i18n.t(
                "models.help.custom",
                "Fill model ID/tag, direct URL, or both. URL-only is supported and will use the file name as the model ID.",
            ),
            "models.note.custom_requires_input": self._i18n.t(
                "models.note.custom_requires_input",
                "Enter a model ID / tag, a direct model URL, or both.",
            ),
            "models.note.custom_requires_real_id": self._i18n.t(
                "models.note.custom_requires_real_id",
                "If the first field is only a display name, also provide a direct model URL so the real model ID can be derived.",
            ),
            "models.empty.none": self._i18n.t("models.empty.none", "No models configured."),
            "models.empty.loading": self._i18n.t("models.empty.loading", "Loading model catalog..."),
            "models.note.action_failed": self._i18n.t("models.note.action_failed", "Action failed."),
            "models.note.model_removed": self._i18n.t("models.note.model_removed", "Model removed: {value}"),
            "models.note.model_remove_missing": self._i18n.t(
                "models.note.model_remove_missing",
                "Local model file was not found: {value}",
            ),
            "models.note.download_started": self._i18n.t(
                "models.note.download_started",
                "Download started: {value}",
            ),
            "models.note.download_progress": self._i18n.t(
                "models.note.download_progress",
                "Downloading {value}: {progress}%",
            ),
            "models.note.download_success": self._i18n.t(
                "models.note.download_success",
                "Download completed: {value}",
            ),
            "models.note.testing_started": self._i18n.t(
                "models.note.testing_started",
                "Checking availability: {value}",
            ),
            "models.note.testing_success": self._i18n.t(
                "models.note.testing_success",
                "Availability confirmed: {value}",
            ),
            "models.note.testing_success_provider": self._i18n.t(
                "models.note.testing_success_provider",
                "Provider is ready: {value}",
            ),
            "models.note.testing_failed": self._i18n.t(
                "models.note.testing_failed",
                "Availability check failed for {value}: {reason}",
            ),
            "models.note.download_failed": self._i18n.t(
                "models.note.download_failed",
                "Download failed for {value}: {reason}",
            ),
            "models.note.download_help_required": self._i18n.t(
                "models.note.download_help_required",
                "This model may require Hugging Face access. Open the links in the card and configure credentials.",
            ),
            "models.note.retest_failed_complete": self._i18n.t(
                "models.note.retest_failed_complete",
                "Rechecked {retested} model(s). Ready now: {selectable}/{total}.",
            ),
            "models.note.local_file_selected": self._i18n.t(
                "models.note.local_file_selected",
                "Local model file selected: {value}",
            ),
            "models.badge.gated": self._i18n.t("models.badge.gated", "Gated"),
            "models.badge.observed_success": self._i18n.t(
                "models.badge.observed_success",
                "Observed success",
            ),
            "models.status.ready": self._i18n.t("models.status.ready", "Ready"),
            "models.status.needs_setup": self._i18n.t("models.status.needs_setup", "Needs setup"),
            "models.status.unknown": self._i18n.t("models.status.unknown", "Unknown"),
            "models.status.unavailable": self._i18n.t("models.status.unavailable", "Unavailable"),
            "models.status.limited": self._i18n.t("models.status.limited", "Limited"),
            "models.status.blocked_for_account": self._i18n.t(
                "models.status.blocked_for_account",
                "Blocked for this account",
            ),
            "models.status.testing": self._i18n.t("models.status.testing", "Testing..."),
            "models.status.download_queued": self._i18n.t("models.status.download_queued", "Queued"),
            "models.status.downloading": self._i18n.t("models.status.downloading", "Downloading {progress}%"),
            "models.card.enabled": self._i18n.t("models.card.enabled", "Enabled"),
            "models.meta.blocked_for_account": self._i18n.t(
                "models.meta.blocked_for_account",
                "Blocked for this account",
            ),
            "models.meta.observed_success": self._i18n.t(
                "models.meta.observed_success",
                "Observed successful run",
            ),
            "models.meta.id": self._i18n.t("models.meta.id", "ID: {value}"),
            "models.meta.quant": self._i18n.t("models.meta.quant", "Quant: {value}"),
            "models.meta.file": self._i18n.t("models.meta.file", "File: {value}"),
            "models.meta.size": self._i18n.t("models.meta.size", "Size: {value}"),
            "models.meta.size_na": self._i18n.t("models.meta.size_na", "n/a"),
            "models.meta.source": self._i18n.t("models.meta.source", "Source: {value}"),
            "models.meta.download": self._i18n.t("models.meta.download", "Download: {value}"),
            "models.links.gated_help": self._i18n.t("models.links.gated_help", "HF access required:"),
            "models.links.model_page": self._i18n.t("models.links.model_page", "Model page"),
            "models.links.get_token": self._i18n.t("models.links.get_token", "Get token"),
            "models.links.token_docs": self._i18n.t("models.links.token_docs", "Token docs"),
            "models.tooltip.gated_title": self._i18n.t(
                "models.tooltip.gated_title",
                "This model is gated on Hugging Face.",
            ),
            "models.tooltip.gated_step_1": self._i18n.t(
                "models.tooltip.gated_step_1",
                "1. Open the model page and request or accept access.",
            ),
            "models.tooltip.gated_step_2": self._i18n.t(
                "models.tooltip.gated_step_2",
                "2. Create a User Access Token in Hugging Face settings.",
            ),
            "models.tooltip.gated_step_3": self._i18n.t(
                "models.tooltip.gated_step_3",
                "3. Set HUGGINGFACE_HUB_TOKEN, HF_TOKEN, or AIMN_HF_TOKEN before downloading.",
            ),
            "models.tooltip.links": self._i18n.t("models.tooltip.links", "Links:"),
            "models.meta.download_progress": self._i18n.t(
                "models.meta.download_progress",
                "Download progress: {progress}%",
            ),
            "models.meta.testing": self._i18n.t("models.meta.testing", "Model test in progress..."),
            "models.meta.retry_after": self._i18n.t("models.meta.retry_after", "Retry after: {value}"),
            "models.meta.last_checked": self._i18n.t("models.meta.last_checked", "Last checked: {value}"),
            "models.meta.last_ok": self._i18n.t("models.meta.last_ok", "Last successful test: {value}"),
            "models.meta.reason": self._i18n.t("models.meta.reason", "Reason: {value}"),
            "models.meta.provider_model_missing": self._i18n.t("models.meta.provider_model_missing", "Model not found"),
            "models.meta.provider_unavailable": self._i18n.t("models.meta.provider_unavailable", "Not available"),
            "models.meta.provider_bad_request": self._i18n.t("models.meta.provider_bad_request", "Bad request"),
            "models.meta.provider_empty_response": self._i18n.t("models.meta.provider_empty_response", "Empty response"),
            "models.meta.provider_request_failed": self._i18n.t("models.meta.provider_request_failed", "Request failed"),
            "models.setup.title": self._i18n.t("models.setup.title", "Model setup required"),
            "models.setup.intro": self._i18n.t(
                "models.setup.intro",
                "This provider is ready, but it needs a local model before it can generate LLM output.",
            ),
            "models.setup.choices": self._i18n.t(
                "models.setup.choices",
                "Choose one of the setup paths below:",
            ),
            "models.setup.option_catalog": self._i18n.t(
                "models.setup.option_catalog",
                "1. Add a model from the catalog below, then download it.",
            ),
            "models.setup.option_custom": self._i18n.t(
                "models.setup.option_custom",
                "2. Add your own model entry or direct model-file URL if the provider supports it.",
            ),
            "models.setup.option_file": self._i18n.t(
                "models.setup.option_file",
                "3. Use a local model file from disk if the provider supports direct file selection.",
            ),
            "models.setup.help_title": self._i18n.t(
                "models.setup.help_title",
                "Plugin setup notes:",
            ),
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._title = QLabel(_tr_map(self._labels, "models.title", "Models"))
        self._title.setObjectName("panelTitle")
        layout.addWidget(self._title)
        self._selection_help = QLabel(_tr_map(
            self._labels,
            "models.help.selection",
            "All available models appear in stage settings. Add or download models here to use them in a stage.",
        ))
        self._selection_help.setObjectName("pipelineMetaLabel")
        self._selection_help.setWordWrap(True)
        layout.addWidget(self._selection_help)

        self._setup_card = QFrame()
        self._setup_card.setObjectName("modelSetupCard")
        self._setup_card.setFrameShape(QFrame.StyledPanel)
        self._setup_card.setVisible(False)
        setup_layout = QVBoxLayout(self._setup_card)
        setup_layout.setContentsMargins(12, 10, 12, 10)
        setup_layout.setSpacing(6)
        self._setup_title = QLabel(_tr_map(self._labels, "models.setup.title", "Model setup required"))
        self._setup_title.setObjectName("listTileTitle")
        setup_layout.addWidget(self._setup_title)
        self._setup_body = QLabel("")
        self._setup_body.setObjectName("listTileMeta")
        self._setup_body.setWordWrap(True)
        self._setup_body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        setup_layout.addWidget(self._setup_body)
        setup_actions = QHBoxLayout()
        setup_actions.setContentsMargins(0, 0, 0, 0)
        setup_actions.setSpacing(8)
        self._setup_action_btn = QPushButton("")
        self._setup_action_btn.setVisible(False)
        self._setup_action_btn.clicked.connect(lambda *_a: self._run_setup_primary_action())
        setup_actions.addWidget(self._setup_action_btn, 0)
        self._setup_link_btn = QPushButton("")
        self._setup_link_btn.setVisible(False)
        self._setup_link_btn.clicked.connect(lambda *_a: self._open_setup_link())
        setup_actions.addWidget(self._setup_link_btn, 0)
        setup_actions.addStretch(1)
        setup_layout.addLayout(setup_actions)
        layout.addWidget(self._setup_card)

        self._toolbar = QWidget()
        bar = QHBoxLayout(self._toolbar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        self._available_label = QLabel(_tr_map(self._labels, "models.label.available", "Available models"))
        self._available_label.setObjectName("pipelineMetaLabel")
        bar.addWidget(self._available_label, 0)

        self._available_models = QComboBox()
        self._available_models.setMinimumWidth(260)
        self._available_models.setPlaceholderText(_tr_map(self._labels, "models.placeholder.available", "Select model"))
        bar.addWidget(self._available_models, 1)

        self._add_selected_btn = QPushButton(_tr_map(self._labels, "models.button.add_selected", "Add selected"))
        self._add_selected_btn.clicked.connect(lambda *_a: self._add_selected_model())
        bar.addWidget(self._add_selected_btn, 0)

        self._show_custom_btn = QPushButton(_tr_map(self._labels, "models.button.add_custom_toggle", "Add custom model"))
        self._show_custom_btn.clicked.connect(lambda *_a: self._toggle_custom_row())
        bar.addWidget(self._show_custom_btn, 0)

        self._retest_failed_btn = QPushButton(_tr_map(self._labels, "models.button.retest_failed", "Retest failed"))
        self._retest_failed_btn.clicked.connect(lambda *_a: self._retest_failed_models())
        self._retest_failed_btn.setVisible(False)
        bar.addWidget(self._retest_failed_btn, 0)

        layout.addWidget(self._toolbar)

        self._custom_row = QWidget()
        custom_layout = QHBoxLayout(self._custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)
        self._custom_model = QLineEdit()
        self._custom_model.setPlaceholderText(
            _tr_map(self._labels, "models.placeholder.custom", "Model ID / repo / tag (optional if URL is provided)")
        )
        custom_layout.addWidget(self._custom_model, 1)
        self._custom_url = QLineEdit()
        self._custom_url.setPlaceholderText(
            _tr_map(self._labels, "models.placeholder.custom_url", "Direct model file URL (optional if model ID is provided)")
        )
        custom_layout.addWidget(self._custom_url, 1)
        self._custom_btn = QPushButton(_tr_map(self._labels, "models.button.add_custom", "Add custom"))
        self._custom_btn.clicked.connect(lambda *_a: self._add_custom_model())
        custom_layout.addWidget(self._custom_btn, 0)
        self._pick_local_btn = QPushButton(_tr_map(self._labels, "models.button.pick_local_file", "Use local GGUF"))
        self._pick_local_btn.clicked.connect(lambda *_a: self._pick_local_model_file())
        custom_layout.addWidget(self._pick_local_btn, 0)
        self._custom_row.setVisible(False)
        layout.addWidget(self._custom_row)
        self._custom_help = QLabel(_tr_map(
            self._labels,
            "models.help.custom",
            "Fill model ID/tag, direct URL, or both. URL-only is supported and will use the file name as the model ID.",
        ))
        self._custom_help.setObjectName("pipelineMetaLabel")
        self._custom_help.setWordWrap(True)
        self._custom_help.setVisible(False)
        layout.addWidget(self._custom_help)

        self._note = QLabel("")
        self._note.setObjectName("pipelineMetaLabel")
        self._note.setWordWrap(True)
        self._note.setVisible(False)
        layout.addWidget(self._note)

        self._cards = QWidget()
        self._cards_layout = QVBoxLayout(self._cards)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        layout.addWidget(self._cards)
        self._setup_primary_action: str = ""
        self._setup_link_url: str = ""

    def set_advanced_mode(self, enabled: bool) -> None:
        self._advanced_mode = bool(enabled)
        self._toolbar.setVisible(self._advanced_mode and bool(self._plugin_id))
        allow_custom_inputs = self._allow_custom_inputs(self._plugin_id)
        always_show_custom = self._always_show_custom_inputs(self._plugin_id)
        self._custom_row.setVisible(
            self._advanced_mode
            and allow_custom_inputs
            and (always_show_custom or self._custom_row.isVisible())
        )
        self._custom_help.setVisible(
            self._advanced_mode
            and allow_custom_inputs
            and (always_show_custom or self._custom_help.isVisible())
        )
        if self._plugin_id:
            self._render_current_plugin(sync_inventory=False, refresh_available=False)

    def set_plugin(self, plugin_id: str) -> None:
        if not self._ui_alive():
            return
        self._plugin_id = str(plugin_id or "").strip()
        self._note.setVisible(False)
        if self._job_states and not self._job_poll_timer.isActive():
            self._job_poll_timer.start()
        self._configure_custom_inputs(self._plugin_id)
        self._render_current_plugin(sync_inventory=True, refresh_available=True)

    def _render_current_plugin(self, *, sync_inventory: bool, refresh_available: bool) -> None:
        restore_scroll = self._capture_scroll_state()
        self._clear_cards()
        if sync_inventory:
            self._sync_local_file_inventory(self._plugin_id)
        if refresh_available:
            self._refresh_available_models(self._plugin_id)

        if not self._plugin_id:
            self._toolbar.setVisible(False)
            self._show_custom_btn.setVisible(False)
            self._custom_row.setVisible(False)
            self._custom_help.setVisible(False)
            self._setup_card.setVisible(False)
            self._cards_layout.addWidget(QLabel(_tr_map(self._labels, "models.empty.none", "No models configured.")))
            self._restore_scroll_state(restore_scroll)
            return

        starter_mode = self._uses_starter_add_flow(self._plugin_id)
        self._available_label.setText(
            _tr_map(
                self._labels,
                "models.label.starter" if starter_mode else "models.label.available",
                "Starter models" if starter_mode else "Available models",
            )
        )
        self._add_selected_btn.setText(
            _tr_map(
                self._labels,
                "models.button.add_selected_simple" if starter_mode else "models.button.add_selected",
                "Add" if starter_mode else "Add selected",
            )
        )
        list_action_id = self._list_action_id(self._plugin_id)
        show_selector = self._show_available_selector(self._plugin_id)
        show_custom_toggle = self._advanced_mode and self._supports_any_custom_input(self._plugin_id)
        self._toolbar.setVisible(
            self._advanced_mode
            and self._plugin_id != "llm.ollama"
            and (show_selector or show_custom_toggle)
        )
        self._available_label.setVisible(show_selector)
        self._available_models.setVisible(show_selector)
        self._add_selected_btn.setVisible(show_selector)
        self._retest_failed_btn.setVisible(self._advanced_mode and self._has_action(self._plugin_id, "retest_failed_models"))
        if not self._allow_custom_inputs(self._plugin_id):
            self._show_custom_btn.setVisible(False)
            self._custom_row.setVisible(False)
            self._custom_help.setVisible(False)
        elif self._always_show_custom_inputs(self._plugin_id):
            self._show_custom_btn.setVisible(False)
            self._custom_row.setVisible(self._advanced_mode)
            self._custom_help.setVisible(self._advanced_mode)

        entries = self._build_entries(self._plugin_id)
        self._update_setup_card(self._plugin_id)
        if list_action_id and self._plugin_id not in self._catalog_loaded_once:
            self._catalog_loaded_once.add(self._plugin_id)
            if (self._advanced_mode or self._plugin_id == "llm.ollama") and not self._action_thread:
                self._run_action(list_action_id, {})
        if not entries and list_action_id and not (self._plugin_id == "llm.ollama" and self._setup_card.isVisible()):
            self._cards_layout.addWidget(QLabel(_tr_map(self._labels, "models.empty.loading", "Loading model catalog...")))
            self._restore_scroll_state(restore_scroll)
            return
        if not entries:
            self._cards_layout.addWidget(QLabel(_tr_map(self._labels, "models.empty.none", "No models configured.")))
            self._restore_scroll_state(restore_scroll)
            return

        for entry in entries:
            card = ModelCard(
                entry,
                labels=self._labels,
                on_toggle=(lambda enabled, mid=entry.model_id: self._toggle_model(mid, enabled))
                if entry.can_toggle
                else None,
                on_primary_action=(
                    lambda mid=entry.model_id: self._run_primary_model_action(mid)
                )
                if entry.primary_action_label
                else None,
                on_download=(lambda mid=entry.model_id: self._pull_model(mid)) if entry.can_download else None,
                on_cancel_download=(
                    lambda mid=entry.model_id: self._cancel_download(mid)
                )
                if entry.can_cancel_download
                else None,
                on_remove=(
                    lambda mid=entry.model_id, q=entry.quant, fn=entry.file_name: self._remove_model(
                        mid,
                        quant=q,
                        file_name=fn,
                    )
                )
                if entry.can_remove
                else None,
            )
            self._cards_layout.addWidget(card)
        self._restore_scroll_state(restore_scroll)

    def _plugin_descriptor(self, plugin_id: str):
        catalog = self._catalog_service.load().catalog
        return catalog.plugin_by_id(str(plugin_id or "").strip())

    def _local_model_file_index(
        self,
        plugin_id: str,
        *,
        settings: dict,
        model_info: dict,
    ) -> dict[str, dict[str, str]]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return {}
        index: dict[str, dict[str, str]] = {}

        def _add(model_id: object, file_name: object, product_name: object) -> None:
            mid = str(model_id or "").strip()
            file_key = str(file_name or "").strip().lower()
            if not mid or not file_key or file_key in index:
                return
            label = str(product_name or "").strip() or mid
            index[file_key] = {"model_id": mid, "product_name": label}

        if isinstance(model_info, dict):
            for model_id, meta in model_info.items():
                if not isinstance(meta, dict):
                    continue
                _add(model_id, meta.get("file"), meta.get("model_name") or meta.get("product_name"))

        rows = settings.get("models") if isinstance(settings, dict) else None
        if isinstance(rows, list):
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                _add(
                    entry.get("model_id") or entry.get("id"),
                    entry.get("file") or entry.get("filename"),
                    entry.get("product_name") or entry.get("name") or entry.get("label"),
                )
        return index

    def _update_setup_card(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        self._setup_primary_action = ""
        self._setup_link_url = ""
        self._setup_action_btn.setVisible(False)
        self._setup_link_btn.setVisible(False)
        if pid == "llm.ollama":
            self._setup_title.setText("Ollama runtime")
            ollama_path = shutil.which("ollama")
            settings = self._settings.get_settings(pid, include_secrets=False)
            rows = self._ollama_confirmed_model_rows(settings)
            auto_start = bool(settings.get("auto_start_server", True)) if isinstance(settings, dict) else True
            if not ollama_path:
                self._setup_body.setText(
                    "Ollama is not installed.\n\n"
                    "Install Ollama from https://ollama.com/download, then return to Settings.\n"
                    "After installation, pull at least one model in Ollama and it will appear here automatically."
                )
                self._setup_link_url = _OLLAMA_DOWNLOAD_URL
                self._setup_link_btn.setText("Open installation page")
                self._setup_link_btn.setVisible(True)
                self._setup_card.setVisible(True)
                return
            if not rows:
                self._setup_body.setText(
                    "Ollama is installed, but no models are visible yet.\n\n"
                    "The app shows only models returned by the local Ollama server API.\n"
                    f"Auto-start server: {'On' if auto_start else 'Off'}.\n"
                    "If the list is empty, start Ollama and pull a model in Ollama itself.\n"
                    "Examples: `ollama pull qwen2.5`, `ollama pull llama3.2`, `ollama pull gemma2`.\n"
                    "As soon as the server returns models, they appear here automatically."
                )
                self._setup_primary_action = "start_server"
                self._setup_action_btn.setText("Start Ollama")
                self._setup_action_btn.setVisible(self._has_action(pid, "start_server"))
                self._setup_link_url = _OLLAMA_INSTALL_GUIDE_URL
                self._setup_link_btn.setText("Open model library")
                self._setup_link_btn.setVisible(True)
                self._setup_card.setVisible(True)
                return
            self._setup_card.setVisible(False)
            return
        if not self._allow_custom_inputs(pid):
            self._setup_card.setVisible(False)
            return
        if not pid or not self._supports_local_file_models(pid):
            self._setup_card.setVisible(False)
            return

        settings = self._settings.get_settings(pid, include_secrets=False)
        if self._has_ready_local_model(pid, settings):
            self._setup_card.setVisible(False)
            return

        plugin = self._plugin_descriptor(pid)
        description = str(getattr(plugin, "description", "") or "").strip() if plugin else ""
        highlights = str(getattr(plugin, "highlights", "") or "").strip() if plugin else ""
        howto = list(getattr(plugin, "howto", []) or []) if plugin else []
        self._setup_body.setText(
            _compose_setup_message(
                self._labels,
                description=description,
                highlights=highlights,
                howto=howto,
            )
        )
        self._setup_card.setVisible(True)

    def _allow_custom_inputs(self, plugin_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        if pid == "llm.ollama":
            return False
        models_caps = self._models_caps(pid)
        if "allow_custom_inputs" in models_caps:
            return _boolish(models_caps.get("allow_custom_inputs"))
        ui_caps = models_caps.get("ui")
        if isinstance(ui_caps, dict) and "allow_custom_inputs" in ui_caps:
            return _boolish(ui_caps.get("allow_custom_inputs"))
        return True

    @staticmethod
    def _always_show_custom_inputs(plugin_id: str) -> bool:
        return str(plugin_id or "").strip() == "llm.llama_cli"

    def _show_available_selector(self, plugin_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        if pid in {"llm.llama_cli", "llm.ollama"}:
            return False
        models_caps = self._models_caps(pid)
        if "show_available_selector" in models_caps:
            return _boolish(models_caps.get("show_available_selector"))
        ui_caps = models_caps.get("ui")
        if isinstance(ui_caps, dict) and "show_available_selector" in ui_caps:
            return _boolish(ui_caps.get("show_available_selector"))
        return True

    def _supports_any_custom_input(self, plugin_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        if not pid:
            return False
        if not self._allow_custom_inputs(pid):
            return False
        return bool(pid) or self._supports_custom_download_url(pid) or self._supports_local_file_models(pid)

    def _run_setup_primary_action(self) -> None:
        pid = str(self._plugin_id or "").strip()
        action_id = str(self._setup_primary_action or "").strip()
        if not pid or not action_id or self._action_thread:
            return
        self._run_action(action_id, {})

    def _open_setup_link(self) -> None:
        url = str(self._setup_link_url or "").strip()
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

    def _has_ready_local_model(self, plugin_id: str, settings: dict) -> bool:
        raw_models = settings.get("models") if isinstance(settings, dict) else None
        rows: list[dict] = [entry for entry in raw_models if isinstance(entry, dict)] if isinstance(raw_models, list) else []
        if not rows:
            rows = list(self._models.load_models_config(plugin_id) or [])
        for entry in rows:
            installed = entry.get("installed")
            if isinstance(installed, bool) and installed:
                return True
            status = str(entry.get("status", "") or "").strip().lower()
            if status in {"installed", "enabled", "ready"}:
                return True
        selected_model_path = str(settings.get("model_path", "") or "").strip()
        if selected_model_path:
            path = Path(selected_model_path).expanduser()
            if not path.is_absolute():
                path = (self._app_root / path).resolve()
            if path.exists() and path.is_file():
                return True
        root = self._model_root(plugin_id, settings)
        if not root or not root.exists():
            return False
        for entry in rows:
            file_name = str(entry.get("file", "") or entry.get("filename", "")).strip()
            if file_name and (root / file_name).exists():
                return True
        patterns = self._local_file_patterns(plugin_id)
        try:
            for pattern in patterns:
                if any(root.glob(pattern)):
                    return True
            return False
        except OSError as exc:
            _LOG.warning("local_model_glob_failed plugin_id=%s root=%s error=%s", plugin_id, root, exc)
            return False

    def _is_local_model_available(self, plugin_id: str, settings: dict, entry: dict) -> bool:
        installed = entry.get("installed")
        if isinstance(installed, bool):
            return installed
        status = str(entry.get("status", "") or "").strip().lower()
        if status in {"installed", "enabled", "ready"}:
            return True
        file_name = str(entry.get("file", "") or entry.get("filename", "")).strip()
        if file_name:
            return self._file_installed(plugin_id, settings, file_name)
        model_path = str(entry.get("model_path", "") or entry.get("path", "")).strip()
        if model_path:
            candidate = Path(model_path).expanduser()
            if not candidate.is_absolute():
                candidate = (self._app_root / candidate).resolve()
            return candidate.exists() and candidate.is_file()
        return False

    def _local_file_patterns(self, plugin_id: str) -> list[str]:
        caps = self._local_files_caps(plugin_id)
        if not caps:
            return ["*.gguf"]
        raw_glob = str(caps.get("glob", "") or "").strip()
        raw_globs = caps.get("globs")
        patterns: list[str] = []
        if raw_glob:
            patterns.append(raw_glob)
        if isinstance(raw_globs, list):
            patterns.extend(str(item or "").strip() for item in raw_globs if str(item or "").strip())
        unique: list[str] = []
        seen: set[str] = set()
        for pattern in patterns:
            if pattern in seen:
                continue
            seen.add(pattern)
            unique.append(pattern)
        return unique or ["*.gguf"]

    def _clear_cards(self) -> None:
        if not self._ui_alive():
            return
        for i in reversed(range(self._cards_layout.count())):
            item = self._cards_layout.takeAt(i)
            if item and item.widget():
                item.widget().setParent(None)

    def _toggle_custom_row(self) -> None:
        if not self._advanced_mode or not self._show_custom_btn.isVisible():
            return
        self._custom_row.setVisible(not self._custom_row.isVisible())
        self._custom_help.setVisible(self._custom_row.isVisible())
        if self._custom_row.isVisible():
            if self._custom_model.isVisible():
                self._custom_model.setFocus()
            elif self._custom_url.isVisible():
                self._custom_url.setFocus()

    def _emit_models_changed(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if pid:
            self.modelsChanged.emit(pid)

    def _available_candidates(self, plugin_id: str) -> list[tuple[str, str]]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return []
        options: dict[str, str] = {}
        plugin = self._catalog_service.load().catalog.plugin_by_id(pid)
        model_info = plugin.model_info if plugin and isinstance(plugin.model_info, dict) else {}
        for model_id, meta in model_info.items():
            mid = str(model_id or "").strip()
            if not mid:
                continue
            if _is_gated_model(meta if isinstance(meta, dict) else {}, mid):
                continue
            name = str(meta.get("model_name", "") if isinstance(meta, dict) else "").strip()
            options[mid] = name or mid
        for entry in self._models.load_models_config(pid):
            mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if not mid:
                continue
            if _is_gated_model(entry if isinstance(entry, dict) else {}, mid):
                continue
            label = str(entry.get("product_name", "") or entry.get("name", "") or "").strip() or mid
            options[mid] = options.get(mid) or label
        settings = self._settings.get_settings(pid, include_secrets=False)
        raw = settings.get("models") if isinstance(settings, dict) else None
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
                if not mid:
                    continue
                if _is_gated_model(entry, mid):
                    continue
                label = str(entry.get("product_name", "") or entry.get("name", "") or "").strip() or mid
                options[mid] = options.get(mid) or label
        return sorted([(mid, label or mid) for mid, label in options.items()], key=lambda pair: (pair[1], pair[0]))

    def _is_curated_model(self, plugin_id: str, model_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        mid = str(model_id or "").strip()
        if not pid or not mid:
            return False
        plugin = self._catalog_service.load().catalog.plugin_by_id(pid)
        model_info = plugin.model_info if plugin and isinstance(plugin.model_info, dict) else {}
        return mid in model_info

    def _curated_model_entry(self, plugin_id: str, model_id: str) -> dict:
        pid = str(plugin_id or "").strip()
        mid = str(model_id or "").strip()
        if not pid or not mid:
            return {}
        plugin = self._plugin_descriptor(pid)
        model_info = plugin.model_info if plugin and isinstance(plugin.model_info, dict) else {}
        meta = model_info.get(mid) if isinstance(model_info, dict) else None
        if not isinstance(meta, dict):
            return {}
        seed = {
            "model_id": mid,
            "product_name": str(meta.get("model_name", "") or mid).strip() or mid,
        }
        return _apply_curated_model_metadata(seed, meta, mid)

    def _refresh_available_models(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        self._available_models.blockSignals(True)
        self._available_models.clear()
        self._available_models.addItem(_tr_map(self._labels, "models.placeholder.available", "Select model"), "")
        for model_id, label in self._available_candidates(pid):
            self._available_models.addItem(f"{label} ({model_id})" if label != model_id else model_id, model_id)
        self._available_models.setCurrentIndex(0)
        self._available_models.blockSignals(False)

    def _models_caps(self, plugin_id: str) -> dict:
        catalog_service = getattr(self, "_catalog_service", None)
        if catalog_service is None:
            return {}
        catalog = catalog_service.load().catalog
        plugin = catalog.plugin_by_id(str(plugin_id or "").strip())
        caps = plugin.capabilities if plugin else {}
        models_caps = caps.get("models") if isinstance(caps, dict) else None
        return dict(models_caps) if isinstance(models_caps, dict) else {}

    def _health_caps(self, plugin_id: str) -> dict:
        catalog_service = getattr(self, "_catalog_service", None)
        if catalog_service is None:
            return {}
        catalog = catalog_service.load().catalog
        plugin = catalog.plugin_by_id(str(plugin_id or "").strip())
        caps = plugin.capabilities if plugin and isinstance(plugin.capabilities, dict) else {}
        health_caps = caps.get("health") if isinstance(caps, dict) else None
        return dict(health_caps) if isinstance(health_caps, dict) else {}

    def _managed_actions_for(self, plugin_id: str) -> dict[str, str] | None:
        models_caps = self._models_caps(plugin_id)
        managed = models_caps.get("managed_actions")
        if not isinstance(managed, dict):
            return None
        normalized: dict[str, str] = {}
        for key in ("list", "pull", "remove"):
            val = str(managed.get(key, "") or "").strip()
            if val and self._has_action(plugin_id, val):
                normalized[key] = val
        return normalized or None

    def _list_action_id(self, plugin_id: str) -> str:
        if self._uses_starter_add_flow(plugin_id):
            return ""
        managed = self._managed_actions_for(plugin_id) or {}
        action_id = str(managed.get("list", "") or "").strip()
        if action_id:
            return action_id
        if self._has_action(plugin_id, "list_models"):
            return "list_models"
        return ""

    @staticmethod
    def _uses_starter_add_flow(plugin_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        return pid in {"llm.openrouter", "llm.llama_cli"}

    def _local_files_caps(self, plugin_id: str) -> dict | None:
        models_caps = self._models_caps(plugin_id)
        local = models_caps.get("local_files")
        return dict(local) if isinstance(local, dict) else None

    def _supports_local_file_models(self, plugin_id: str) -> bool:
        return self._local_files_caps(plugin_id) is not None

    def _supports_custom_download_url(self, plugin_id: str) -> bool:
        return self._supports_local_file_models(plugin_id)

    def _custom_help_text(self, plugin_id: str) -> str:
        if self._supports_custom_download_url(plugin_id):
            return _tr_map(
                self._labels,
                "models.help.custom",
                "Fill model ID/tag, direct URL, or both. URL-only is supported and will use the file name as the model ID.",
            )
        return _tr_map(
            self._labels,
            "models.help.custom_id_only",
            "Enter the exact model ID or tag used by this provider.",
        )

    def _configure_custom_inputs(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        allow_custom = self._allow_custom_inputs(pid)
        supports_model_id = bool(pid) and allow_custom
        supports_url = self._supports_custom_download_url(pid)
        supports_local_file = self._supports_local_file_models(pid)
        if not allow_custom:
            supports_url = False
            supports_local_file = False
        supports_any_custom = bool(allow_custom and (supports_model_id or supports_url))
        self._show_custom_btn.setVisible(self._advanced_mode and supports_any_custom)
        if not supports_any_custom or not self._advanced_mode:
            self._custom_row.setVisible(False)
            self._custom_help.setVisible(False)
        self._custom_model.setVisible(supports_model_id)
        self._custom_url.setVisible(supports_url)
        self._pick_local_btn.setVisible(supports_local_file)
        if supports_url:
            self._custom_model.setPlaceholderText(
                _tr_map(self._labels, "models.placeholder.custom", "Model ID / repo / tag (optional if URL is provided)")
            )
            self._custom_url.setPlaceholderText(
                _tr_map(self._labels, "models.placeholder.custom_url", "Direct model file URL (optional if model ID is provided)")
            )
        else:
            self._custom_model.setPlaceholderText(
                _tr_map(self._labels, "models.placeholder.custom_id_only", "Model ID / tag")
            )
            self._custom_url.setPlaceholderText("")
        self._custom_help.setText(self._custom_help_text(pid))

    def _is_local_models_plugin(self, plugin_id: str) -> bool:
        models_caps = self._models_caps(plugin_id)
        if isinstance(models_caps.get("local_files"), dict):
            return True
        return str(models_caps.get("storage", "") or "").strip().lower() == "local"

    def _missing_required_health_settings(self, plugin_id: str, settings: dict | object) -> bool:
        if not isinstance(settings, dict):
            settings = {}
        health_caps = self._health_caps(plugin_id)
        required = health_caps.get("required_settings")
        if not isinstance(required, list):
            return False
        for group in required:
            if not isinstance(group, dict):
                continue
            keys = group.get("keys")
            if not isinstance(keys, list):
                continue
            if not any(str(settings.get(str(key or "").strip(), "") or "").strip() for key in keys):
                return True
        return False

    def _display_cloud_availability(self, plugin_id: str, settings: dict | object, meta: dict) -> str:
        availability = self._cloud_availability_status(meta)
        if availability != "unknown":
            return availability
        if self._missing_required_health_settings(plugin_id, settings):
            return "needs_setup"
        managed = self._managed_actions_for(plugin_id) or {}
        has_probe = bool(managed.get("list")) or self._has_action(plugin_id, "test_connection") or self._has_action(
            plugin_id, "test_model"
        )
        if has_probe:
            return "unknown"
        return "ready"

    def _model_root(self, plugin_id: str, settings: dict) -> Path | None:
        caps = self._local_files_caps(plugin_id)
        if not caps:
            return None
        root_setting = str(caps.get("root_setting", "") or "").strip()
        default_root = str(caps.get("default_root", "") or "").strip()
        raw_root = str(settings.get(root_setting, "") or "").strip() if root_setting else ""
        chosen = raw_root or default_root
        if not chosen:
            return None
        path = Path(chosen).expanduser()
        return path if path.is_absolute() else (self._app_root / path).resolve()

    def _relative_model_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self._app_root)).replace("\\", "/")
        except (OSError, RuntimeError, ValueError):
            try:
                return str(path.resolve())
            except (OSError, RuntimeError, ValueError):
                return str(path)

    def _sync_local_file_inventory(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid or not self._supports_local_file_models(pid):
            return
        settings = self._settings.get_settings(pid, include_secrets=False)
        if not isinstance(settings, dict):
            settings = {}
        plugin = self._plugin_descriptor(pid)
        model_info = plugin.model_info if plugin and isinstance(plugin.model_info, dict) else {}
        curated_ids = {str(model_id or "").strip() for model_id in model_info.keys() if str(model_id or "").strip()}
        file_index = self._local_model_file_index(pid, settings=settings, model_info=model_info)
        root = self._model_root(pid, settings)
        raw_models = settings.get("models")
        rows: list[dict] = [dict(entry) for entry in raw_models if isinstance(entry, dict)] if isinstance(raw_models, list) else []
        patterns = self._local_file_patterns(pid)

        files_by_name: dict[str, Path] = {}
        if root and root.exists() and root.is_dir():
            try:
                for pattern in patterns:
                    for path in sorted(root.glob(pattern)):
                        if path.is_file():
                            files_by_name[path.name] = path
            except OSError as exc:
                _LOG.warning("sync_local_file_inventory_glob_failed plugin_id=%s root=%s error=%s", pid, root, exc)
                files_by_name = {}

        updated: list[dict] = []
        matched_files: set[str] = set()
        for entry in rows:
            row = dict(entry)
            model_id = str(row.get("model_id", "") or row.get("id", "")).strip()
            file_name = str(row.get("file", "") or row.get("filename", "")).strip()
            model_path = str(row.get("model_path", "") or row.get("path", "")).strip()
            catalog_source = str(row.get("catalog_source", "") or "").strip().lower()
            user_added = bool(row.get("user_added", False))
            is_filesystem_only = not model_id and (catalog_source == "filesystem" or model_path or file_name)

            if model_id and not user_added and curated_ids and model_id not in curated_ids and catalog_source == "recommended":
                continue
            if model_id and model_id in curated_ids:
                curated = model_info.get(model_id)
                if isinstance(curated, dict):
                    row = _apply_curated_model_metadata(row, curated, model_id)
                    file_name = str(row.get("file", "") or row.get("filename", "")).strip()
                    model_path = str(row.get("model_path", "") or row.get("path", "")).strip()

            installed = row.get("installed")
            path_obj: Path | None = None
            if file_name and file_name in files_by_name:
                path_obj = files_by_name[file_name]
                matched_files.add(file_name)
            elif model_path:
                candidate = Path(model_path).expanduser()
                if not candidate.is_absolute():
                    candidate = (self._app_root / candidate).resolve()
                if candidate.exists() and candidate.is_file():
                    path_obj = candidate
                    matched_files.add(candidate.name)
                    if not file_name:
                        file_name = candidate.name
                        row["file"] = file_name

            is_installed = bool(path_obj is not None)
            if installed is not is_installed:
                row["installed"] = is_installed
            row["status"] = "installed" if is_installed else ""

            if path_obj and not model_path:
                row["model_path"] = self._relative_model_path(path_obj)
            if file_name:
                matched = file_index.get(file_name.lower(), {})
                if matched:
                    if not str(row.get("model_id", "") or row.get("id", "")).strip():
                        row["model_id"] = str(matched.get("model_id", "") or "").strip()
                    if not str(row.get("product_name", "") or "").strip():
                        row["product_name"] = str(matched.get("product_name", "") or "").strip() or file_name
            if path_obj and not str(row.get("product_name", "") or "").strip():
                row["product_name"] = path_obj.name

            if is_filesystem_only and not is_installed:
                continue
            updated.append(row)

        for file_name, path in sorted(files_by_name.items()):
            if file_name in matched_files:
                continue
            matched = file_index.get(file_name.lower(), {})
            model_id = str(matched.get("model_id", "") or "").strip()
            product_name = str(matched.get("product_name", "") or "").strip() or path.name
            updated.append(
                {
                    "model_id": model_id,
                    "model_path": self._relative_model_path(path),
                    "product_name": product_name,
                    "file": file_name,
                    "installed": True,
                    "status": "installed",
                    "catalog_source": "filesystem",
                }
            )

        if updated == rows:
            return
        merged_settings = dict(settings)
        merged_settings["models"] = updated
        preserve = [k for k in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(k)]
        self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
        self._emit_models_changed(pid)

    def _file_installed(self, plugin_id: str, settings: dict, file_name: str) -> bool:
        if not file_name:
            return False
        root = self._model_root(plugin_id, settings)
        if not root:
            return False
        return (root / file_name).exists()

    def _file_size(self, plugin_id: str, settings: dict, file_name: str) -> int:
        if not file_name:
            return 0
        root = self._model_root(plugin_id, settings)
        if not root:
            return 0
        path = root / file_name
        if not path.exists():
            return 0
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(value or 0)
        if size <= 0:
            return ""
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while size >= 1024 and idx < len(units) - 1:
            size /= 1024
            idx += 1
        if idx == 0:
            return f"{int(size)} {units[idx]}"
        return f"{size:.1f} {units[idx]}"

    def _status_for(self, enabled: bool | None, installed: bool | None) -> tuple[str, str, str]:
        _ = enabled
        if installed is True:
            return _tr_map(self._labels, "models.status.ready", "Ready"), "#DCFCE7", "#166534"
        if installed is False:
            return _tr_map(self._labels, "models.status.needs_setup", "Needs setup"), "#FEF3C7", "#92400E"
        return _tr_map(self._labels, "models.status.unknown", "Unknown"), "#E5E7EB", "#374151"

    def _cloud_availability_status(self, meta: dict) -> str:
        availability = str(meta.get("availability_status", "") or "").strip().lower()
        if availability in {"ready", "needs_setup", "unknown", "limited", "unavailable"}:
            return availability
        failure_code = str(meta.get("failure_code", "") or "").strip().lower()
        selectable = meta.get("selectable")
        cooldown_until = int(meta.get("cooldown_until", 0) or 0)
        status_raw = str(meta.get("status", "") or "").strip().lower()
        now_ts = int(time.time())
        if cooldown_until > now_ts or failure_code == "rate_limited" or status_raw == "rate_limited":
            return "limited"
        if failure_code in {"provider_blocked", "model_not_found", "not_available", "auth_error", "request_failed"}:
            return "unavailable"
        if status_raw in {"provider_blocked", "model_not_found", "not_available", "auth_error", "request_failed"}:
            return "unavailable"
        if selectable is True or status_raw in {"ok", "ready"}:
            return "ready"
        return "unknown"

    @staticmethod
    def _cloud_availability_from_failure_code(failure_code: str) -> str:
        failure = str(failure_code or "").strip().lower()
        if failure in {"rate_limited"}:
            return "limited"
        if failure in {
            "provider_blocked",
            "model_not_found",
            "not_available",
            "auth_error",
            "bad_request",
            "empty_response",
            "request_failed",
            "timeout",
            "transport_error",
            "network_error",
        }:
            return "unavailable"
        return "unknown"

    def _cloud_status_for(self, meta: dict) -> tuple[str, str, str]:
        availability = self._cloud_availability_status(meta)
        mapping = {
            "ready": (_tr_map(self._labels, "models.status.ready", "Ready"), "#DCFCE7", "#166534"),
            "needs_setup": (_tr_map(self._labels, "models.status.needs_setup", "Needs setup"), "#FEF3C7", "#92400E"),
            "unknown": (_tr_map(self._labels, "models.status.unknown", "Unknown"), "#E5E7EB", "#374151"),
            "limited": (_tr_map(self._labels, "models.status.limited", "Limited"), "#FEF3C7", "#92400E"),
            "unavailable": (_tr_map(self._labels, "models.status.unavailable", "Unavailable"), "#FEE2E2", "#B91C1C"),
        }
        return mapping.get(availability, mapping["unknown"])

    @staticmethod
    def _cloud_primary_action_spec(
        *,
        status_raw: str,
        failure_code: str,
        model_id: str,
        has_test_model: bool,
        has_test_connection: bool,
    ) -> tuple[str, str, dict[str, str], str]:
        status = str(status_raw or "").strip().lower()
        failure = str(failure_code or "").strip().lower()
        mid = str(model_id or "").strip()
        if status in {"ok", "ready", "rate_limited"} or failure == "rate_limited":
            return "", "", {}, ""
        if failure == "auth_error" or status == "auth_error":
            if has_test_connection:
                return (
                    "Check availability",
                    "test_connection",
                    {},
                    "Run an availability check with the current provider credentials.",
                )
            return "", "", {}, ""
        if has_test_model and mid:
            return (
                "Check availability",
                "test_model",
                {"model_id": mid},
                "Run a live availability check for this model and update its status.",
            )
        if has_test_connection:
            return (
                "Check availability",
                "test_connection",
                {},
                "Run a provider availability check and refresh the status.",
            )
        return "", "", {}, ""

    def _cloud_primary_action_for_entry(
        self,
        *,
        plugin_id: str,
        model_id: str,
        meta: dict,
    ) -> tuple[str, str, dict[str, str], str]:
        return self._cloud_primary_action_spec(
            status_raw=str(meta.get("status", "") or ""),
            failure_code=str(meta.get("failure_code", "") or ""),
            model_id=model_id,
            has_test_model=self._has_action(plugin_id, "test_model"),
            has_test_connection=self._has_action(plugin_id, "test_connection"),
        )

    def _provider_status_label(self, value: object) -> str:
        raw = str(value or "").strip().lower()
        if not raw or raw in {"ok", "ready"}:
            return ""
        mapping = {
            "provider_blocked": _tr_map(
                self._labels,
                "models.status.blocked_for_account",
                "Blocked for this account",
            ),
            "model_not_found": _tr_map(self._labels, "models.meta.provider_model_missing", "Model not found"),
            "not_available": _tr_map(self._labels, "models.meta.provider_unavailable", "Not available"),
            "auth_error": _tr_map(self._labels, "models.status.auth_issue", "Auth issue"),
            "rate_limited": _tr_map(self._labels, "models.status.limited", "Limited"),
            "bad_request": _tr_map(self._labels, "models.meta.provider_bad_request", "Bad request"),
            "empty_response": _tr_map(self._labels, "models.meta.provider_empty_response", "Empty response"),
            "request_failed": _tr_map(self._labels, "models.meta.provider_request_failed", "Request failed"),
            "timeout": _tr_map(self._labels, "models.meta.provider_unavailable", "Not available"),
            "transport_error": _tr_map(self._labels, "models.meta.provider_unavailable", "Not available"),
            "network_error": _tr_map(self._labels, "models.meta.provider_unavailable", "Not available"),
        }
        return mapping.get(raw, raw.replace("_", " "))

    def _status_for_download(self, job: dict[str, object]) -> tuple[str, str, str]:
        state = str(job.get("status", "") or "").strip().lower()
        progress = int(job.get("progress", 0) or 0)
        if state == "queued":
            return _tr_map(self._labels, "models.status.download_queued", "Queued"), "#E0E7FF", "#3730A3"
        return (
            _tr_map(self._labels, "models.status.downloading", "Downloading {progress}%").format(progress=progress),
            "#DBEAFE",
            "#1D4ED8",
        )

    @staticmethod
    def _cloud_entry_sort_key(entry: ModelEntry) -> tuple[int, str]:
        status = str(entry.status_label or "").strip().lower()
        if "ready" in status:
            rank = 0
        elif "testing" in status:
            rank = 1
        elif "limited" in status:
            rank = 2
        elif "unknown" in status:
            rank = 3
        elif "unavailable" in status:
            rank = 4
        else:
            rank = 5
        return rank, str(entry.title or "").lower()

    @staticmethod
    def _format_timestamp(value: object) -> str:
        try:
            timestamp = int(value or 0)
        except (TypeError, ValueError):
            return ""
        if timestamp <= 0:
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))
        except (OSError, OverflowError, ValueError):
            return ""

    def _build_entries(self, plugin_id: str) -> list[ModelEntry]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return []

        catalog = self._catalog_service.load().catalog
        plugin = catalog.plugin_by_id(pid)
        model_info = plugin.model_info if plugin and isinstance(plugin.model_info, dict) else {}
        managed = self._managed_actions_for(pid) or {}
        local_mode = self._is_local_models_plugin(pid)

        settings = self._settings.get_settings(pid, include_secrets=False)
        selected_model_path = str(settings.get("model_path", "") or "").strip()
        hidden_ids_raw = settings.get("hidden_model_ids") if isinstance(settings, dict) else []
        hidden_files_raw = settings.get("hidden_model_files") if isinstance(settings, dict) else []
        hidden_ids = {
            str(item or "").strip()
            for item in (hidden_ids_raw if isinstance(hidden_ids_raw, list) else [])
            if str(item or "").strip()
        }
        hidden_files = {
            str(item or "").strip()
            for item in (hidden_files_raw if isinstance(hidden_files_raw, list) else [])
            if str(item or "").strip()
        }
        settings_models = settings.get("models") if isinstance(settings, dict) else None
        raw_models: list[dict] = [m for m in settings_models if isinstance(m, dict)] if isinstance(settings_models, list) else []
        if pid == "llm.ollama":
            raw_models = self._ollama_confirmed_model_rows(settings)
        if not raw_models:
            raw_models = list(self._models.load_models_config(pid) or [])
        if pid == "llm.ollama" and not self._ollama_runtime_ready(settings):
            raw_models = []

        by_id: dict[str, dict] = {}
        path_rows: list[dict] = []
        for entry in raw_models:
            entry_meta = dict(entry)
            entry_mid = str(entry_meta.get("model_id", "") or entry_meta.get("id", "")).strip()
            entry_file = str(entry_meta.get("file", "") or entry_meta.get("filename", "")).strip()
            entry_visible_local = local_mode and self._is_local_model_available(pid, settings, entry_meta)
            if bool(entry_meta.get("hidden", False)) and not entry_visible_local:
                continue
            mid = entry_mid
            if mid and mid in hidden_ids and not entry_visible_local:
                continue
            if mid:
                if local_mode and self._uses_starter_add_flow(pid) and not entry_visible_local:
                    active_job = self._job_state_for(pid, mid)
                    pending_action = self._pending_model_actions.get((pid, mid), "")
                    curated = mid in model_info
                    user_added = bool(entry_meta.get("user_added", False))
                    has_download_source = bool(
                        str(entry_meta.get("download_url", "") or "").strip()
                        or str(entry_meta.get("source_url", "") or "").strip()
                    )
                    if not active_job and not pending_action and not curated and not user_added and not has_download_source:
                        continue
                by_id[mid] = entry_meta
                continue
            model_path = str(entry_meta.get("model_path", "") or entry_meta.get("path", "")).strip()
            file_name = entry_file
            if file_name and file_name in hidden_files and not entry_visible_local:
                continue
            if model_path or file_name:
                path_rows.append(entry_meta)

        catalog_models: list[tuple[str, str, str]] = []
        if pid != "llm.ollama" and not self._uses_starter_add_flow(pid):
            for model_id, meta in model_info.items():
                mid = str(model_id or "").strip()
                if not mid:
                    continue
                name = str(meta.get("model_name", "") if isinstance(meta, dict) else "").strip()
                desc = str(meta.get("model_description", "") if isinstance(meta, dict) else "").strip()
                catalog_models.append((mid, name or mid, desc))

        if not catalog_models:
            for mid in sorted(by_id.keys()):
                meta = by_id[mid]
                if bool(meta.get("hidden", False)):
                    continue
                title = str(meta.get("product_name", "") or mid).strip() or mid
                catalog_models.append((mid, title, str(meta.get("description", "") or "").strip()))

        known_ids = {mid for mid, _t, _d in catalog_models}
        for mid in sorted(by_id.keys()):
            if mid in known_ids:
                continue
            meta = by_id[mid]
            title = str(meta.get("product_name", "") or mid).strip() or mid
            catalog_models.append((mid, title, str(meta.get("description", "") or "").strip()))

        entries: list[ModelEntry] = []
        if selected_model_path:
            local_path = Path(selected_model_path).expanduser()
            if not local_path.is_absolute():
                local_path = (self._app_root / local_path).resolve()
            if local_path.exists() and local_path.is_file():
                status, bg, fg = self._status_for(True, True)
                entries.append(
                    ModelEntry(
                        model_id=f"path:{local_path}",
                        title=local_path.name,
                        status_label=status,
                        status_bg=bg,
                        status_fg=fg,
                        meta_lines=[
                            _tr_map(self._labels, "models.meta.file", "File: {value}").format(value=str(local_path)),
                            _tr_map(self._labels, "models.meta.source", "Source: {value}").format(value="local file"),
                        ],
                        enabled=True,
                        can_toggle=False,
                        can_download=False,
                        can_remove=False,
                    )
                )
        for mid, title, desc in catalog_models:
            catalog_meta = model_info.get(mid, {}) if isinstance(model_info, dict) else {}
            meta = dict(catalog_meta) if isinstance(catalog_meta, dict) else {}
            if mid in by_id:
                meta.update(by_id[mid])
            if bool(meta.get("hidden", False)) and not self._is_local_model_available(pid, settings, meta):
                continue
            if mid in hidden_ids and not self._is_local_model_available(pid, settings, meta):
                continue
            enabled_raw = meta.get("enabled")
            favorite_raw = meta.get("favorite")
            enabled = bool(enabled_raw) if isinstance(enabled_raw, bool) else bool(favorite_raw)
            observed_success = bool(meta.get("observed_success")) if isinstance(
                meta.get("observed_success"), bool
            ) else (str(meta.get("last_pipeline_quality", "") or "").strip().lower() == "usable")
            file_name = str(meta.get("file", "") or meta.get("filename", "")).strip()
            quant = str(meta.get("quant", "") or "").strip()
            size_hint = str(meta.get("size_hint", "") or meta.get("size", "") or "").strip()
            source_url = str(meta.get("source_url", "") or "").strip()
            download_url = str(meta.get("download_url", "") or "").strip()
            gated = _is_gated_model(meta, mid)
            if gated:
                continue
            model_url = _preferred_model_link(meta, mid)
            tooltip = _gated_tooltip(self._labels, model_url) if gated else ""
            links_html = _gated_links_html(self._labels, model_url) if gated else _external_link_html(
                model_url,
                _tr_map(self._labels, "models.links.model_page", "Model page"),
            )
            installed = None
            if local_mode:
                installed = self._is_local_model_available(pid, settings, meta)
            active_job = self._job_state_for(pid, mid)
            pending_action = self._pending_model_actions.get((pid, mid), "")

            display_availability = self._display_cloud_availability(pid, settings, meta) if not local_mode else ""
            status, bg, fg = (
                self._status_for(enabled, installed)
                if local_mode
                else self._cloud_status_for({**meta, "availability_status": display_availability})
            )
            primary_action_label = ""
            primary_action_tooltip = ""
            if (
                not local_mode
                and (self._advanced_mode or display_availability in {"unknown", "needs_setup", "limited", "unavailable"})
            ):
                primary_action_label, _primary_action_id, _primary_payload, primary_action_tooltip = (
                    self._cloud_primary_action_for_entry(plugin_id=pid, model_id=mid, meta=meta)
                )
            lines = []
            if pending_action == "test_model":
                status = _tr_map(self._labels, "models.status.testing", "Testing...")
                bg = "#DBEAFE"
                fg = "#1D4ED8"
                primary_action_label = ""
                primary_action_tooltip = ""
                lines.append(_tr_map(self._labels, "models.meta.testing", "Model test in progress..."))
            elif pending_action and pending_action == str(managed.get("pull", "") or "").strip():
                status = _tr_map(self._labels, "models.status.downloading", "Downloading...")
                bg = "#DBEAFE"
                fg = "#1D4ED8"
                primary_action_label = ""
                primary_action_tooltip = ""
                lines.append(_tr_map(self._labels, "models.meta.download_pending", "Model download in progress..."))
            lines.append(_tr_map(self._labels, "models.meta.id", "ID: {value}").format(value=mid))
            if quant:
                lines.append(_tr_map(self._labels, "models.meta.quant", "Quant: {value}").format(value=quant))
            if size_hint:
                lines.append(_tr_map(self._labels, "models.meta.size", "Size: {value}").format(value=size_hint))
            if file_name:
                lines.append(_tr_map(self._labels, "models.meta.file", "File: {value}").format(value=file_name))
                size = self._file_size(pid, settings, file_name)
                if not size_hint:
                    lines.append(
                        _tr_map(self._labels, "models.meta.size", "Size: {value}").format(
                            value=self._format_bytes(size)
                            if size
                            else _tr_map(self._labels, "models.meta.size_na", "n/a")
                        )
                    )
            if source_url:
                lines.append(_tr_map(self._labels, "models.meta.source", "Source: {value}").format(value=source_url))
            if download_url and download_url != source_url:
                lines.append(
                    _tr_map(self._labels, "models.meta.download", "Download: {value}").format(value=download_url)
                )
            if not local_mode:
                if bool(meta.get("blocked_for_account", False)):
                    lines.append(
                        _tr_map(
                            self._labels,
                            "models.meta.blocked_for_account",
                            "Blocked for this account",
                        )
                    )
                retry_after = self._format_timestamp(meta.get("cooldown_until"))
                if retry_after:
                    lines.append(
                        _tr_map(self._labels, "models.meta.retry_after", "Retry after: {value}").format(
                            value=retry_after
                        )
                    )
                provider_status = str(meta.get("failure_code", "") or meta.get("status", "") or "").strip()
                if self._advanced_mode and provider_status and provider_status not in {"ok", "ready"}:
                    lines.append(
                        _tr_map(self._labels, "models.meta.reason", "Reason: {value}").format(
                            value=self._provider_status_label(provider_status)
                        )
                    )
                last_ok = self._format_timestamp(meta.get("last_ok_at"))
                if self._advanced_mode and last_ok:
                    lines.append(
                        _tr_map(self._labels, "models.meta.last_ok", "Last successful test: {value}").format(
                            value=last_ok
                        )
                    )
                last_checked = self._format_timestamp(meta.get("last_checked_at"))
                if self._advanced_mode and last_checked:
                    lines.append(
                        _tr_map(self._labels, "models.meta.last_checked", "Last checked: {value}").format(
                            value=last_checked
                        )
                    )
            if desc:
                lines.append(desc)
            if active_job:
                status, bg, fg = self._status_for_download(active_job)

            entry_managed = meta.get("managed")
            allow_manage = entry_managed is not False
            can_download = bool(managed.get("pull")) and allow_manage and (installed is False) and not bool(active_job)
            can_cancel_download = bool(active_job) and bool(managed.get("pull"))
            can_remove = (
                bool(managed.get("remove"))
                and allow_manage
                and not bool(active_job)
                and ((installed is True) if local_mode else True)
            )
            if not local_mode and self._uses_starter_add_flow(pid):
                can_remove = True
            if pid == "llm.ollama":
                can_download = False
                can_cancel_download = False
                can_remove = False
                primary_action_label = ""
                primary_action_tooltip = ""

            entries.append(
                ModelEntry(
                    model_id=mid,
                    title=title,
                    status_label=status,
                    status_bg=bg,
                    status_fg=fg,
                    meta_lines=lines[:6],
                    enabled=enabled,
                    can_toggle=False,
                    toggle_label="",
                    can_download=can_download,
                    can_cancel_download=can_cancel_download,
                    can_remove=can_remove,
                    observed_success=observed_success,
                    quant=quant,
                    file_name=file_name,
                    download_job_active=bool(active_job),
                    links_html=links_html,
                    gated=gated,
                    tooltip=tooltip,
                    primary_action_label=primary_action_label,
                    primary_action_tooltip=primary_action_tooltip,
                )
            )
        for meta in path_rows:
            model_path = str(meta.get("model_path", "") or meta.get("path", "")).strip()
            file_name = str(meta.get("file", "") or meta.get("filename", "")).strip()
            installed_raw = meta.get("installed")
            installed = bool(installed_raw) if isinstance(installed_raw, bool) else None
            if installed is None and file_name and local_mode:
                installed = self._file_installed(pid, settings, file_name)
            if installed is None and model_path:
                candidate = Path(model_path).expanduser()
                if not candidate.is_absolute():
                    candidate = (self._app_root / candidate).resolve()
                installed = candidate.exists() and candidate.is_file()
            status, bg, fg = self._status_for(None, installed)
            title = str(meta.get("product_name", "") or "").strip() or file_name or Path(model_path).name or model_path
            lines = []
            if model_path:
                lines.append(_tr_map(self._labels, "models.meta.file", "File: {value}").format(value=model_path))
            elif file_name:
                lines.append(_tr_map(self._labels, "models.meta.file", "File: {value}").format(value=file_name))
            if file_name:
                size = self._file_size(pid, settings, file_name)
                lines.append(
                    _tr_map(self._labels, "models.meta.size", "Size: {value}").format(
                        value=self._format_bytes(size) if size else _tr_map(self._labels, "models.meta.size_na", "n/a")
                    )
                )
            entries.append(
                ModelEntry(
                    model_id="",
                    title=title,
                    status_label=status,
                    status_bg=bg,
                    status_fg=fg,
                    meta_lines=lines[:6],
                    enabled=None,
                    can_toggle=False,
                    can_download=False,
                    can_remove=bool(managed.get("remove")) and (installed is True),
                    file_name=file_name,
                )
            )
        if not local_mode:
            entries.sort(key=self._cloud_entry_sort_key)
        return entries

    @staticmethod
    def _ollama_runtime_ready(settings: dict | object) -> bool:
        if not isinstance(settings, dict):
            return False
        meta = settings.get(_OLLAMA_RUNTIME_META_KEY)
        if not isinstance(meta, dict):
            return False
        if meta.get("ollama_installed") is not True:
            return False
        if meta.get("server_running") is not True:
            return False
        try:
            return int(meta.get("total", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    @classmethod
    def _ollama_confirmed_model_rows(cls, settings: dict | object) -> list[dict]:
        if not isinstance(settings, dict):
            return []
        if not cls._ollama_runtime_ready(settings):
            return []
        raw_models = settings.get("models")
        if not isinstance(raw_models, list):
            return []
        return [entry for entry in raw_models if isinstance(entry, dict)]

    def _toggle_model(self, model_id: str, enabled: bool) -> None:
        pid = str(self._plugin_id or "").strip()
        wanted = str(model_id or "").strip()
        if not pid or not wanted:
            return
        try:
            local_plugin = self._is_local_models_plugin(pid)
            if local_plugin:
                self._sync_local_file_inventory(pid)
            settings = self._settings.get_settings(pid, include_secrets=False)
            raw = settings.get("models") if isinstance(settings, dict) else None
            target_entry = None
            if isinstance(raw, list):
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
                    if mid == wanted:
                        target_entry = dict(entry)
                        break
            if target_entry is None and local_plugin:
                for entry in self._models.load_models_config(pid) or []:
                    if not isinstance(entry, dict):
                        continue
                    mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
                    if mid == wanted:
                        target_entry = dict(entry)
                        break
            if target_entry is None and local_plugin:
                target_entry = self._curated_model_entry(pid, wanted)
                if target_entry and self._is_local_model_available(
                    pid,
                    settings if isinstance(settings, dict) else {},
                    target_entry,
                ):
                    target_entry["installed"] = True
                    target_entry["status"] = "installed"
            if enabled and local_plugin and not self._is_local_model_available(
                pid,
                settings if isinstance(settings, dict) else {},
                target_entry or {},
            ):
                self._set_note_message(
                    _tr_map(
                        self._labels,
                        "models.note.enabled_requires_download",
                        "Only downloaded local models can be used from stage settings.",
                    )
                )
                self.set_plugin(pid)
                return
            if isinstance(raw, list) or (local_plugin and isinstance(target_entry, dict) and target_entry):
                rows = [dict(entry) for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
                updated: list[dict] = []
                found = False
                for entry in rows:
                    mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
                    if mid == wanted:
                        found = True
                        merged = dict(entry)
                        merged["enabled"] = bool(enabled)
                        merged.pop("favorite", None)
                        updated.append(merged)
                    else:
                        updated.append(dict(entry))
                if not found:
                    appended = dict(target_entry) if isinstance(target_entry, dict) else {}
                    appended["model_id"] = wanted
                    appended["enabled"] = bool(enabled)
                    appended.pop("favorite", None)
                    if not str(appended.get("availability_status", "") or "").strip():
                        appended["availability_status"] = "unknown"
                    updated.append(appended)
                merged_settings = dict(settings)
                merged_settings["models"] = updated
                preserve = [
                    k
                    for k in self._settings.get_settings(pid, include_secrets=True).keys()
                    if _is_secret_field_name(k)
                ]
                self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
                self._emit_models_changed(pid)
            else:
                self._models.update_model_enabled(pid, wanted, enabled)
                self._emit_models_changed(pid)
        except _MODEL_UI_RUNTIME_ERRORS as exc:
            logging.getLogger("aimn.ui").warning(
                "model_toggle_failed plugin_id=%s model=%s error=%s", pid, wanted, exc
            )
        self.set_plugin(pid)

    def _pull_model(self, model_id: str) -> None:
        pid = str(self._plugin_id or "").strip()
        wanted = str(model_id or "").strip()
        if not pid or not wanted:
            return
        if self._job_state_for(pid, wanted):
            return
        managed = self._managed_actions_for(pid) or {}
        action_id = str(managed.get("pull", "") or "").strip()
        if not action_id:
            return
        self._pending_model_actions[(pid, wanted)] = action_id
        self._focus_model_after_render = (pid, wanted)
        self._note.setText(
            _tr_map(self._labels, "models.note.download_started", "Download started: {value}").format(
                value=wanted
            )
        )
        self._note.setVisible(True)
        self._render_current_plugin(sync_inventory=False, refresh_available=False)
        self._run_action(action_id, {"model_id": wanted})

    def _cancel_download(self, model_id: str) -> None:
        pid = str(self._plugin_id or "").strip()
        wanted = str(model_id or "").strip()
        if not pid or not wanted:
            return
        job = self._job_state_for(pid, wanted)
        if not isinstance(job, dict):
            return
        job_id = str(job.get("job_id", "") or "").strip()
        if not job_id or not self._has_action(pid, "cancel_download"):
            return
        self._note.setText(
            _tr_map(self._labels, "models.note.download_cancelling", "Cancelling download: {value}").format(
                value=wanted
            )
        )
        self._note.setVisible(True)
        self._run_action("cancel_download", {"job_id": job_id})

    def _run_primary_model_action(self, model_id: str) -> None:
        pid = str(self._plugin_id or "").strip()
        wanted = str(model_id or "").strip()
        if not pid or not wanted or self._action_thread:
            return
        settings = self._settings.get_settings(pid, include_secrets=False)
        raw_models = settings.get("models") if isinstance(settings, dict) else None
        meta: dict = {}
        if isinstance(raw_models, list):
            for row in raw_models:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("model_id", "") or row.get("id", "")).strip()
                if row_id == wanted:
                    meta = dict(row)
                    break
        _label, action_id, payload, _tooltip = self._cloud_primary_action_for_entry(
            plugin_id=pid,
            model_id=wanted,
            meta=meta,
        )
        if not action_id:
            return
        _LOG.info(
            "model_primary_action_clicked plugin_id=%s model_id=%s action_id=%s meta_status=%s meta_failure=%s",
            pid,
            wanted,
            action_id,
            str(meta.get("status", "") or "").strip(),
            str(meta.get("failure_code", "") or "").strip(),
        )
        self._pending_model_actions[(pid, wanted)] = action_id
        self._focus_model_after_render = (pid, wanted)
        self._note.setText(
            _tr_map(self._labels, "models.note.testing_started", "Checking availability: {value}").format(
                value=wanted
            )
        )
        self._note.setVisible(True)
        self._render_current_plugin(sync_inventory=False, refresh_available=False)
        self._run_action(action_id, payload)

    def _persist_single_model_probe_result(
        self,
        *,
        plugin_id: str,
        action_id: str,
        result: object,
    ) -> bool:
        pid = str(plugin_id or "").strip()
        aid = str(action_id or "").strip()
        if not pid or aid not in {"test_model"}:
            return False
        data = _action_result_data(result)
        model_id = str(data.get("model_id", "") or "").strip()
        if not model_id:
            return False
        status, message = _action_status_and_message(result)
        now_ts = int(time.time())
        settings = self._settings.get_settings(pid, include_secrets=False)
        raw = settings.get("models") if isinstance(settings, dict) else None
        rows: list[dict] = [dict(entry) for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
        updated = False
        found = False
        for entry in rows:
            row_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if row_id != model_id:
                continue
            found = True
            entry["last_checked_at"] = now_ts
            if status in {"ok", "success"}:
                entry["status"] = "ready"
                entry["availability_status"] = "ready"
                entry["failure_code"] = ""
                entry["selectable"] = True
                entry["last_ok_at"] = now_ts
                updated = True
                continue
            failure = _cloud_failure_code_from_probe_message(message, data)
            entry["status"] = failure
            entry["availability_status"] = self._cloud_availability_from_failure_code(failure)
            entry["failure_code"] = failure
            entry["selectable"] = False
            updated = True
        if not found:
            row: dict[str, object] = {
                "model_id": model_id,
                "product_name": model_id,
                "last_checked_at": now_ts,
            }
            if status in {"ok", "success"}:
                row["status"] = "ready"
                row["availability_status"] = "ready"
                row["failure_code"] = ""
                row["selectable"] = True
                row["last_ok_at"] = now_ts
            else:
                failure = _cloud_failure_code_from_probe_message(message, data)
                row["status"] = failure
                row["availability_status"] = self._cloud_availability_from_failure_code(failure)
                row["failure_code"] = failure
                row["selectable"] = False
            rows.append(row)
            found = True
            updated = True
            _LOG.info(
                "persist_single_model_probe_result_upsert plugin_id=%s action_id=%s model_id=%s status=%s",
                pid,
                aid,
                model_id,
                str(row.get("status", "") or "").strip(),
            )
        if status in {"ok", "success"}:
            merged_settings = dict(settings) if isinstance(settings, dict) else {}
            merged_settings["models"] = rows
            if not self._is_local_models_plugin(pid):
                merged_settings["model_id"] = model_id
            preserve = [
                key for key in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(key)
            ]
            self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
            self._emit_models_changed(pid)
            _LOG.info(
                "persist_single_model_probe_result_ok plugin_id=%s model_id=%s status=ready selectable=true",
                pid,
                model_id,
            )
            return True
        if updated:
            merged_settings = dict(settings) if isinstance(settings, dict) else {}
            merged_settings["models"] = rows
            preserve = [
                key for key in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(key)
            ]
            self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
            self._emit_models_changed(pid)
            _LOG.info(
                "persist_single_model_probe_result_error plugin_id=%s model_id=%s failure_code=%s",
                pid,
                model_id,
                next(
                    (
                        str(entry.get("failure_code", "") or "").strip()
                        for entry in rows
                        if str(entry.get("model_id", "") or entry.get("id", "")).strip() == model_id
                    ),
                    "",
                ),
            )
            return True
        return False

    def _retest_failed_models(self) -> None:
        pid = str(self._plugin_id or "").strip()
        if not pid or self._action_thread:
            return
        if not self._has_action(pid, "retest_failed_models"):
            return
        self._run_action("retest_failed_models", {})

    def _remove_model(self, model_id: str, *, quant: str = "", file_name: str = "") -> None:
        pid = str(self._plugin_id or "").strip()
        wanted = str(model_id or "").strip()
        if not pid or (not wanted and not str(file_name or "").strip()):
            return
        if self._action_thread:
            return
        if self._uses_starter_add_flow(pid) and not self._is_local_models_plugin(pid):
            settings = self._settings.get_settings(pid, include_secrets=False)
            raw = settings.get("models") if isinstance(settings, dict) else None
            rows = [dict(entry) for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
            updated = [
                entry
                for entry in rows
                if str(entry.get("model_id", "") or entry.get("id", "")).strip() != wanted
            ]
            merged_settings = dict(settings) if isinstance(settings, dict) else {}
            merged_settings["models"] = updated
            if str(merged_settings.get("model_id", "") or "").strip() == wanted:
                merged_settings["model_id"] = ""
            preserve = [k for k in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(k)]
            self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
            self._emit_models_changed(pid)
            self.set_plugin(pid)
            return
        managed = self._managed_actions_for(pid) or {}
        action_id = str(managed.get("remove", "") or "").strip()
        if not action_id:
            return
        payload = {"model_id": wanted}
        if str(quant or "").strip():
            payload["quant"] = str(quant).strip()
        if str(file_name or "").strip():
            payload["file"] = str(file_name).strip()
        self._run_action(action_id, payload)

    def _upsert_model_in_settings(self, plugin_id: str, model_id: str, *, label: str = "") -> None:
        self._upsert_model_in_settings_with_meta(plugin_id, model_id, label=label)

    def _upsert_model_in_settings_with_meta(
        self,
        plugin_id: str,
        model_id: str,
        *,
        label: str = "",
        download_url: str = "",
        source_url: str = "",
        file_name: str = "",
        user_added: bool = False,
    ) -> None:
        pid = str(plugin_id or "").strip()
        mid = str(model_id or "").strip()
        if not pid or not mid:
            return
        settings = self._settings.get_settings(pid, include_secrets=False)
        raw = settings.get("models") if isinstance(settings, dict) else None
        updated: list[dict] = [dict(entry) for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []
        hidden_ids_raw = settings.get("hidden_model_ids") if isinstance(settings, dict) else []
        hidden_files_raw = settings.get("hidden_model_files") if isinstance(settings, dict) else []
        hidden_ids = {
            str(item or "").strip()
            for item in (hidden_ids_raw if isinstance(hidden_ids_raw, list) else [])
            if str(item or "").strip()
        }
        hidden_files = {
            str(item or "").strip()
            for item in (hidden_files_raw if isinstance(hidden_files_raw, list) else [])
            if str(item or "").strip()
        }
        found = False
        for entry in updated:
            entry_mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if entry_mid != mid:
                continue
            entry["enabled"] = True
            entry.pop("hidden", None)
            entry.pop("favorite", None)
            if user_added:
                entry["user_added"] = True
                entry["catalog_source"] = "user"
            if label and not str(entry.get("product_name", "") or "").strip():
                entry["product_name"] = label
            if download_url:
                entry["download_url"] = download_url
            if source_url:
                entry["source_url"] = source_url
            elif download_url:
                entry["source_url"] = download_url
            if file_name:
                entry["file"] = file_name
            found = True
            break
        if not found:
            row = {"model_id": mid, "enabled": True}
            if user_added:
                row["user_added"] = True
                row["catalog_source"] = "user"
            if label:
                row["product_name"] = label
            if download_url:
                row["download_url"] = download_url
            if source_url:
                row["source_url"] = source_url
            elif download_url:
                row["source_url"] = download_url
            if file_name:
                row["file"] = file_name
            updated.append(row)
        merged_settings = dict(settings) if isinstance(settings, dict) else {}
        merged_settings["models"] = updated
        if mid in hidden_ids:
            hidden_ids.discard(mid)
            merged_settings["hidden_model_ids"] = sorted(hidden_ids)
        if file_name and file_name in hidden_files:
            hidden_files.discard(file_name)
            merged_settings["hidden_model_files"] = sorted(hidden_files)
        if not self._is_local_models_plugin(pid):
            merged_settings["model_id"] = mid
        preserve = [k for k in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(k)]
        self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
        self._emit_models_changed(pid)

    def _forget_removed_model_in_settings(self, plugin_id: str, *, model_id: str = "", file_name: str = "") -> None:
        pid = str(plugin_id or "").strip()
        wanted_id = str(model_id or "").strip()
        wanted_file = str(file_name or "").strip()
        if not pid or (not wanted_id and not wanted_file):
            return
        settings = self._settings.get_settings(pid, include_secrets=False)
        rows_raw = settings.get("models") if isinstance(settings, dict) else None
        rows: list[dict] = [dict(entry) for entry in rows_raw if isinstance(entry, dict)] if isinstance(rows_raw, list) else []
        hidden_ids_raw = settings.get("hidden_model_ids") if isinstance(settings, dict) else []
        hidden_files_raw = settings.get("hidden_model_files") if isinstance(settings, dict) else []
        hidden_ids = {
            str(item or "").strip()
            for item in (hidden_ids_raw if isinstance(hidden_ids_raw, list) else [])
            if str(item or "").strip()
        }
        hidden_files = {
            str(item or "").strip()
            for item in (hidden_files_raw if isinstance(hidden_files_raw, list) else [])
            if str(item or "").strip()
        }
        if not rows:
            rows = []

        selected_model_id = str(settings.get("model_id", "") or "").strip() if isinstance(settings, dict) else ""
        selected_model_path = str(settings.get("model_path", "") or "").strip() if isinstance(settings, dict) else ""
        updated: list[dict] = []
        changed = False

        for entry in rows:
            entry_mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            entry_file = str(entry.get("file", "") or entry.get("filename", "")).strip()
            entry_path = str(entry.get("model_path", "") or entry.get("path", "")).strip()
            matches = False
            if wanted_id and entry_mid == wanted_id:
                matches = True
            elif wanted_file and (entry_file == wanted_file or Path(entry_path).name == wanted_file):
                matches = True
            if not matches:
                updated.append(entry)
                continue

            changed = True
            is_user_added = bool(entry.get("user_added", False))
            is_filesystem_only = not entry_mid and bool(entry_path or entry_file)
            if is_user_added or is_filesystem_only:
                continue

            kept = dict(entry)
            kept["hidden"] = True
            kept["enabled"] = False
            kept["installed"] = False
            kept["status"] = ""
            updated.append(kept)

        if wanted_id:
            if wanted_id not in hidden_ids:
                hidden_ids.add(wanted_id)
                changed = True
        if wanted_file:
            if wanted_file not in hidden_files:
                hidden_files.add(wanted_file)
                changed = True

        if not changed and wanted_id:
            updated.append(
                {
                    "model_id": wanted_id,
                    "hidden": True,
                    "enabled": False,
                    "installed": False,
                    "status": "",
                }
            )
            changed = True

        if not changed:
            return

        merged_settings = dict(settings) if isinstance(settings, dict) else {}
        merged_settings["models"] = updated
        merged_settings["hidden_model_ids"] = sorted(hidden_ids)
        merged_settings["hidden_model_files"] = sorted(hidden_files)
        if wanted_id and selected_model_id == wanted_id:
            merged_settings["model_id"] = ""
        if wanted_file and selected_model_path and Path(selected_model_path).name == wanted_file:
            merged_settings["model_path"] = ""
        preserve = [k for k in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(k)]
        self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
        self._emit_models_changed(pid)

    def _mark_removed_model_uninstalled_in_settings(
        self,
        plugin_id: str,
        *,
        model_id: str = "",
        file_name: str = "",
    ) -> None:
        pid = str(plugin_id or "").strip()
        wanted_id = str(model_id or "").strip()
        wanted_file = str(file_name or "").strip()
        if not pid or (not wanted_id and not wanted_file):
            return
        settings = self._settings.get_settings(pid, include_secrets=False)
        rows_raw = settings.get("models") if isinstance(settings, dict) else None
        rows: list[dict] = [dict(entry) for entry in rows_raw if isinstance(entry, dict)] if isinstance(rows_raw, list) else []
        changed = False
        for entry in rows:
            entry_mid = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            entry_file = str(entry.get("file", "") or entry.get("filename", "")).strip()
            matches = bool(wanted_id and entry_mid == wanted_id) or bool(wanted_file and entry_file == wanted_file)
            if not matches:
                continue
            entry["installed"] = False
            entry["enabled"] = False
            entry["status"] = ""
            entry["availability_status"] = "needs_setup"
            entry.pop("hidden", None)
            changed = True
        if not changed:
            return
        merged_settings = dict(settings) if isinstance(settings, dict) else {}
        merged_settings["models"] = rows
        preserve = [k for k in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(k)]
        self._settings.set_settings(pid, merged_settings, secret_fields=[], preserve_secrets=preserve)
        self._emit_models_changed(pid)

    def _add_selected_model(self) -> None:
        pid = str(self._plugin_id or "").strip()
        if not pid:
            return
        model_id = str(self._available_models.currentData() or "").strip()
        if not model_id:
            return
        label = str(self._available_models.currentText() or "").strip()
        try:
            self._upsert_model_in_settings(pid, model_id, label=label)
        except _MODEL_UI_RUNTIME_ERRORS as exc:
            _LOG.warning("add_selected_model_failed plugin_id=%s model_id=%s error=%s", pid, model_id, exc)
            self._note.setText(str(exc) or _tr_map(self._labels, "models.note.action_failed", "Action failed."))
            self._note.setVisible(True)
            return
        self.set_plugin(pid)

    def _add_custom_model(self) -> None:
        pid = str(self._plugin_id or "").strip()
        wanted = str(self._custom_model.text() or "").strip()
        download_url = str(self._custom_url.text() or "").strip()
        if not pid:
            return
        if not self._supports_custom_download_url(pid):
            download_url = ""
        payload = self._resolve_custom_model_payload(wanted, download_url)
        if payload is None:
            return
        self._custom_model.setText("")
        self._custom_url.setText("")

        try:
            self._upsert_model_in_settings_with_meta(
                pid,
                str(payload.get("model_id", "") or ""),
                label=str(payload.get("label", "") or ""),
                download_url=str(payload.get("download_url", "") or ""),
                source_url=str(payload.get("source_url", "") or ""),
                file_name=str(payload.get("file_name", "") or ""),
                user_added=True,
            )
        except _MODEL_UI_RUNTIME_ERRORS as exc:
            _LOG.warning("add_custom_model_failed plugin_id=%s error=%s", pid, exc)
            self._note.setText(str(exc) or _tr_map(self._labels, "models.note.action_failed", "Action failed."))
            self._note.setVisible(True)
            return

        self.set_plugin(pid)

    def _pick_local_model_file(self) -> None:
        pid = str(self._plugin_id or "").strip()
        if not pid:
            return
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _tr_map(self._labels, "models.button.pick_local_file", "Use local GGUF"),
            str(self._app_root),
            "GGUF files (*.gguf);;All files (*.*)",
        )
        if not file_path:
            return
        path = Path(file_path).expanduser()
        try:
            settings = self._settings.get_settings(pid, include_secrets=False)
            merged = dict(settings) if isinstance(settings, dict) else {}
            merged["model_path"] = str(path)
            merged["model_id"] = ""
            preserve = [
                k for k in self._settings.get_settings(pid, include_secrets=True).keys() if _is_secret_field_name(k)
            ]
            self._settings.set_settings(pid, merged, secret_fields=[], preserve_secrets=preserve)
            self._emit_models_changed(pid)
            self._note.setText(
                _tr_map(self._labels, "models.note.local_file_selected", "Local GGUF selected: {value}").format(
                    value=str(path)
                )
            )
            self._note.setVisible(True)
        except _MODEL_UI_RUNTIME_ERRORS as exc:
            _LOG.warning("pick_local_model_file_failed plugin_id=%s path=%s error=%s", pid, path, exc)
            self._note.setText(str(exc))
            self._note.setVisible(True)
        self.set_plugin(pid)

    @staticmethod
    def _infer_file_name_from_url(raw_url: str) -> str:
        text = str(raw_url or "").strip()
        if not text:
            return ""
        try:
            from urllib.parse import urlparse

            name = Path(urlparse(text).path).name
        except (ImportError, OSError, TypeError, ValueError):
            return ""
        return name if name.lower().endswith(".gguf") else ""

    @staticmethod
    def _model_id_from_hf_repo_url(raw_value: str) -> tuple[str, str]:
        text = str(raw_value or "").strip()
        if not _looks_like_hf_repo_url(text):
            return "", ""
        try:
            parsed = urlparse(text)
            parts = [part for part in parsed.path.split("/") if part]
        except (AttributeError, TypeError, ValueError):
            return "", ""
        if len(parts) < 2:
            return "", ""
        return f"{parts[0]}/{parts[1]}", text

    @staticmethod
    def _looks_like_model_reference(raw_value: str) -> bool:
        text = str(raw_value or "").strip()
        if not text:
            return False
        if _looks_like_http_url(text):
            return True
        return " " not in text

    def _set_note_message(self, text: str) -> None:
        self._note.setText(str(text or "").strip())
        self._note.setVisible(bool(str(text or "").strip()))

    def _resolve_custom_model_payload(self, wanted: str, download_url: str) -> dict[str, str] | None:
        raw_name = str(wanted or "").strip()
        raw_url = str(download_url or "").strip()
        if not raw_name and not raw_url:
            self._set_note_message(
                _tr_map(
                    self._labels,
                    "models.note.custom_requires_input",
                    "Enter a model ID / tag, a direct model URL, or both.",
                )
            )
            return None

        file_name = self._infer_file_name_from_url(raw_url)
        direct_download_url = raw_url if file_name else ""
        normalized_model_id = raw_name
        source_url = raw_url if raw_url else ""
        label = raw_name

        repo_model_id, repo_source_url = self._model_id_from_hf_repo_url(raw_name)
        if repo_model_id:
            normalized_model_id = repo_model_id
            source_url = repo_source_url
            label = repo_model_id
        elif raw_name and "/" in raw_name and not _looks_like_http_url(raw_name):
            source_url = f"https://huggingface.co/{raw_name}"

        if raw_name and raw_url and not self._looks_like_model_reference(raw_name):
            if not file_name:
                self._set_note_message(
                    _tr_map(
                        self._labels,
                        "models.note.custom_requires_real_id",
                        "If the first field is only a display name, also provide a direct model URL so the real model ID can be derived.",
                    )
                )
                return None
            normalized_model_id = file_name
            label = raw_name
            source_url = raw_url
        elif not normalized_model_id and file_name:
            normalized_model_id = file_name
            label = Path(file_name).stem
            source_url = raw_url

        if not normalized_model_id:
            self._set_note_message(
                _tr_map(
                    self._labels,
                    "models.note.custom_requires_real_id",
                    "If the first field is only a display name, also provide a direct model URL so the real model ID can be derived.",
                )
            )
            return None

        self._set_note_message("")
        return {
            "model_id": normalized_model_id,
            "label": label,
            "download_url": direct_download_url,
            "source_url": source_url or raw_url,
            "file_name": file_name,
        }

    def _refresh_models_catalog(self) -> None:
        pid = str(self._plugin_id or "").strip()
        if not pid:
            return
        if self._action_thread:
            return
        list_action = self._list_action_id(pid)
        if not list_action:
            return
        self._run_action(list_action, {})

    def _run_action(self, action_id: str, payload: dict) -> None:
        pid = str(self._plugin_id or "").strip()
        aid = str(action_id or "").strip()
        if not pid or not aid:
            return
        if self._action_thread:
            _LOG.info(
                "model_action_skipped_busy plugin_id=%s action_id=%s payload=%s",
                pid,
                aid,
                payload,
            )
            return

        self._note.setVisible(False)
        _LOG.info("model_action_started plugin_id=%s action_id=%s payload=%s", pid, aid, dict(payload or {}))

        thread_parent = QApplication.instance() or self
        thread = QThread(thread_parent)
        thread.setObjectName(f"aimn.model_cards:{pid}:{aid}")
        worker = _ActionWorker(self._action_service, pid, aid, payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.finished_ok.connect(self._on_action_ok)
        worker.finished_error.connect(self._on_action_error)
        worker.finished_ok.connect(worker.deleteLater)
        worker.finished_error.connect(worker.deleteLater)
        worker.finished_ok.connect(thread.quit)
        worker.finished_error.connect(thread.quit)
        thread.finished.connect(self._on_action_thread_finished)
        thread.finished.connect(thread.deleteLater)
        keepalive_key = _keepalive_register(thread, worker)
        thread.finished.connect(lambda key=keepalive_key: _keepalive_unregister(key))

        self._action_thread = thread
        self._action_worker = worker
        thread.start()

    def _on_action_ok(self, plugin_id: str, action_id: str, result: object) -> None:
        if not self._ui_alive():
            return
        pid = str(plugin_id or "").strip()
        aid = str(action_id or "").strip()
        if not pid:
            return
        data = _action_result_data(result)
        action_model_id = str(data.get("model_id", "") or "").strip()
        if action_model_id:
            self._pending_model_actions.pop((pid, action_model_id), None)
            self._focus_model_after_render = (pid, action_model_id)
        elif aid:
            for key in [item for item, pending_aid in self._pending_model_actions.items() if item[0] == pid and pending_aid == aid]:
                self._pending_model_actions.pop(key, None)
        try:
            status, message = _action_status_and_message(result)
            _LOG.info(
                "model_action_ok plugin_id=%s action_id=%s model_id=%s status=%s message=%s data=%s",
                pid,
                aid,
                action_model_id,
                status,
                message,
                data,
            )
            ok = status in {"ok", "success", ""}
            accepted = status == "accepted"
            managed = self._managed_actions_for(pid) or {}
            pull_action = str(managed.get("pull", "") or "").strip()
            remove_action = str(managed.get("remove", "") or "").strip()
            note_text = _action_note_text(self._labels, aid, status, message, result, remove_action_id=remove_action)
            if accepted:
                job_id = _action_result_job_id(result)
                if job_id:
                    data = _action_result_data(result)
                    label = str(data.get("file", "") or data.get("model_id", "") or "").strip() or "model"
                    if aid == pull_action:
                        self._upsert_model_in_settings_with_meta(
                            pid,
                            str(data.get("model_id", "") or "").strip(),
                            download_url=str(data.get("download_url", "") or "").strip(),
                            file_name=str(data.get("file", "") or "").strip(),
                        )
                    self._start_job_poll(
                        pid,
                        aid,
                        job_id,
                        label,
                        model_id=str(data.get("model_id", "") or "").strip(),
                    )
                    if aid == pull_action:
                        self._note.setText(
                            _tr_map(self._labels, "models.note.download_started", "Download started: {value}").format(
                                value=label
                            )
                        )
                        self._note.setVisible(True)
                    if pid == self._plugin_id:
                        self._render_current_plugin(sync_inventory=False, refresh_available=False)
                    return
            if note_text:
                self._note.setText(note_text)
                self._note.setVisible(True)
            elif ok and aid == "test_model":
                model_id = str(data.get("model_id", "") or "").strip() or "model"
                self._note.setText(
                    _tr_map(self._labels, "models.note.testing_success", "Availability confirmed: {value}").format(
                        value=model_id
                    )
                )
                self._note.setVisible(True)
            elif ok and aid == "test_connection":
                provider_value = str(pid or "").strip() or "provider"
                self._note.setText(
                    _tr_map(
                        self._labels,
                        "models.note.testing_success_provider",
                        "Provider is ready: {value}",
                    ).format(value=provider_value)
                )
                self._note.setVisible(True)
            elif ok and aid == "retest_failed_models":
                data = _action_result_data(result)
                summary = data.get("summary") if isinstance(data, dict) else {}
                if isinstance(summary, dict):
                    self._note.setText(
                        _tr_map(
                            self._labels,
                            "models.note.retest_failed_complete",
                            "Rechecked {retested} model(s). Ready now: {selectable}/{total}.",
                        ).format(
                            retested=int(summary.get("retested", 0) or 0),
                            selectable=int(summary.get("selectable", 0) or 0),
                            total=int(summary.get("total", 0) or 0),
                        )
                    )
                    self._note.setVisible(True)
            if not ok:
                if not note_text:
                    if aid == pull_action:
                        message = _friendly_download_error(
                            self._labels,
                            message,
                            result,
                            plugin_id=pid,
                        )
                    elif aid in {"test_model", "test_connection"}:
                        model_id = str(data.get("model_id", "") or "").strip() or "model"
                        if aid == "test_connection":
                            model_id = str(pid or "").strip() or "provider"
                        message = _tr_map(
                            self._labels,
                            "models.note.testing_failed",
                            "Availability check failed for {value}: {reason}",
                        ).format(value=model_id, reason=message or "request_failed")
                    self._note.setText(
                        message or _tr_map(self._labels, "models.note.action_failed", "Action failed.")
                    )
                    self._note.setVisible(True)
            list_action = self._list_action_id(pid)
            persist_actions = {str(val).strip() for val in managed.values() if str(val).strip()}
            if list_action:
                persist_actions.add(list_action)
            if self._has_action(pid, "retest_failed_models"):
                persist_actions.add("retest_failed_models")
            self._persist_single_model_probe_result(plugin_id=pid, action_id=aid, result=result)
            should_persist_models = bool(ok and aid and aid in persist_actions)
            if pid == "llm.ollama" and aid == list_action:
                should_persist_models = True
            if should_persist_models:
                models = _models_from_action_result(result)
                # Only the list action is allowed to overwrite the model catalog with an empty list.
                # Pull/remove actions may succeed without returning an updated catalog.
                if models or aid == list_action:
                    try:
                        current_plain = self._settings.get_settings(pid, include_secrets=False)
                        merged = dict(current_plain) if isinstance(current_plain, dict) else {}
                        merged["models"] = models
                        if pid == "llm.ollama" and aid == list_action:
                            merged[_OLLAMA_RUNTIME_META_KEY] = {
                                "ollama_installed": bool(shutil.which("ollama")),
                                "server_running": bool(data.get("server_running", False)),
                                "total": int(data.get("total", 0) or 0),
                                "updated_at": int(time.time()),
                            }
                        preserve = [
                            k
                            for k in self._settings.get_settings(pid, include_secrets=True).keys()
                            if _is_secret_field_name(k)
                        ]
                        self._settings.set_settings(
                            pid,
                            merged,
                            secret_fields=[],
                            preserve_secrets=preserve,
                        )
                        self._emit_models_changed(pid)
                    except _MODEL_UI_RUNTIME_ERRORS as exc:
                        _LOG.warning(
                            "persist_models_after_action_failed plugin_id=%s action_id=%s error=%s",
                            pid,
                            aid,
                            exc,
                        )
                if aid == list_action:
                    self._catalog_loaded_once.add(pid)
            if ok and aid == remove_action:
                removed_model_id = str(data.get("model_id", "") or "").strip()
                removed_file = str(data.get("file", "") or "").strip()
                if _boolish(data.get("remove_from_settings")):
                    self._forget_removed_model_in_settings(
                        pid,
                        model_id=removed_model_id,
                        file_name=removed_file,
                    )
                else:
                    self._mark_removed_model_uninstalled_in_settings(
                        pid,
                        model_id=removed_model_id,
                        file_name=removed_file,
                    )
        except _MODEL_UI_RUNTIME_ERRORS as exc:
            logging.getLogger("aimn.ui").warning(
                "model_action_ok_handler_failed plugin_id=%s action_id=%s error=%s",
                pid,
                aid,
                exc,
            )
            self._note.setText(str(exc) or _tr_map(self._labels, "models.note.action_failed", "Action failed."))
            self._note.setVisible(True)
        self.set_plugin(pid)

    def _on_action_error(self, plugin_id: str, action_id: str, message: str) -> None:
        if not self._ui_alive():
            return
        aid = str(action_id or "").strip()
        if aid:
            for key in [item for item, pending_aid in self._pending_model_actions.items() if item[0] == str(plugin_id or "").strip() and pending_aid == aid]:
                self._pending_model_actions.pop(key, None)
                self._focus_model_after_render = (str(plugin_id or "").strip(), str(key[1] or "").strip())
        _LOG.warning(
            "model_action_error plugin_id=%s action_id=%s message=%s",
            plugin_id,
            action_id,
            message,
        )
        text = str(message or "").strip() or _tr_map(self._labels, "models.note.action_failed", "Action failed.")
        self._note.setText(text)
        self._note.setVisible(True)
        pid = str(plugin_id or self._plugin_id or "").strip()
        if pid:
            self.set_plugin(pid)

    def _on_action_thread_finished(self) -> None:
        self._action_thread = None
        self._action_worker = None

    def _start_job_poll(
        self,
        plugin_id: str,
        action_id: str,
        job_id: str,
        label: str,
        *,
        model_id: str = "",
    ) -> None:
        pid = str(plugin_id or "").strip()
        jid = str(job_id or "").strip()
        if not pid or not jid:
            return
        self._job_states[jid] = {
            "plugin_id": pid,
            "action_id": str(action_id or "").strip(),
            "job_id": jid,
            "label": str(label or "").strip() or "model",
            "model_id": str(model_id or "").strip(),
            "status": "queued",
            "progress": 0,
            "message": "queued",
        }
        if not self._job_poll_timer.isActive():
            self._job_poll_timer.start()

    def _job_state_for(self, plugin_id: str, model_id: str) -> dict[str, object] | None:
        pid = str(plugin_id or "").strip()
        mid = str(model_id or "").strip()
        if not pid or not mid:
            return None
        for state in self._job_states.values():
            if str(state.get("plugin_id", "") or "").strip() != pid:
                continue
            if str(state.get("model_id", "") or "").strip() != mid:
                continue
            return dict(state)
        return None

    def _poll_active_job(self) -> None:
        if not self._job_states:
            self._job_poll_timer.stop()
            return
        rerender_current = False
        for job_id, job in list(self._job_states.items()):
            pid = str(job.get("plugin_id", "") or "").strip()
            label = str(job.get("label", "") or "").strip() or "model"
            if not pid:
                self._job_states.pop(job_id, None)
                continue
            try:
                status = self._action_service.get_job_status(pid, job_id)
            except _MODEL_UI_RUNTIME_ERRORS as exc:
                _LOG.warning("poll_model_job_failed plugin_id=%s job_id=%s error=%s", pid, job_id, exc)
                self._note.setText(
                    _tr_map(self._labels, "models.note.download_failed", "Download failed for {value}: {reason}").format(
                        value=label,
                        reason=str(exc) or "unknown error",
                    )
                )
                self._note.setVisible(True)
                self._job_states.pop(job_id, None)
                rerender_current = rerender_current or (pid == self._plugin_id)
                continue
            if status is None:
                continue

            state = str(getattr(status, "status", "") or "").strip().lower()
            progress_raw = getattr(status, "progress", None)
            try:
                progress = (
                    max(0, min(100, int(round(float(progress_raw) * 100)))) if progress_raw is not None else 0
                )
            except (TypeError, ValueError):
                progress = 0
            message = str(getattr(status, "message", "") or "").strip()
            previous_state = str(job.get("status", "") or "").strip().lower()
            previous_progress = int(job.get("progress", 0) or 0)
            previous_message = str(job.get("message", "") or "").strip()
            job["status"] = state
            job["progress"] = progress
            job["message"] = message
            if pid == self._plugin_id and (
                state != previous_state or progress != previous_progress or message != previous_message
            ):
                rerender_current = True

            if state in {"queued", "running"}:
                continue

            self._job_states.pop(job_id, None)
            if state == "success":
                self._note.setText(
                    _tr_map(self._labels, "models.note.download_success", "Download completed: {value}").format(
                        value=label
                    )
                )
                self._note.setVisible(True)
                rerender_current = rerender_current or (pid == self._plugin_id)
                if pid == self._plugin_id:
                    self._render_current_plugin(sync_inventory=True, refresh_available=False)
                self._refresh_models_catalog()
                continue

            if state in {"failed", "error", "cancelled"}:
                reason = message or state or "failed"
                self._note.setText(
                    _tr_map(self._labels, "models.note.download_failed", "Download failed for {value}: {reason}").format(
                        value=label,
                        reason=reason,
                    )
                )
                self._note.setVisible(True)
                rerender_current = rerender_current or (pid == self._plugin_id)

        if not self._job_states:
            self._job_poll_timer.stop()
        if rerender_current and self._plugin_id:
            self._render_current_plugin(sync_inventory=False, refresh_available=False)

    def _has_action(self, plugin_id: str, action_id: str) -> bool:
        pid = str(plugin_id or "").strip()
        aid = str(action_id or "").strip()
        if not pid or not aid:
            return False
        try:
            actions = self._action_service.list_actions(pid)
        except _MODEL_UI_RUNTIME_ERRORS as exc:
            _LOG.warning("list_model_actions_failed plugin_id=%s error=%s", pid, exc)
            return False
        return any(str(getattr(a, "action_id", "") or "").strip() == aid for a in (actions or []))

    def _ui_alive(self) -> bool:
        return _is_valid(self) and _is_valid(self._cards) and _is_valid(self._cards_layout)

    def _capture_scroll_state(self) -> tuple[QScrollArea | None, int]:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent, int(parent.verticalScrollBar().value())
            parent = parent.parentWidget()
        return None, 0

    def _restore_scroll_state(self, state: tuple[QScrollArea | None, int]) -> None:
        area, value = state
        if not isinstance(area, QScrollArea):
            return
        focus_plugin_id, focus_model_id = self._focus_model_after_render
        if focus_plugin_id == str(self._plugin_id or "").strip() and focus_model_id:
            def _restore_focus() -> None:
                for index in range(self._cards_layout.count()):
                    item = self._cards_layout.itemAt(index)
                    widget = item.widget() if item else None
                    if not isinstance(widget, QWidget):
                        continue
                    if str(widget.property("aimn_model_id") or "").strip() != focus_model_id:
                        continue
                    area.ensureWidgetVisible(widget, 0, 24)
                    self._focus_model_after_render = ("", "")
                    return
                area.verticalScrollBar().setValue(int(value))
                self._focus_model_after_render = ("", "")
            QTimer.singleShot(0, _restore_focus)
            return
        QTimer.singleShot(0, lambda: area.verticalScrollBar().setValue(int(value)))


def _models_from_action_result(result: object) -> list[dict]:
    if result is None:
        return []
    data = None
    if hasattr(result, "data"):
        try:
            data = result.data
        except (AttributeError, RuntimeError):
            data = None
    if data is None and isinstance(result, dict):
        data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        models = data.get("models")
    elif isinstance(result, dict) and isinstance(result.get("models"), list):
        models = result.get("models")
    else:
        models = None
    if not isinstance(models, list):
        return []
    return [entry for entry in models if isinstance(entry, dict)]


def _action_status_and_message(result: object) -> tuple[str, str]:
    status = ""
    message = ""
    if isinstance(result, dict):
        status = str(result.get("status", "") or "").strip().lower()
        message = str(result.get("message", "") or "").strip()
        return status, message
    if hasattr(result, "status"):
        try:
            status = str(result.status or "").strip().lower()
        except (AttributeError, RuntimeError):
            status = ""
    if hasattr(result, "message"):
        try:
            message = str(result.message or "").strip()
        except (AttributeError, RuntimeError):
            message = ""
    return status, message


def _action_result_data(result: object) -> dict:
    if isinstance(result, dict):
        raw = result.get("data")
        return raw if isinstance(raw, dict) else {}
    if hasattr(result, "data"):
        try:
            raw = result.data
        except (AttributeError, RuntimeError):
            raw = None
        return raw if isinstance(raw, dict) else {}
    return {}


def _action_result_job_id(result: object) -> str:
    if isinstance(result, dict):
        return str(result.get("job_id", "") or "").strip()
    if hasattr(result, "job_id"):
        try:
            return str(result.job_id or "").strip()
        except (AttributeError, RuntimeError):
            return ""
    return ""


def _cloud_failure_code_from_probe_message(message: str, data: dict[str, object] | None = None) -> str:
    payload = dict(data or {})
    explicit = str(payload.get("failure_code", "") or payload.get("status", "") or "").strip().lower()
    if explicit in {
        "provider_blocked",
        "model_not_found",
        "not_available",
        "auth_error",
        "rate_limited",
        "bad_request",
        "empty_response",
        "request_failed",
        "timeout",
        "transport_error",
        "network_error",
    }:
        return explicit
    text = str(message or "").strip().lower()
    if not text:
        return "request_failed"
    if any(token in text for token in {"api_key_missing", "auth_error", "status=401", "status=402", "unauthorized"}):
        return "auth_error"
    if any(token in text for token in {"provider_blocked", "blocked by google ai studio", "status=403", "blocked"}):
        return "provider_blocked"
    if any(token in text for token in {"model_not_found", "status=404"}):
        return "model_not_found"
    if "not_available" in text or "not available" in text:
        return "not_available"
    if "rate_limited" in text or "status=429" in text:
        return "rate_limited"
    if "status=400" in text or "bad_request" in text:
        return "bad_request"
    if "empty_response" in text:
        return "empty_response"
    if "timeout" in text:
        return "timeout"
    if any(token in text for token in {"ssl", "unexpected_eof", "transport_error", "connection reset", "winerror 10054"}):
        return "transport_error"
    if any(token in text for token in {"network_error", "temporary failure in name resolution", "name or service not known"}):
        return "network_error"
    return "request_failed"


def _action_note_text(
    labels: dict[str, str],
    action_id: str,
    status: str,
    message: str,
    result: object,
    *,
    remove_action_id: str = "",
) -> str:
    aid = str(action_id or "").strip()
    remove_id = str(remove_action_id or "").strip()
    if not remove_id or aid != remove_id:
        return ""
    data = _action_result_data(result)
    value = str(data.get("file", "") or data.get("model_id", "") or "").strip()
    if not value:
        value = "model"
    if str(status or "").strip().lower() in {"ok", "success"} and message == "model_removed":
        return _tr_map(labels, "models.note.model_removed", "Model removed: {value}").format(value=value)
    if message == "model_not_found_for_remove":
        return _tr_map(
            labels,
            "models.note.model_remove_missing",
            "Local model file was not found: {value}",
        ).format(value=value)
    return ""
