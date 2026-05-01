from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aimn.ui.widgets.standard_components import StandardSelectableChip


class EditAlgorithmsPanel(QGroupBox):
    def __init__(
        self,
        algorithms_provider: Callable[[], list[tuple[str, str]]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Edit Algorithms", parent)
        self._algorithms_provider = algorithms_provider
        self.setProperty("density_level", "basic")
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        layout.addWidget(self._list)

    def apply_stage(self, stage) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        selected = set(stage.current_settings.get("selected_models", []) or [])
        for label, plugin_id in self._algorithms_provider():
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, plugin_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked if plugin_id in selected else Qt.Unchecked)
            self._list.addItem(item)
        self._list.blockSignals(False)

    def collect_settings(self) -> dict:
        selected: list[str] = []
        for idx in range(self._list.count()):
            item = self._list.item(idx)
            if item.checkState() == Qt.Checked:
                selected.append(str(item.data(Qt.UserRole)))
        return {"selected_models": selected}


class LlmProviderPanel(QGroupBox):
    def __init__(
        self,
        providers_provider: Callable[[], list[tuple[str, str]]],
        models_provider: Callable[[str], list[tuple[str, str]]],
        prompt_presets_provider: Callable[[], list[dict]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Providers & Models", parent)
        self._providers_provider = providers_provider
        self._models_provider = models_provider
        self._prompt_presets_provider = prompt_presets_provider
        # provider -> ordered list of enabled models; first one is treated as "primary/selected"
        self._selected_models: dict[str, list[str]] = {}
        self._selected_provider: str = ""
        self._prompt_box: QGroupBox | None = None
        self._prompt_profile_id: str = ""
        self._prompt_profile_buttons: dict[str, StandardSelectableChip] = {}
        self.setProperty("density_level", "basic")

        layout = QVBoxLayout(self)
        selector = QWidget()
        selector_layout = QHBoxLayout(selector)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(10)

        providers_box = QGroupBox("Providers")
        providers_layout = QVBoxLayout(providers_box)
        providers_layout.setContentsMargins(10, 10, 10, 10)
        providers_layout.setSpacing(8)
        self._providers_scroll = QScrollArea()
        self._providers_scroll.setWidgetResizable(True)
        self._providers_scroll.setFrameShape(QScrollArea.NoFrame)
        self._providers_container = QWidget()
        self._providers_stack = QVBoxLayout(self._providers_container)
        self._providers_stack.setContentsMargins(0, 0, 0, 0)
        self._providers_stack.setSpacing(8)
        self._providers_scroll.setWidget(self._providers_container)
        providers_layout.addWidget(self._providers_scroll, 1)

        models_box = QGroupBox("Models")
        models_layout = QVBoxLayout(models_box)
        models_layout.setContentsMargins(10, 10, 10, 10)
        models_layout.setSpacing(8)
        self._models_scroll = QScrollArea()
        self._models_scroll.setWidgetResizable(True)
        self._models_scroll.setFrameShape(QScrollArea.NoFrame)
        self._models_container = QWidget()
        self._models_grid = QGridLayout(self._models_container)
        self._models_grid.setContentsMargins(0, 0, 0, 0)
        self._models_grid.setHorizontalSpacing(8)
        self._models_grid.setVerticalSpacing(8)
        self._models_scroll.setWidget(self._models_container)
        models_layout.addWidget(self._models_scroll, 1)

        selector_layout.addWidget(providers_box, 0)
        selector_layout.addWidget(models_box, 1)
        layout.addWidget(selector)

        self._provider_buttons: dict[str, StandardSelectableChip] = {}
        self._model_buttons: dict[str, StandardSelectableChip] = {}

        prompt_box = QGroupBox("Prompt")
        self._prompt_box = prompt_box
        prompt_layout = QVBoxLayout(prompt_box)
        prompt_layout.addWidget(QLabel("Profile"))
        self._prompt_profiles_host = QWidget()
        self._prompt_profiles_layout = QHBoxLayout(self._prompt_profiles_host)
        self._prompt_profiles_layout.setContentsMargins(0, 0, 0, 0)
        self._prompt_profiles_layout.setSpacing(8)
        prompt_layout.addWidget(self._prompt_profiles_host)

        self._prompt_language = QComboBox()
        self._prompt_language.setEditable(True)
        self._prompt_language.setPlaceholderText("Prompt language override")
        prompt_layout.addWidget(self._prompt_language)

        self._prompt_max_words = QComboBox()
        self._prompt_max_words.setEditable(True)
        self._prompt_max_words.setPlaceholderText("Max words")
        prompt_layout.addWidget(self._prompt_max_words)

        self._prompt_custom = QTextEdit()
        self._prompt_custom.setPlaceholderText("Custom prompt (optional)")
        prompt_layout.addWidget(self._prompt_custom)
        layout.addWidget(prompt_box)

    def apply_stage(self, stage) -> None:
        selected = stage.current_settings.get("selected_models", {})
        if isinstance(selected, dict):
            self._selected_models = {
                str(provider_id): [str(m) for m in (models or []) if str(m)]
                for provider_id, models in selected.items()
            }
        else:
            self._selected_models = {}

        providers = stage.current_settings.get("selected_providers", [])
        self._selected_provider = str(providers[0]) if providers else ""
        self._render_providers()
        self._render_models_for(self._selected_provider or self._first_provider_id())
        self._apply_prompt(stage.current_settings)

    def collect_settings(self) -> dict:
        selected_providers = [pid for pid, models in self._selected_models.items() if models]
        return {
            "selected_providers": selected_providers,
            "selected_models": {
                provider_id: list(models) for provider_id, models in self._selected_models.items()
            },
            "prompt_profile": self._prompt_profile_id,
            "prompt_custom": self._prompt_custom.toPlainText().strip(),
            "prompt_language": self._prompt_language.currentText().strip(),
            "prompt_max_words": self._prompt_max_words.currentText().strip(),
        }

    def _first_provider_id(self) -> str:
        providers = self._providers_provider()
        return str(providers[0][0]) if providers else ""

    def _render_providers(self) -> None:
        for i in reversed(range(self._providers_stack.count())):
            item = self._providers_stack.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._provider_buttons = {}

        providers = self._providers_provider()
        if not self._selected_provider and providers:
            self._selected_provider = str(providers[0][0])

        for provider_id, label in providers:
            pid = str(provider_id)
            btn = StandardSelectableChip(str(label))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _checked=False, p=pid: self._select_provider(p))
            btn.setToolTip(pid)
            self._providers_stack.addWidget(btn)
            self._provider_buttons[pid] = btn

        self._providers_stack.addStretch(1)
        self._refresh_provider_styles()

    def _select_provider(self, provider_id: str) -> None:
        pid = str(provider_id or "").strip()
        if not pid:
            return
        self._selected_provider = pid
        self._refresh_provider_styles()
        self._render_models_for(pid)

    def _refresh_provider_styles(self) -> None:
        for pid, btn in self._provider_buttons.items():
            has_models = bool(self._selected_models.get(pid))
            selected = pid == self._selected_provider
            btn.apply_state(selected=selected, active=has_models, tone="focus", checked=selected)

    def _render_models_for(self, provider_id: str) -> None:
        pid = str(provider_id or "").strip()
        for i in reversed(range(self._models_grid.count())):
            item = self._models_grid.takeAt(i)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._model_buttons = {}
        if not pid:
            return

        models = self._models_provider(pid)
        selected = list(self._selected_models.get(pid, []))
        selected_set = set(selected)
        primary = selected[0] if selected else ""

        cols = 2
        for idx, (label, model_id) in enumerate(models):
            mid = str(model_id)
            row = idx // cols
            col = idx % cols
            btn = StandardSelectableChip(str(label))
            btn.setChecked(mid in selected_set)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda checked=False, m=mid: self._toggle_model(m, checked))
            btn.pressed.connect(lambda m=mid: self._promote_primary(m))
            btn.setToolTip(mid)
            self._models_grid.addWidget(btn, row, col)
            self._model_buttons[mid] = btn

        self._models_grid.setRowStretch((len(models) // cols) + 1, 1)
        self._refresh_model_styles(pid, primary)

    def _toggle_model(self, model_id: str, checked: bool) -> None:
        pid = self._selected_provider
        if not pid:
            return
        models = list(self._selected_models.get(pid, []))
        mid = str(model_id)
        if checked:
            if mid not in models:
                models.append(mid)
        else:
            models = [m for m in models if m != mid]
        if models:
            self._selected_models[pid] = models
        elif pid in self._selected_models:
            del self._selected_models[pid]
        primary = models[0] if models else ""
        self._refresh_provider_styles()
        self._refresh_model_styles(pid, primary)

    def _promote_primary(self, model_id: str) -> None:
        pid = self._selected_provider
        if not pid:
            return
        models = list(self._selected_models.get(pid, []))
        mid = str(model_id)
        if mid not in models:
            return
        models = [mid] + [m for m in models if m != mid]
        self._selected_models[pid] = models
        self._refresh_model_styles(pid, mid)

    def _refresh_model_styles(self, provider_id: str, primary_model_id: str) -> None:
        pid = str(provider_id or "")
        primary = str(primary_model_id or "")
        selected_set = set(self._selected_models.get(pid, []))
        for mid, btn in self._model_buttons.items():
            enabled = mid in selected_set
            selected = enabled and mid == primary
            btn.apply_state(selected=selected, active=enabled, tone="success", checked=enabled)

    def _apply_prompt(self, settings: dict) -> None:
        presets = self._prompt_presets_provider()
        for i in reversed(range(self._prompt_profiles_layout.count())):
            item = self._prompt_profiles_layout.takeAt(i)
            if item and item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
        self._prompt_profile_buttons = {}
        for preset in presets:
            profile_id = str(preset.get("id", "")).strip()
            if not profile_id:
                continue
            label = str(preset.get("label", profile_id)).strip() or profile_id
            btn = StandardSelectableChip(label)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setMinimumHeight(32)
            btn.set_compact_mode(True, max_chars=22)
            btn.clicked.connect(lambda _checked=False, pid=profile_id: self._select_prompt_profile(pid))
            self._prompt_profiles_layout.addWidget(btn, 0)
            self._prompt_profile_buttons[profile_id] = btn
        custom_btn = StandardSelectableChip("Custom")
        custom_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        custom_btn.setMinimumHeight(32)
        custom_btn.clicked.connect(lambda _checked=False: self._select_prompt_profile("custom"))
        self._prompt_profiles_layout.addWidget(custom_btn, 0)
        self._prompt_profile_buttons["custom"] = custom_btn
        self._prompt_profiles_layout.addStretch(1)

        profile_id = str(settings.get("prompt_profile", "")).strip()
        if not profile_id or profile_id not in self._prompt_profile_buttons:
            profile_id = "custom"
        self._select_prompt_profile(profile_id)
        self._prompt_custom.setPlainText(str(settings.get("prompt_custom", "") or ""))
        self._prompt_language.setCurrentText(str(settings.get("prompt_language", "") or ""))
        max_words = settings.get("prompt_max_words")
        self._prompt_max_words.setCurrentText("" if max_words is None else str(max_words))

    def _select_prompt_profile(self, profile_id: str) -> None:
        selected_id = str(profile_id or "").strip() or "custom"
        if selected_id not in self._prompt_profile_buttons:
            selected_id = "custom"
        self._prompt_profile_id = selected_id
        for pid, btn in self._prompt_profile_buttons.items():
            selected = pid == selected_id
            btn.apply_state(selected=selected, active=selected, tone="focus", checked=selected)

    def set_density(self, density: str) -> None:
        if self._prompt_box:
            self._prompt_box.setVisible(density == "full")


class TranscriptionExtrasPanel(QGroupBox):
    def __init__(
        self,
        status_provider: Callable[[], str],
        download_callback: Callable[[], None],
        remove_callback: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Model", parent)
        self._status_provider = status_provider
        self.setProperty("density_level", "advanced")
        layout = QVBoxLayout(self)
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Status"))
        self._status_label = QLabel("unknown")
        status_row.addWidget(self._status_label)
        layout.addLayout(status_row)

        actions = QHBoxLayout()
        self._download_btn = QPushButton("Download")
        self._remove_btn = QPushButton("Remove")
        self._download_btn.clicked.connect(download_callback)
        self._remove_btn.clicked.connect(remove_callback)
        actions.addWidget(self._download_btn)
        actions.addWidget(self._remove_btn)
        actions.addStretch()
        layout.addLayout(actions)

    def apply_stage(self, stage) -> None:
        self._status_label.setText(self._status_provider())

    def collect_settings(self) -> dict:
        return {}


class EmbeddingsExtrasPanel(QGroupBox):
    def __init__(
        self,
        status_provider: Callable[[], str],
        download_callback: Callable[[], None],
        remove_callback: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Embeddings", parent)
        self._status_provider = status_provider
        self.setProperty("density_level", "advanced")
        layout = QVBoxLayout(self)
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Status"))
        self._status_label = QLabel("unknown")
        status_row.addWidget(self._status_label)
        layout.addLayout(status_row)

        actions = QHBoxLayout()
        self._download_btn = QPushButton("Download")
        self._remove_btn = QPushButton("Remove")
        self._download_btn.clicked.connect(download_callback)
        self._remove_btn.clicked.connect(remove_callback)
        actions.addWidget(self._download_btn)
        actions.addWidget(self._remove_btn)
        actions.addStretch()
        layout.addLayout(actions)

    def apply_stage(self, stage) -> None:
        self._status_label.setText(self._status_provider())

    def collect_settings(self) -> dict:
        return {}
