from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aimn.ui.widgets.standard_components import StandardSelectableChip

_COMPACT_CHIP_MAX_CHARS = 30
_SECTION_MARGIN = 4
_SECTION_SPACING = 4


@dataclass(frozen=True)
class ModelSpec:
    label: str
    model_id: str = ""
    model_path: str = ""

    def key(self) -> str:
        if self.model_path:
            return f"path:{self.model_path}"
        return f"id:{self.model_id}"


def _compact_chip_text(text: str, *, max_chars: int = _COMPACT_CHIP_MAX_CHARS) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1].rstrip()}…"


def _mark_plain_group(widget: QGroupBox) -> None:
    widget.setFlat(True)
    widget.setProperty("drawerPlain", True)


class WrappingFlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def addWidget(self, widget: QWidget) -> None:  # noqa: N802
        super().addWidget(widget)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, max(0, int(width)), 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = max(0, int(self.spacing()))
        max_x = effective.x() + max(0, effective.width())

        for item in self._items:
            hint = item.sizeHint()
            if line_height > 0 and (x + hint.width()) > max_x:
                x = effective.x()
                y += line_height + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + spacing
            line_height = max(line_height, hint.height())

        total_height = (y - effective.y()) + line_height
        return total_height + margins.top() + margins.bottom()


class TextProcessingVariantsPanel(QGroupBox):
    """
    Drawer panel: toggle multiple text_processing plugins (stage variants).
    """

    settingsChanged = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__("Algorithms", parent)
        _mark_plain_group(self)
        self.setProperty("density_level", "basic")
        self._buttons: dict[str, StandardSelectableChip] = {}
        self._available: list[tuple[str, str]] = []
        self._enabled: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(_SECTION_SPACING)

        hint = QLabel("Select one or more algorithms to run for this meeting.")
        hint.setObjectName("pipelineMetaLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._chips_host = QWidget(self)
        self._chips_flow = WrappingFlowLayout(self._chips_host, spacing=6)
        self._chips_host.setLayout(self._chips_flow)
        layout.addWidget(self._chips_host, 1)

    def apply_stage(self, stage) -> None:
        available = stage.ui_metadata.get("available_variants", [])
        enabled = stage.ui_metadata.get("enabled_variants", [])
        self._available = [
            (str(pid), str(label))
            for pid, label in available
            if str(pid).strip() and str(label).strip()
        ]
        self._enabled = [str(pid) for pid in enabled if str(pid).strip()]
        self._render()

    def collect_settings(self) -> dict:
        variants = [{"plugin_id": pid, "params": {}} for pid in self._enabled]
        return {"__stage_payload__": {"variants": variants}}

    def _render(self) -> None:
        for i in reversed(range(self._chips_flow.count())):
            item = self._chips_flow.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._buttons = {}

        for pid, label in self._available:
            btn = StandardSelectableChip(_compact_chip_text(label))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            enabled = pid in set(self._enabled)
            btn.apply_state(selected=False, active=enabled, tone="success", checked=enabled)
            btn.clicked.connect(lambda checked, _pid=pid: self._toggle(_pid, checked))
            btn.setToolTip(str(label or pid))
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self._buttons[pid] = btn
            self._chips_flow.addWidget(btn)

    def _toggle(self, plugin_id: str, enabled: bool) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        current = [p for p in self._enabled if p != pid]
        if enabled:
            current.append(pid)
        self._enabled = current
        btn = self._buttons.get(pid)
        if btn:
            btn.apply_state(selected=False, active=enabled, tone="success", checked=enabled)
        self.settingsChanged.emit()


class TextProcessingGroupedPanel(QGroupBox):
    """
    Drawer panel: group algorithms into "providers" (e.g. Essentials / Advanced).
    """

    settingsChanged = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__("Algorithms", parent)
        _mark_plain_group(self)
        self.setProperty("density_level", "basic")
        self._providers: list[tuple[str, str]] = []
        self._provider_buttons: dict[str, StandardSelectableChip] = {}
        self._provider_algorithms: dict[str, list[tuple[str, str, str]]] = {}
        self._enabled: dict[str, list[str]] = {}
        self._selected_provider: str = ""
        self._algo_buttons: dict[str, StandardSelectableChip] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(_SECTION_SPACING)

        hint = QLabel(
            "Structuring and refining meaning using mathematical and linguistic models.\n"
            "Semantic Processing works before AI reasoning.\n"
            "It does not invent or generate new text — it reveals structure, signals, and meaning already present."
        )
        hint.setObjectName("pipelineMetaLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._providers_box = QGroupBox("Groups")
        _mark_plain_group(self._providers_box)
        providers_layout = QVBoxLayout(self._providers_box)
        providers_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        providers_layout.setSpacing(_SECTION_SPACING)
        self._providers_host = QWidget(self._providers_box)
        self._providers_flow = WrappingFlowLayout(self._providers_host, spacing=8)
        self._providers_host.setLayout(self._providers_flow)
        providers_layout.addWidget(self._providers_host)
        layout.addWidget(self._providers_box)

        algos_box = QGroupBox("Algorithms")
        _mark_plain_group(algos_box)
        algos_layout = QVBoxLayout(algos_box)
        algos_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        algos_layout.setSpacing(_SECTION_SPACING)
        self._algos_host = QWidget()
        self._algos_flow = WrappingFlowLayout(self._algos_host, spacing=6)
        self._algos_host.setLayout(self._algos_flow)
        algos_layout.addWidget(self._algos_host, 1)
        self._empty = QLabel("No algorithms found in this group.")
        self._empty.setObjectName("pipelineMetaLabel")
        self._empty.setWordWrap(True)
        algos_layout.addWidget(self._empty)
        layout.addWidget(algos_box, 1)

    def apply_stage(self, stage) -> None:
        meta = getattr(stage, "ui_metadata", {}) or {}
        self._providers = [
            (str(pid), str(label))
            for pid, label in (meta.get("available_providers", []) or [])
            if str(pid).strip()
        ]
        raw = meta.get("provider_models", {}) or {}
        provider_algos: dict[str, list[tuple[str, str, str]]] = {}
        if isinstance(raw, dict):
            for group_id, items in raw.items():
                gid = str(group_id)
                algos: list[tuple[str, str, str]] = []
                if isinstance(items, list):
                    for entry in items:
                        if not isinstance(entry, dict):
                            continue
                        pid = str(entry.get("plugin_id", "") or "").strip()
                        label = str(entry.get("label", "") or pid).strip() or pid
                        tooltip = str(entry.get("tooltip", "") or "").strip()
                        if pid:
                            algos.append((pid, label, tooltip))
                provider_algos[gid] = algos
        self._provider_algorithms = provider_algos

        enabled = meta.get("enabled_models", {}) or {}
        enabled_map: dict[str, list[str]] = {}
        if isinstance(enabled, dict):
            for gid, ids in enabled.items():
                if isinstance(ids, list):
                    enabled_map[str(gid)] = [str(x) for x in ids if str(x).strip()]
        self._enabled = enabled_map

        selected = str(meta.get("selected_provider", "") or "").strip()
        if not selected and self._providers:
            selected = self._providers[0][0]
        self._selected_provider = selected
        self._render()

    def collect_settings(self) -> dict:
        variants: list[dict] = []
        order = [pid for pid, _label in self._providers]
        for group_id in order:
            for plugin_id in self._enabled.get(group_id, []):
                variants.append({"plugin_id": plugin_id, "params": {}})
        return {"__stage_payload__": {"variants": variants}}

    def set_provider_selector_visible(self, visible: bool) -> None:
        self._providers_box.setVisible(bool(visible))

    def select_provider(self, provider_id: str) -> None:
        gid = str(provider_id or "").strip()
        if not gid or gid not in {pid for pid, _label in self._providers}:
            return
        self._selected_provider = gid
        self._render()

    def has_enabled_selection(self) -> bool:
        return any(bool(self._enabled.get(gid)) for gid, _label in self._providers)

    def _render(self) -> None:
        self._clear_layout(self._providers_flow)
        self._clear_layout(self._algos_flow)
        self._provider_buttons = {}
        self._algo_buttons = {}

        for gid, label in self._providers:
            enabled_any = bool(self._enabled.get(gid))
            selected = gid == self._selected_provider
            btn = StandardSelectableChip(_compact_chip_text(label))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            btn.apply_state(selected=selected, active=enabled_any, tone="focus", checked=selected)
            btn.clicked.connect(lambda _checked, _gid=gid: self._select_provider(_gid))
            self._provider_buttons[gid] = btn
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            btn.setToolTip(str(label or gid))
            self._providers_flow.addWidget(btn)
        algos = self._provider_algorithms.get(self._selected_provider, [])
        self._empty.setVisible(not bool(algos))
        if not algos:
            return
        enabled = set(self._enabled.get(self._selected_provider, []) or [])
        for pid, label, tooltip in algos:
            is_enabled = pid in enabled
            btn = StandardSelectableChip(_compact_chip_text(label))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            btn.apply_state(selected=False, active=is_enabled, tone="success", checked=is_enabled)
            btn.clicked.connect(lambda checked, _pid=pid: self._toggle_algo(_pid, checked))
            btn.setToolTip(tooltip or str(label or pid))
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self._algo_buttons[pid] = btn
            self._algos_flow.addWidget(btn)

    def _select_provider(self, provider_id: str) -> None:
        gid = str(provider_id or "").strip()
        if not gid or gid == self._selected_provider:
            return
        self._selected_provider = gid
        self._render()

    def _toggle_algo(self, plugin_id: str, enabled: bool) -> None:
        pid = str(plugin_id or "").strip()
        if not pid or not self._selected_provider:
            return
        current = [p for p in (self._enabled.get(self._selected_provider, []) or []) if p != pid]
        if enabled:
            current.append(pid)
        self._enabled[self._selected_provider] = current
        btn = self._algo_buttons.get(pid)
        if btn:
            btn.apply_state(selected=False, active=enabled, tone="success", checked=enabled)
        prov_btn = self._provider_buttons.get(self._selected_provider)
        if prov_btn:
            prov_btn.apply_state(
                selected=True,
                active=bool(self._enabled.get(self._selected_provider)),
                tone="focus",
                checked=True,
            )
        self.settingsChanged.emit()

    @staticmethod
    def _clear_layout(layout) -> None:
        for i in reversed(range(layout.count())):
            item = layout.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()


class LlmVariantsPanel(QGroupBox):
    """
    Drawer panel: select providers + one or more models per provider.
    Produces llm_processing stage variants.
    """

    settingsChanged = Signal()
    refreshModelsRequested = Signal(str)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__("Providers & Models", parent)
        _mark_plain_group(self)
        self.setProperty("density_level", "basic")
        self._providers: list[tuple[str, str]] = []
        self._models: dict[str, list[ModelSpec]] = {}
        self._enabled_models: dict[str, list[str]] = {}
        self._selected_provider: str = ""
        self._provider_buttons: dict[str, StandardSelectableChip] = {}
        self._model_buttons: dict[str, StandardSelectableChip] = {}
        self._updating_prompt_controls = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(_SECTION_SPACING)

        self._hint = QLabel(
            "Pick provider(s) and available model(s) to run. Add or download models in Settings."
        )
        self._hint.setObjectName("pipelineMetaLabel")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._providers_box = QGroupBox("Providers")
        _mark_plain_group(self._providers_box)
        providers_layout = QVBoxLayout(self._providers_box)
        providers_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        providers_layout.setSpacing(_SECTION_SPACING)
        self._providers_host = QWidget(self._providers_box)
        self._providers_flow = WrappingFlowLayout(self._providers_host, spacing=8)
        self._providers_host.setLayout(self._providers_flow)
        providers_layout.addWidget(self._providers_host)
        layout.addWidget(self._providers_box)

        self._models_box = QGroupBox("Models")
        _mark_plain_group(self._models_box)
        models_layout = QVBoxLayout(self._models_box)
        models_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        models_layout.setSpacing(_SECTION_SPACING)
        models_actions = QHBoxLayout()
        models_actions.setSpacing(8)
        self._models_note = QLabel("All available models appear here.")
        self._models_note.setObjectName("pipelineMetaLabel")
        self._models_note.setWordWrap(True)
        models_actions.addWidget(self._models_note, 1)
        models_layout.addLayout(models_actions)
        self._models_grid_host = QWidget()
        self._models_flow = WrappingFlowLayout(self._models_grid_host, spacing=6)
        self._models_grid_host.setLayout(self._models_flow)
        models_layout.addWidget(self._models_grid_host, 1)
        layout.addWidget(self._models_box)

        self._empty = QLabel(
            "No available models found for this provider.\nAdd or download a model in Settings, then return here."
        )
        self._empty.setObjectName("pipelineMetaLabel")
        self._empty.setWordWrap(True)
        models_layout.addWidget(self._empty)

        self._prompt_box = QGroupBox("Prompt")
        _mark_plain_group(self._prompt_box)
        prompt_layout = QVBoxLayout(self._prompt_box)
        prompt_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        prompt_layout.setSpacing(_SECTION_SPACING)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile"))
        self._prompt_profile = QComboBox()
        self._prompt_profile.currentIndexChanged.connect(self._on_prompt_profile_changed)
        profile_row.addWidget(self._prompt_profile, 1)
        prompt_layout.addLayout(profile_row)

        self._prompt_custom = QTextEdit()
        self._prompt_custom.setPlaceholderText("Custom prompt request body")
        self._prompt_custom.textChanged.connect(self._on_prompt_custom_changed)
        prompt_layout.addWidget(self._prompt_custom)

        self._prompt_hint = QLabel(
            "Profile controls summary style. Use Custom to provide your own request body."
        )
        self._prompt_hint.setObjectName("pipelineMetaLabel")
        self._prompt_hint.setWordWrap(True)
        prompt_layout.addWidget(self._prompt_hint)
        layout.addWidget(self._prompt_box)

    def apply_stage(self, stage) -> None:
        self._providers = [
            (str(pid), str(label))
            for pid, label in stage.ui_metadata.get("available_providers", [])
            if str(pid).strip()
        ]
        raw_models = stage.ui_metadata.get("provider_models", {}) or {}
        models: dict[str, list[ModelSpec]] = {}
        if isinstance(raw_models, dict):
            for pid, items in raw_models.items():
                pid_str = str(pid)
                specs: list[ModelSpec] = []
                if isinstance(items, list):
                    for entry in items:
                        if isinstance(entry, dict):
                            label = str(entry.get("label", "")).strip()
                            model_id = str(entry.get("model_id", "")).strip()
                            model_path = str(entry.get("model_path", "")).strip()
                            if label and (model_id or model_path):
                                specs.append(ModelSpec(label=label, model_id=model_id, model_path=model_path))
                models[pid_str] = specs
        self._models = models

        enabled = stage.ui_metadata.get("enabled_models", {}) or {}
        enabled_models: dict[str, list[str]] = {}
        if isinstance(enabled, dict):
            for pid, keys in enabled.items():
                if isinstance(keys, list):
                    enabled_models[str(pid)] = [str(k) for k in keys if str(k).strip()]
        self._enabled_models = enabled_models
        selected = str(stage.ui_metadata.get("selected_provider", "") or "").strip()
        if not selected and self._providers:
            selected = self._providers[0][0]
        self._selected_provider = selected
        self._apply_prompt_settings(getattr(stage, "current_settings", {}) or {})
        self._render()

    def collect_settings(self) -> dict:
        variants: list[dict] = []
        provider_order = [pid for pid, _label in self._providers]
        for pid in provider_order:
            keys = self._enabled_models.get(pid, [])
            by_key = {m.key(): m for m in self._models.get(pid, [])}
            for key in keys:
                spec = by_key.get(key)
                if not spec:
                    continue
                params = {}
                if spec.model_path:
                    params["model_path"] = spec.model_path
                    params["model_id"] = ""
                else:
                    params["model_id"] = spec.model_id
                    params["model_path"] = ""
                variants.append({"plugin_id": pid, "params": params})
        selected_profile = self._selected_prompt_profile()
        selected_custom = self._prompt_custom.toPlainText().strip()
        prompt_signature = ""
        try:
            from aimn.plugins.prompt_manager import compute_prompt_signature

            prompt_signature = str(compute_prompt_signature(selected_profile, selected_custom))
        except Exception:
            prompt_signature = ""
        stage_payload = {
            "variants": variants,
            "params": {
                "prompt_profile": selected_profile,
                "prompt_custom": selected_custom,
                "prompt_signature": prompt_signature,
            },
        }
        return {"__stage_payload__": stage_payload}

    def set_provider_selector_visible(self, visible: bool) -> None:
        self._providers_box.setVisible(bool(visible))

    def select_provider(self, provider_id: str) -> None:
        self._select_provider(provider_id)

    def provider_has_enabled_models(self, provider_id: str) -> bool:
        pid = str(provider_id or "").strip()
        return bool(self._enabled_models.get(pid))

    def _render(self) -> None:
        self._clear_layout(self._providers_flow)
        self._clear_layout(self._models_flow)
        self._provider_buttons = {}
        self._model_buttons = {}
        self._models_note.setText("All available models appear here. Add or download more models in Settings.")

        for pid, label in self._providers:
            enabled_any = bool(self._enabled_models.get(pid))
            selected = pid == self._selected_provider
            btn = StandardSelectableChip(_compact_chip_text(label))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            btn.apply_state(selected=selected, active=enabled_any, tone="focus", checked=selected)
            btn.clicked.connect(lambda _checked, _pid=pid: self._select_provider(_pid))
            btn.setToolTip(str(label or pid))
            self._provider_buttons[pid] = btn
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self._providers_flow.addWidget(btn)
        models = self._models.get(self._selected_provider, [])
        self._empty.setVisible(not bool(models))
        if not models:
            return
        enabled_keys = set(self._enabled_models.get(self._selected_provider, []) or [])
        for spec in models:
            key = spec.key()
            is_enabled = key in enabled_keys
            btn = StandardSelectableChip(_compact_chip_text(spec.label))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            btn.apply_state(selected=False, active=is_enabled, tone="success", checked=is_enabled)
            btn.clicked.connect(lambda checked, _key=key: self._toggle_model(_key, checked))
            tooltip = spec.label
            if spec.model_path or spec.model_id:
                tooltip = f"{tooltip}\n{spec.model_path or spec.model_id}"
            btn.setToolTip(tooltip)
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self._model_buttons[key] = btn
            self._models_flow.addWidget(btn)

    def _select_provider(self, provider_id: str) -> None:
        pid = str(provider_id or "").strip()
        if not pid or pid == self._selected_provider:
            return
        self._selected_provider = pid
        self._render()

    def _toggle_model(self, model_key: str, enabled: bool) -> None:
        key = str(model_key or "").strip()
        if not key or not self._selected_provider:
            return
        current = [k for k in (self._enabled_models.get(self._selected_provider, []) or []) if k != key]
        if enabled:
            current.append(key)
        self._enabled_models[self._selected_provider] = current
        btn = self._model_buttons.get(key)
        if btn:
            btn.apply_state(selected=False, active=enabled, tone="success", checked=enabled)
        prov_btn = self._provider_buttons.get(self._selected_provider)
        if prov_btn:
            prov_btn.apply_state(
                selected=True,
                active=bool(self._enabled_models.get(self._selected_provider)),
                tone="focus",
                checked=True,
            )
        self.settingsChanged.emit()

    def _apply_prompt_settings(self, settings: dict) -> None:
        self._updating_prompt_controls = True
        try:
            self._prompt_profile.clear()
            options = self._load_prompt_profile_options()
            for profile_id, label in options:
                self._prompt_profile.addItem(label, profile_id)
            self._prompt_profile.addItem("Custom", "custom")

            profile_id = str(settings.get("prompt_profile", "") or "").strip().lower() or "standard"
            index = self._prompt_profile.findData(profile_id)
            if index < 0:
                index = self._prompt_profile.findData("standard")
            if index < 0:
                index = 0
            self._prompt_profile.setCurrentIndex(index)
            self._prompt_custom.setPlainText(str(settings.get("prompt_custom", "") or ""))
            self._sync_prompt_visibility()
        finally:
            self._updating_prompt_controls = False

    @staticmethod
    def _load_prompt_profile_options() -> list[tuple[str, str]]:
        default_labels = {
            "brief": "Brief",
            "standard": "Standard",
            "detailed": "Detailed",
            "transcript_edit": "Transcript Edit",
        }
        default_order = ["brief", "standard", "detailed", "transcript_edit"]
        try:
            from aimn.plugins.prompt_manager import load_prompt_presets

            presets = load_prompt_presets()
        except Exception:
            presets = []
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        by_id: dict[str, str] = {}
        for item in presets:
            preset_id = str(getattr(item, "preset_id", "") or "").strip().lower()
            if not preset_id or preset_id == "custom":
                continue
            label = str(getattr(item, "label", "") or "").strip() or preset_id
            by_id[preset_id] = label
        for profile_id in default_order:
            label = by_id.get(profile_id, default_labels.get(profile_id, profile_id))
            ordered.append((profile_id, label))
            seen.add(profile_id)
        for item in presets:
            preset_id = str(getattr(item, "preset_id", "") or "").strip().lower()
            if not preset_id or preset_id in seen or preset_id == "custom":
                continue
            label = str(getattr(item, "label", "") or "").strip() or preset_id
            ordered.append((preset_id, label))
            seen.add(preset_id)
        return ordered

    def _selected_prompt_profile(self) -> str:
        value = str(self._prompt_profile.currentData() or "").strip().lower()
        return value or "standard"

    def _sync_prompt_visibility(self) -> None:
        show_custom = self._selected_prompt_profile() == "custom"
        self._prompt_custom.setVisible(show_custom)

    def _on_prompt_profile_changed(self, *_args) -> None:
        self._sync_prompt_visibility()
        if not self._updating_prompt_controls:
            self.settingsChanged.emit()

    def _on_prompt_custom_changed(self) -> None:
        if self._updating_prompt_controls:
            return
        if self._selected_prompt_profile() == "custom":
            self.settingsChanged.emit()

    @staticmethod
    def _clear_layout(layout) -> None:
        for i in reversed(range(layout.count())):
            item = layout.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()


class AiProcessingPanel(QGroupBox):
    settingsChanged = Signal()
    refreshModelsRequested = Signal(str)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__("AI Processing", parent)
        _mark_plain_group(self)
        self._density = "full"
        self.setProperty("density_level", "basic")
        self._provider_buttons: dict[str, StandardSelectableChip] = {}
        self._providers: list[tuple[str, str]] = []
        self._selected_provider_key: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(_SECTION_SPACING)

        hint = QLabel(
            "Choose semantic processing or an LLM provider. Provider tiles wrap to a second row automatically."
        )
        hint.setObjectName("pipelineMetaLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._providers_box = QGroupBox("Providers")
        _mark_plain_group(self._providers_box)
        providers_layout = QVBoxLayout(self._providers_box)
        providers_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        providers_layout.setSpacing(_SECTION_SPACING)
        self._providers_host = QWidget(self._providers_box)
        self._providers_flow = WrappingFlowLayout(self._providers_host, spacing=8)
        self._providers_host.setLayout(self._providers_flow)
        providers_layout.addWidget(self._providers_host)
        layout.addWidget(self._providers_box)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack, 1)

        self._semantic_panel = TextProcessingGroupedPanel(parent=self)
        self._semantic_panel.set_provider_selector_visible(False)
        self._semantic_panel.settingsChanged.connect(self._on_child_settings_changed)
        self._stack.addWidget(self._semantic_panel)

        self._llm_panel = LlmVariantsPanel(parent=self)
        self._llm_panel.set_provider_selector_visible(False)
        self._llm_panel.settingsChanged.connect(self._on_child_settings_changed)
        self._llm_panel.refreshModelsRequested.connect(self.refreshModelsRequested.emit)
        self._stack.addWidget(self._llm_panel)

    def apply_stage(self, stage) -> None:
        meta = getattr(stage, "ui_metadata", {}) or {}
        semantic_stage = SimpleNamespace(
            ui_metadata={
                "available_providers": list(meta.get("semantic_available_providers", []) or []),
                "provider_models": dict(meta.get("semantic_provider_models", {}) or {}),
                "enabled_models": dict(meta.get("semantic_enabled_models", {}) or {}),
                "selected_provider": str(meta.get("semantic_selected_provider", "") or "").strip(),
            }
        )
        self._semantic_panel.apply_stage(semantic_stage)
        self._llm_panel.apply_stage(stage)
        self._providers = []
        if semantic_stage.ui_metadata["available_providers"]:
            self._providers.append(("semantic", "Semantic"))
        self._providers.extend(
            [
                (str(pid), str(label))
                for pid, label in (meta.get("available_providers", []) or [])
                if str(pid).strip()
            ]
        )
        provider_ids = {pid for pid, _label in self._providers}
        preferred = str(self._selected_provider_key or "").strip()
        llm_selected = str(meta.get("selected_provider", "") or "").strip()
        if preferred not in provider_ids:
            preferred = ""
        if not preferred and llm_selected in provider_ids:
            preferred = llm_selected
        if not preferred and "semantic" in provider_ids:
            preferred = "semantic"
        if not preferred and self._providers:
            preferred = self._providers[0][0]
        self._selected_provider_key = preferred
        self._render_provider_buttons()
        self._show_selected_provider(self._selected_provider_key)
        self.set_density(self._density)

    def collect_settings(self) -> dict:
        payload = dict(self._llm_panel.collect_settings())
        semantic_payload = self._semantic_panel.collect_settings().get("__stage_payload__")
        if isinstance(semantic_payload, dict):
            payload["__extra_stage_payloads__"] = {"text_processing": semantic_payload}
        return payload

    def set_density(self, density: str) -> None:
        self._density = str(density or "").strip() or "full"
        if hasattr(self._llm_panel, "set_density"):
            self._llm_panel.set_density(self._density)

    def _render_provider_buttons(self) -> None:
        self._clear_layout(self._providers_flow)
        self._provider_buttons = {}
        for pid, label in self._providers:
            active = self._provider_has_selection(pid)
            selected = pid == self._selected_provider_key
            btn = StandardSelectableChip(_compact_chip_text(label))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            btn.apply_state(selected=selected, active=active, tone="focus", checked=selected)
            btn.clicked.connect(lambda _checked, _pid=pid: self._show_selected_provider(_pid))
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            btn.setToolTip(str(label or pid))
            self._provider_buttons[pid] = btn
            self._providers_flow.addWidget(btn)
        self._providers_box.setVisible(bool(self._providers))

    def _show_selected_provider(self, provider_key: str) -> None:
        pid = str(provider_key or "").strip()
        if not pid:
            return
        self._selected_provider_key = pid
        if pid == "semantic":
            self._stack.setCurrentWidget(self._semantic_panel)
        else:
            self._llm_panel.select_provider(pid)
            self._stack.setCurrentWidget(self._llm_panel)
        for tid, btn in self._provider_buttons.items():
            btn.apply_state(
                selected=tid == self._selected_provider_key,
                active=self._provider_has_selection(tid),
                tone="focus",
                checked=tid == self._selected_provider_key,
            )

    def _provider_has_selection(self, provider_key: str) -> bool:
        pid = str(provider_key or "").strip()
        if pid == "semantic":
            return self._semantic_panel.has_enabled_selection()
        return self._llm_panel.provider_has_enabled_models(pid)

    def _on_child_settings_changed(self) -> None:
        self._render_provider_buttons()
        self.settingsChanged.emit()

    @staticmethod
    def _clear_layout(layout) -> None:
        for i in reversed(range(layout.count())):
            item = layout.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()


class TranscriptionPanel(QGroupBox):
    """
    Drawer panel: transcription provider + installed models + language + quality preset.

    The goal is to make it obvious what is enabled, avoid dropdown hunting, and keep "advanced" knobs in Settings.
    """

    settingsChanged = Signal()

    _QUALITY_KEYS = [
        "reduce_hallucinations",
        "no_gpu",
        "no_fallback",
        "suppress_nst",
        "suppress_regex",
        "best_of",
        "beam_size",
        "temperature",
        "temperature_inc",
        "max_context",
        "max_len",
        "split_on_word",
        "initial_prompt",
        "carry_initial_prompt",
        "no_speech_threshold",
        "logprob_threshold",
        "vad_enable",
        "vad_model",
        "vad_threshold",
        "vad_min_speech_duration_ms",
        "vad_min_silence_duration_ms",
        "vad_max_speech_duration_s",
        "vad_speech_pad_ms",
        "vad_samples_overlap",
        "auto_retry_low_quality",
        "postprocess_cleanup",
        "retry_with_chunking",
        "chunk_seconds",
        "chunk_overlap_seconds",
        "pre_gate",
        "gate_frame_ms",
        "gate_min_speech_ms",
        "gate_min_silence_ms",
        "gate_pad_ms",
        "gate_speech_blend",
    ]
    _DEFAULT_PRESET = "silero_vad_ru"
    _PRESET_ORDER = [
        "silero_vad_ru",
    ]
    _PRESETS: dict[str, dict[str, object]] = {
        "silero_vad_ru": {
            "label": "Silero VAD RU (Experimental, Recommended)",
            "hint": (
                "Uses whisper.cpp external VAD with stricter anti-hallucination thresholds. "
                "Requires compatible model file at models/whisper/ggml-silero-v6.2.0.bin."
            ),
            "params": {
                "pre_gate": False,
                "gate_frame_ms": 100,
                "gate_min_speech_ms": 400,
                "gate_min_silence_ms": 250,
                "gate_pad_ms": 200,
                "gate_speech_blend": 0.25,
                "reduce_hallucinations": False,
                "no_gpu": False,
                "no_fallback": False,
                "suppress_nst": True,
                "suppress_regex": "(?i)(subtitle\\s+editor|caption\\s+editor|proofreader)",
                "best_of": None,
                "beam_size": 5,
                "temperature": None,
                "temperature_inc": None,
                "no_speech_threshold": 0.55,
                "logprob_threshold": -0.8,
                "max_context": 192,
                "max_len": 88,
                "split_on_word": True,
                "initial_prompt": "",
                "carry_initial_prompt": False,
                "vad_enable": True,
                "vad_model": "models/whisper/ggml-silero-v6.2.0.bin",
                "vad_threshold": 0.5,
                "vad_min_speech_duration_ms": 350,
                "vad_min_silence_duration_ms": 600,
                "vad_max_speech_duration_s": None,
                "vad_speech_pad_ms": 120,
                "vad_samples_overlap": 0.2,
                "auto_retry_low_quality": True,
                "postprocess_cleanup": False,
                "retry_with_chunking": True,
                "chunk_seconds": 90,
                "chunk_overlap_seconds": 2,
            },
        },
    }
    _PRESET_ALIASES = {
        "": _DEFAULT_PRESET,
        "default": _DEFAULT_PRESET,
        "recommended": _DEFAULT_PRESET,
        "recommended_basic": _DEFAULT_PRESET,
        "recovery_full": _DEFAULT_PRESET,
        "basic": _DEFAULT_PRESET,
        "anti": _DEFAULT_PRESET,
        "silero_vad": "silero_vad_ru",
        "silence_guard": _DEFAULT_PRESET,
        "no_fallback_exp": _DEFAULT_PRESET,
        "full_transcript_recovery": _DEFAULT_PRESET,
        "final_ru_gpu": _DEFAULT_PRESET,
        "gemini_optimized": _DEFAULT_PRESET,
    }
    _LANGUAGE_OPTIONS: list[tuple[str, str]] = [
        ("(not set)", ""),
        ("English (en)", "en"),
        ("Russian (ru)", "ru"),
        ("Ukrainian (uk)", "uk"),
        ("German (de)", "de"),
        ("French (fr)", "fr"),
        ("Spanish (es)", "es"),
        ("Italian (it)", "it"),
        ("Portuguese (pt)", "pt"),
        ("Polish (pl)", "pl"),
        ("Turkish (tr)", "tr"),
        ("Arabic (ar)", "ar"),
        ("Hindi (hi)", "hi"),
        ("Chinese (zh)", "zh"),
        ("Japanese (ja)", "ja"),
        ("Korean (ko)", "ko"),
    ]
    _WHISPER_VAD_MODEL_PATH = (
        r"C:\Project\apogee_ai_projects\apps\ai_meeting_manager\models\whisper\ggml-silero-v6.2.0.bin"
    )

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__("Transcription", parent)
        _mark_plain_group(self)
        self.setProperty("density_level", "basic")
        self._providers: list[tuple[str, str]] = []
        self._provider_buttons: dict[str, StandardSelectableChip] = {}
        self._models: list[str] = []
        self._model_buttons: dict[str, StandardSelectableChip] = {}
        self._selected_models: dict[str, list[str]] = {}
        self._enabled_providers: list[str] = []
        self._provider_params: dict[str, dict[str, object]] = {}
        self._selected_provider: str = ""
        self._selected_model: str = ""
        self._preset_capable_providers: set[str] = set()
        self._preset: str = self._DEFAULT_PRESET

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(_SECTION_SPACING)

        self._providers_box = QGroupBox("Providers")
        _mark_plain_group(self._providers_box)
        providers_layout = QVBoxLayout(self._providers_box)
        providers_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        providers_layout.setSpacing(_SECTION_SPACING)
        self._providers_host = QWidget(self._providers_box)
        self._providers_flow = WrappingFlowLayout(self._providers_host, spacing=8)
        self._providers_host.setLayout(self._providers_flow)
        providers_layout.addWidget(self._providers_host)
        layout.addWidget(self._providers_box)

        self._models_box = QGroupBox("Models")
        _mark_plain_group(self._models_box)
        models_layout = QVBoxLayout(self._models_box)
        models_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        models_layout.setSpacing(_SECTION_SPACING)
        self._models_host = QWidget()
        self._models_flow = WrappingFlowLayout(self._models_host, spacing=6)
        self._models_host.setLayout(self._models_flow)
        models_layout.addWidget(self._models_host, 1)
        self._models_empty = QLabel(
            "No Whisper models installed.\nDownload one in Settings → Whisper Advanced (and VAD model if needed)."
        )
        self._models_empty.setObjectName("pipelineMetaLabel")
        self._models_empty.setWordWrap(True)
        models_layout.addWidget(self._models_empty)
        layout.addWidget(self._models_box)

        language_box = QGroupBox("Language")
        _mark_plain_group(language_box)
        language_layout = QHBoxLayout(language_box)
        language_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        language_layout.setSpacing(6)
        self._language_mode = QComboBox()
        self._language_mode.addItem("Auto", "auto")
        self._language_mode.addItem("None", "none")
        self._language_mode.addItem("Forced", "forced")
        self._language_mode.currentIndexChanged.connect(lambda *_a: self._sync_controls())
        language_layout.addWidget(QLabel("Mode"))
        language_layout.addWidget(self._language_mode, 1)
        self._two_pass = QCheckBox("Two-pass detect")
        self._two_pass.stateChanged.connect(lambda *_a: self._emit())
        language_layout.addWidget(self._two_pass, 0)
        self._language_code = QComboBox()
        self._language_code.setEditable(False)
        self._populate_language_options("")
        self._language_code.currentIndexChanged.connect(lambda *_a: self._emit())
        language_layout.addWidget(QLabel("Language"))
        language_layout.addWidget(self._language_code, 1)
        layout.addWidget(language_box)

        preset_box = QGroupBox("Quality Preset")
        _mark_plain_group(preset_box)
        preset_layout = QVBoxLayout(preset_box)
        preset_layout.setContentsMargins(_SECTION_MARGIN, 0, _SECTION_MARGIN, 0)
        preset_layout.setSpacing(_SECTION_SPACING)
        self._preset_name = QLabel("")
        self._preset_name.setObjectName("pipelineMetaLabel")
        self._preset_name.setWordWrap(True)
        preset_layout.addWidget(self._preset_name)

        self._preset_hint = QLabel("")
        self._preset_hint.setObjectName("pipelineMetaLabel")
        self._preset_hint.setWordWrap(True)
        preset_layout.addWidget(self._preset_hint)
        layout.addWidget(preset_box)

    def apply_stage(self, stage) -> None:
        meta = getattr(stage, "ui_metadata", {}) or {}
        self._providers = [
            (str(pid), str(label)) for pid, label in meta.get("available_providers", []) if str(pid).strip()
        ]
        self._models = [str(m) for m in (meta.get("installed_models", []) or []) if str(m).strip()]
        self._preset_capable_providers = {
            str(pid).strip() for pid in (meta.get("transcription_preset_providers", []) or []) if str(pid).strip()
        }
        current = stage.current_settings if isinstance(stage.current_settings, dict) else {}

        self._provider_params = {}
        raw_params = meta.get("provider_params", {})
        if isinstance(raw_params, dict):
            for pid, params in raw_params.items():
                key = str(pid or "").strip()
                if not key or not isinstance(params, dict):
                    continue
                self._provider_params[key] = dict(params)

        self._selected_models = {}
        raw_selected_models = meta.get("selected_models", {})
        if isinstance(raw_selected_models, dict):
            for pid, models in raw_selected_models.items():
                key = str(pid or "").strip()
                if not key:
                    continue
                ordered = [str(model or "").strip() for model in (models or []) if str(model or "").strip()]
                if ordered:
                    self._selected_models[key] = ordered

        self._enabled_providers = [
            str(pid or "").strip()
            for pid in (meta.get("enabled_providers", []) or [])
            if str(pid or "").strip()
        ]
        if not self._selected_models:
            for pid, params in self._provider_params.items():
                model_id = str((params or {}).get("model", "") or "").strip()
                if model_id:
                    self._selected_models[pid] = [model_id]
        if not self._enabled_providers:
            fallback_provider = str(current.get("plugin_id", "") or "").strip()
            if fallback_provider:
                self._enabled_providers = [fallback_provider]

        self._selected_provider = str(meta.get("selected_provider", "") or current.get("plugin_id", "") or "").strip()
        if not self._selected_provider and self._enabled_providers:
            self._selected_provider = self._enabled_providers[0]
        if not self._selected_provider and self._providers:
            self._selected_provider = self._providers[0][0]

        available_ids = [pid for pid, _label in self._providers]
        available_set = set(available_ids)
        self._enabled_providers = [pid for pid in self._enabled_providers if pid in available_set]
        if self._selected_provider not in available_set:
            if self._enabled_providers:
                self._selected_provider = self._enabled_providers[0]
            elif available_ids:
                self._selected_provider = available_ids[0]
            else:
                self._selected_provider = ""

        seed_params = dict(current) if isinstance(current, dict) else {}
        for pid in available_ids:
            if pid not in self._provider_params:
                if pid == self._selected_provider:
                    self._provider_params[pid] = dict(seed_params)
                else:
                    self._provider_params[pid] = {}
        # Selected provider can be focused while inactive. In that case keep focus (blue)
        # but do not inherit an active model selection from another provider.
        if self._selected_provider and self._selected_provider not in set(self._enabled_providers):
            selected_existing = dict(self._provider_params.get(self._selected_provider, {}) or {})
            selected_existing["model"] = ""
            self._provider_params[self._selected_provider] = selected_existing
        available_models = set(self._models)
        filtered_selected_models: dict[str, list[str]] = {}
        for pid, models in self._selected_models.items():
            if pid not in available_set:
                continue
            ordered = [model for model in models if model in available_models] if available_models else list(models)
            if ordered:
                filtered_selected_models[pid] = ordered
        self._selected_models = filtered_selected_models
        self._enabled_providers = [pid for pid in self._enabled_providers if pid in self._selected_models]

        selected_params = dict(self._provider_params.get(self._selected_provider, {}) or {})
        selected_models = list(self._selected_models.get(self._selected_provider, []))
        if selected_models:
            selected_params["model"] = selected_models[0]
        self._load_controls_from_params(selected_params)
        self._render()
        self._apply_preset_selection(emit=False)
        self._sync_controls()

    def collect_settings(self) -> dict:
        self._store_selected_provider_params()

        enabled = [pid for pid in self._enabled_providers if str(pid or "").strip() and self._selected_models.get(str(pid))]
        selected_provider = str(self._selected_provider or "").strip()
        if not selected_provider and enabled:
            selected_provider = enabled[0]

        variants: list[dict] = []
        selected_params: dict[str, object] = {}
        selected_params_remove: list[str] = []
        for pid in enabled:
            params = dict(self._provider_params.get(pid, {}) or {})
            built_params, params_remove = self._finalize_provider_params(pid, params)
            models = list(self._selected_models.get(pid, []))
            for index, model_id in enumerate(models):
                variant_params = dict(built_params)
                variant_params["model"] = model_id
                variants.append({"plugin_id": pid, "params": variant_params})
                if pid == selected_provider and index == 0:
                    selected_params = dict(variant_params)
                    selected_params_remove = list(params_remove)
        if selected_provider and not selected_params:
            params = dict(self._provider_params.get(selected_provider, {}) or {})
            selected_params, selected_params_remove = self._finalize_provider_params(selected_provider, params)
            fallback_models = list(self._selected_models.get(selected_provider, []))
            if fallback_models:
                selected_params["model"] = fallback_models[0]

        stage_payload: dict[str, object] = {
            "plugin_id": selected_provider,
            "params": selected_params,
            "variants": variants,
        }
        if selected_params_remove:
            stage_payload["params_remove"] = selected_params_remove
        return {"__stage_payload__": stage_payload}

    def _render(self) -> None:
        self._clear_layout(self._providers_flow)
        self._clear_layout(self._models_flow)
        self._provider_buttons = {}
        self._model_buttons = {}
        enabled_set = set(self._enabled_providers)

        for pid, label in self._providers:
            selected = pid == self._selected_provider
            active = pid in enabled_set
            btn = StandardSelectableChip(_compact_chip_text(label))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            btn.apply_state(selected=selected, active=active, tone="focus", checked=selected)
            btn.clicked.connect(lambda _checked, _pid=pid: self._select_provider(_pid))
            btn.setToolTip(str(label or pid))
            self._provider_buttons[pid] = btn
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self._providers_flow.addWidget(btn)

        self._models_empty.setVisible(not bool(self._models))
        if not self._models:
            return
        active_models = list(self._selected_models.get(self._selected_provider, []))
        active_set = set(active_models)
        primary_model = active_models[0] if active_models else ""
        for model in self._models:
            selected = model in active_set
            btn = StandardSelectableChip(_compact_chip_text(model))
            btn.set_compact_mode(True, max_chars=_COMPACT_CHIP_MAX_CHARS)
            btn.apply_state(selected=(model == primary_model and selected), active=selected, tone="success", checked=selected)
            btn.clicked.connect(lambda checked, _m=model: self._toggle_model(_m, checked))
            btn.setToolTip(model)
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self._model_buttons[model] = btn
            self._models_flow.addWidget(btn)
        self._apply_preset_selection(emit=False)

    @staticmethod
    def _clear_layout(layout) -> None:
        for i in reversed(range(layout.count())):
            item = layout.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()

    def _select_provider(self, provider_id: str) -> None:
        pid = str(provider_id or "").strip()
        if not pid:
            return
        if pid == self._selected_provider:
            self._refresh_provider_button_styles()
            return
        self._store_selected_provider_params()
        self._selected_provider = pid
        if pid not in self._provider_params:
            self._provider_params[pid] = {}
        selected_params = dict(self._provider_params.get(self._selected_provider, {}) or {})
        selected_models = list(self._selected_models.get(pid, []))
        selected_params["model"] = selected_models[0] if selected_models else ""
        self._provider_params[pid] = selected_params
        self._load_controls_from_params(selected_params if isinstance(selected_params, dict) else {})
        self._render()
        self._sync_controls()
        self._emit()

    def _toggle_model(self, model_id: str, checked: bool) -> None:
        mid = str(model_id or "").strip()
        if not mid:
            return
        pid = str(self._selected_provider or "").strip()
        if not pid:
            return
        self._store_selected_provider_params()
        selected_models = list(self._selected_models.get(pid, []))
        if checked:
            if mid not in selected_models:
                selected_models.append(mid)
        else:
            selected_models = [model for model in selected_models if model != mid]

        if selected_models:
            self._selected_models[pid] = selected_models
            if pid not in set(self._enabled_providers):
                self._enabled_providers.append(pid)
            self._selected_model = selected_models[0]
        else:
            self._selected_models.pop(pid, None)
            self._enabled_providers = [item for item in self._enabled_providers if str(item or "").strip() != pid]
            self._selected_model = ""

        params = dict(self._provider_params.get(pid, {}) or {})
        params["model"] = self._selected_model
        self._provider_params[pid] = params
        self._refresh_model_button_styles(pid)
        self._refresh_provider_button_styles()
        self._emit()

    def _refresh_provider_button_styles(self) -> None:
        enabled_set = set(self._enabled_providers)
        for pid, btn in self._provider_buttons.items():
            selected = pid == self._selected_provider
            active = pid in enabled_set
            btn.apply_state(selected=selected, active=active, tone="focus", checked=selected)

    def _refresh_model_button_styles(self, provider_id: str) -> None:
        pid = str(provider_id or "").strip()
        selected_models = list(self._selected_models.get(pid, []))
        selected_set = set(selected_models)
        primary_model = selected_models[0] if selected_models else ""
        for model_id, btn in self._model_buttons.items():
            enabled = model_id in selected_set
            btn.apply_state(
                selected=enabled and model_id == primary_model,
                active=enabled,
                tone="success",
                checked=enabled,
            )

    def _store_selected_provider_params(self) -> None:
        pid = str(self._selected_provider or "").strip()
        if not pid:
            return
        mode = self._language_mode.currentData()
        if mode is None or str(mode).strip() == "":
            mode = str(self._language_mode.currentText() or "").strip().lower()
        code = str(self._language_code.currentData() or "").strip()
        existing = dict(self._provider_params.get(pid, {}) or {})
        selected_models = list(self._selected_models.get(pid, []))
        primary_model = selected_models[0] if selected_models else str(existing.get("model", "") or "").strip()
        existing.update(
            {
                "model": primary_model,
                "language_mode": mode,
                "language_code": code,
                "two_pass": bool(self._two_pass.isChecked()),
                "preset_profile": self._preset,
            }
        )
        self._provider_params[pid] = existing

    def _load_controls_from_params(self, params: dict) -> None:
        payload = dict(params or {})
        selected_models = list(self._selected_models.get(self._selected_provider, []))
        payload_model = str(payload.get("model", "") or "").strip()
        self._selected_model = selected_models[0] if selected_models else payload_model
        self._preset = self._normalize_preset(str(payload.get("preset_profile", "") or "").strip())
        mode = str(payload.get("language_mode", "") or "auto").strip().lower()
        two_pass = bool(payload.get("two_pass"))
        if mode == "auto_two_pass":
            mode = "auto"
            two_pass = True
        idx = self._language_mode.findData(mode)
        self._language_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self._two_pass.setChecked(two_pass)
        code = str(payload.get("language_code", "") or "").strip()
        self._populate_language_options(code)

    def _finalize_provider_params(self, provider_id: str, params: dict[str, object]) -> tuple[dict[str, object], list[str]]:
        finalized = dict(params or {})
        params_remove: list[str] = []
        preset = self._normalize_preset(str(finalized.get("preset_profile", "") or "").strip())
        finalized["preset_profile"] = preset
        if provider_id in self._preset_capable_providers:
            preset_spec = self._PRESETS.get(preset, self._PRESETS[self._DEFAULT_PRESET])
            overrides = preset_spec.get("params")
            if isinstance(overrides, dict):
                finalized.update(overrides)
            else:
                params_remove = list(self._QUALITY_KEYS)
        else:
            params_remove = list(self._QUALITY_KEYS)

        if finalized.get("language_mode") == "forced" and not str(finalized.get("language_code") or "").strip():
            finalized["language_code"] = "en"
        return finalized, params_remove

    def _normalize_preset(self, preset_id: str) -> str:
        return self._resolve_preset_id(preset_id)

    @classmethod
    def _resolve_preset_id(cls, preset_id: str) -> str:
        raw = str(preset_id or "").strip()
        mapped = cls._PRESET_ALIASES.get(raw, raw)
        if mapped in cls._PRESETS:
            return str(mapped)
        return cls._DEFAULT_PRESET

    @classmethod
    def preset_params_for(cls, preset_id: str) -> dict[str, object]:
        resolved = cls._resolve_preset_id(preset_id)
        spec = cls._PRESETS.get(resolved, cls._PRESETS[cls._DEFAULT_PRESET])
        params = spec.get("params")
        if not isinstance(params, dict):
            return {}
        return dict(params)

    def _on_preset_selected(self) -> None:
        selected = self._preset
        normalized = self._normalize_preset(selected)
        if normalized == self._preset:
            self._apply_preset_selection(emit=False)
            return
        self._preset = normalized
        self._apply_preset_selection(emit=False)
        self._emit()

    def _apply_preset_selection(self, *, emit: bool) -> None:
        self._preset = self._normalize_preset(self._preset)
        spec = self._PRESETS.get(self._preset, self._PRESETS[self._DEFAULT_PRESET])
        self._preset_name.setText(f"Active profile: {str(spec.get('label', self._preset) or self._preset)}")
        self._preset_hint.setText(str(spec.get("hint", "") or ""))
        if emit:
            self._emit()

    def _populate_language_options(self, current_code: str) -> None:
        code = str(current_code or "").strip().lower()
        values = {value for _label, value in self._LANGUAGE_OPTIONS}
        self._language_code.blockSignals(True)
        self._language_code.clear()
        for label, value in self._LANGUAGE_OPTIONS:
            self._language_code.addItem(label, value)
        if code and code not in values:
            self._language_code.insertItem(1, f"Custom ({code})", code)
        idx = self._language_code.findData(code)
        self._language_code.setCurrentIndex(idx if idx >= 0 else 0)
        self._language_code.blockSignals(False)

    def _sync_controls(self) -> None:
        raw = self._language_mode.currentData()
        if raw is None or str(raw).strip() == "":
            raw = str(self._language_mode.currentText() or "").strip().lower()
        mode = str(raw or "").strip()
        forced = mode == "forced"
        self._language_code.setEnabled(forced)
        self._two_pass.setEnabled((not forced) and mode in {"auto", "none"})
        self._emit()

    def _emit(self) -> None:
        self.settingsChanged.emit()
