from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _download_file(url: str, target: Path, *, progress_cb=None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".partial")
    if temp.exists():
        temp.unlink()
    request = urllib.request.Request(url, headers={"User-Agent": "AI-Meeting-Manager-Installer/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, temp.open("wb") as handle:
        total = int(response.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
            if callable(progress_cb) and total > 0:
                progress_cb(min(1.0, downloaded / total))
    temp.replace(target)


def _snapshot_download(model_id: str, target_root: Path) -> None:
    from huggingface_hub import snapshot_download

    env_overrides = {
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "NO_COLOR": "1",
    }
    previous = {key: os.environ.get(key) for key in env_overrides}
    os.environ.update(env_overrides)
    try:
        snapshot_download(repo_id=model_id, cache_dir=str(target_root))
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _is_certificate_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "certificate_verify_failed" in text or "self-signed certificate" in text


def _normalize_theme_id(raw: str) -> str:
    value = str(raw or "").strip().lower() or "light"
    allowed = {
        "light",
        "dark",
        "light_mono",
        "dark_mono",
        "light_emerald",
        "light_sunset",
    }
    return value if value in allowed else "light"


class PortableInstallerDialog(QDialog):
    def __init__(self, *, payload_zip: Path, manifest_path: Path) -> None:
        super().__init__(None)
        self._payload_zip = Path(payload_zip)
        self._manifest = _load_json(manifest_path)
        self._wizard = dict(self._manifest.get("first_run_wizard") or {})
        self._downloads = dict(self._wizard.get("downloads") or {})
        self._state_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._install_state: dict[str, Any] = {
            "phase": "idle",
            "message": "",
            "overall_progress": 0,
            "extract_progress": 0,
            "whisper_progress": 0,
            "summary_progress": 0,
            "semantic_indeterminate": False,
            "errors": [],
            "download_errors": [],
            "done": False,
            "target_dir": "",
        }

        self.setWindowTitle("AI Meeting Manager Free Portable Installer")
        self.resize(1040, 760)
        self.setModal(True)

        self._target_dir = str(Path.home() / "Documents" / "AI Meeting Manager Free Portable")
        self._ui_locale = "ru"
        self._ui_theme = "light"
        self._transcription_language = "auto"
        self._two_pass = False
        self._launch_after_install = True
        self._create_desktop_shortcut = True
        self._whisper_choices = self._default_choices("whisper")
        self._semantic_choices = self._default_choices("semantic")
        self._summary_choices = self._default_choices("summary")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self._stack = QStackedWidget(self)
        root.addWidget(self._stack, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(8)
        self._step_label = QLabel("")
        self._step_label.setObjectName("pipelineMetaLabel")
        nav.addWidget(self._step_label, 1)
        self._back_btn = QPushButton("Back")
        self._back_btn.clicked.connect(self._go_back)
        nav.addWidget(self._back_btn, 0)
        self._next_btn = QPushButton("Next")
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn, 0)
        root.addLayout(nav, 0)

        self._build_pages()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(300)
        self._poll_timer.timeout.connect(self._refresh_install_progress)
        self._poll_timer.start()
        self._update_nav()

    def _build_pages(self) -> None:
        self._stack.addWidget(self._build_intro_page())
        self._stack.addWidget(self._build_models_page())
        self._stack.addWidget(self._build_install_page())
        self._stack.addWidget(self._build_finish_page())

    def _build_intro_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._card(
            "Portable setup",
            "This installer extracts the portable app into the selected folder, applies first-run settings, "
            "and can download optional models before the first launch.",
        ))

        target_card = QFrame(page)
        target_card.setObjectName("stdCard")
        target_layout = QVBoxLayout(target_card)
        target_layout.setContentsMargins(16, 16, 16, 16)
        target_layout.setSpacing(8)
        target_layout.addWidget(self._title("Install location"))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._target_edit = QLineEdit(self._target_dir)
        row.addWidget(self._target_edit, 1)
        browse = QPushButton("Choose folder")
        browse.clicked.connect(self._pick_target_dir)
        row.addWidget(browse, 0)
        target_layout.addLayout(row)
        note = QLabel(
            "Portable mode keeps the application, settings, and downloaded models inside this folder."
        )
        note.setWordWrap(True)
        note.setObjectName("pipelineMetaLabel")
        target_layout.addWidget(note)
        layout.addWidget(target_card)

        prefs = QFrame(page)
        prefs.setObjectName("stdCard")
        prefs_layout = QVBoxLayout(prefs)
        prefs_layout.setContentsMargins(16, 16, 16, 16)
        prefs_layout.setSpacing(10)
        prefs_layout.addWidget(self._title("First-run settings"))

        self._ui_locale_buttons = self._choice_row(
            prefs_layout,
            "Application language",
            [
                ("ru", "Russian"),
                ("en", "English"),
            ],
            lambda value: self._set_attr("_ui_locale", value),
            self._ui_locale,
        )
        self._ui_theme_buttons = self._choice_row(
            prefs_layout,
            "Theme",
            [
                ("light", "Light"),
                ("dark", "Dark"),
                ("light_mono", "Light mono"),
                ("dark_mono", "Dark mono"),
            ],
            lambda value: self._set_attr("_ui_theme", value),
            self._ui_theme,
        )
        self._transcription_language_buttons = self._choice_row(
            prefs_layout,
            "Transcription language",
            [
                ("auto", "Auto"),
                ("ru", "Russian"),
                ("en", "English"),
            ],
            lambda value: self._set_attr("_transcription_language", value),
            self._transcription_language,
        )
        tx_note = QLabel(
            "Auto usually works well. For predictable single-language audio, selecting the language explicitly is safer."
        )
        tx_note.setWordWrap(True)
        tx_note.setObjectName("pipelineMetaLabel")
        prefs_layout.addWidget(tx_note)
        self._two_pass_box = QCheckBox("Enable two-pass transcription for difficult audio")
        prefs_layout.addWidget(self._two_pass_box)
        layout.addWidget(prefs)
        layout.addStretch(1)
        return page
    def _build_models_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_card(
            "1. Whisper",
            dict(self._downloads.get("whisper") or {}),
            "_whisper_choices",
        ))
        layout.addWidget(self._section_card(
            "2. Semantic",
            dict(self._downloads.get("semantic") or {}),
            "_semantic_choices",
        ))
        layout.addWidget(self._section_card(
            "3. Summary",
            dict(self._downloads.get("summary") or {}),
            "_summary_choices",
        ))
        note = QLabel(
            "On the next step the installer extracts the app and downloads any selected optional models."
        )
        note.setWordWrap(True)
        note.setObjectName("pipelineMetaLabel")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_install_page(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left = QFrame(page)
        left.setObjectName("stdCard")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(10)
        left_layout.addWidget(self._title("Install and download models"))
        self._install_message = QLabel("Installation has not started yet.")
        self._install_message.setWordWrap(True)
        left_layout.addWidget(self._install_message)

        self._overall_bar = QProgressBar(left)
        self._overall_bar.setRange(0, 100)
        left_layout.addWidget(self._overall_bar)

        self._extract_bar = self._labeled_progress(left_layout, "Extract application")
        self._whisper_bar = self._labeled_progress(left_layout, "Whisper models")
        self._semantic_bar = self._labeled_progress(left_layout, "Embedding models")
        self._summary_bar = self._labeled_progress(left_layout, "Summary models")

        self._launch_box = QCheckBox("Launch the app after installation")
        self._launch_box.setChecked(True)
        left_layout.addWidget(self._launch_box)
        self._shortcut_box = QCheckBox("Create a desktop shortcut")
        self._shortcut_box.setChecked(True)
        left_layout.addWidget(self._shortcut_box)
        left_layout.addStretch(1)
        layout.addWidget(left, 1)

        right = QFrame(page)
        right.setObjectName("stdCard")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(10)
        right_layout.addWidget(self._title("Quick start"))
        self._slides_box = QTextEdit(right)
        self._slides_box.setReadOnly(True)
        self._slides_box.setPlainText(self._slides_text())
        right_layout.addWidget(self._slides_box, 1)
        pro = self._wizard.get("pro_teaser")
        if isinstance(pro, dict):
            teaser = QLabel(
                f"{str(pro.get('title', '')).strip()}\n\n{str(pro.get('body', '')).strip()}"
            )
            teaser.setWordWrap(True)
            teaser.setObjectName("pipelineMetaLabel")
            right_layout.addWidget(teaser, 0)
        layout.addWidget(right, 1)
        return page
    def _build_finish_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._finish_card = self._card(
            "Installation complete",
            "The portable app has been installed. You can run it from the selected folder.",
        )
        layout.addWidget(self._finish_card)
        layout.addStretch(1)
        return page
    def _title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("panelTitle")
        label.setWordWrap(True)
        return label

    def _card(self, title: str, body: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("stdCard")
        card.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._title(title))
        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setObjectName("pipelineMetaLabel")
        layout.addWidget(body_label)
        return card

    def _choice_row(self, layout: QVBoxLayout, title: str, options: list[tuple[str, str]], on_pick, selected: str):
        layout.addWidget(QLabel(title))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        buttons: dict[str, QPushButton] = {}
        for value, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, picked=value: on_pick(picked))
            row.addWidget(btn, 0)
            buttons[value] = btn
        row.addStretch(1)
        layout.addLayout(row)
        self._apply_button_group_state(buttons, selected)
        return buttons

    def _section_card(self, fallback_title: str, spec: dict[str, Any], attr_name: str) -> QFrame:
        title = str(spec.get("title", "") or fallback_title).strip() or fallback_title
        description = str(spec.get("description", "") or "").strip()
        card = self._card(title, description)
        layout = card.layout()
        options = spec.get("options")
        buttons: dict[str, QCheckBox] = {}
        for option in options if isinstance(options, list) else []:
            if not isinstance(option, dict):
                continue
            option_id = str(option.get("id", "")).strip()
            if not option_id:
                continue
            inner = QFrame(card)
            inner.setObjectName("stdPanel")
            inner_layout = QVBoxLayout(inner)
            inner_layout.setContentsMargins(0, 4, 0, 4)
            inner_layout.setSpacing(6)
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(8)
            btn = QCheckBox(str(option.get("label", option_id) or option_id))
            btn.stateChanged.connect(
                lambda _state=0, picked=option_id: self._sync_multi_choice(attr_name, picked)
            )
            header.addWidget(btn, 0)
            size_hint = str(option.get("size_hint", "") or "").strip()
            if size_hint:
                size_label = QLabel(size_hint)
                size_label.setObjectName("pipelineMetaLabel")
                header.addWidget(size_label, 0)
            header.addStretch(1)
            inner_layout.addLayout(header)
            desc = QLabel(str(option.get("description", "") or "").strip())
            desc.setWordWrap(True)
            desc.setObjectName("pipelineMetaLabel")
            inner_layout.addWidget(desc)
            layout.addWidget(inner)
            buttons[option_id] = btn
        self._apply_check_group_state(buttons, list(getattr(self, attr_name, []) or []))
        setattr(self, f"{attr_name}_buttons", buttons)
        return card

    def _labeled_progress(self, layout: QVBoxLayout, title: str) -> QProgressBar:
        label = QLabel(title)
        label.setObjectName("statusMeta")
        layout.addWidget(label)
        bar = QProgressBar(self)
        bar.setRange(0, 100)
        layout.addWidget(bar)
        return bar

    def _slides_text(self) -> str:
        slides = self._wizard.get("slides")
        parts: list[str] = []
        for index, slide in enumerate(slides if isinstance(slides, list) else [], start=1):
            if not isinstance(slide, dict):
                continue
            title = str(slide.get("title", "") or f"Step {index}").strip()
            body = str(slide.get("body", "") or "").strip()
            parts.append(f"{index}. {title}\n{body}")
        if not parts:
            parts.append(
                "1. Add an audio or video file.\n"
                "2. Run the pipeline.\n"
                "3. Review transcript, semantic cleanup, and summary artifacts."
            )
        parts.append(
            "\nNotes:\n"
            "- The first launch can be slower while caches warm up.\n"
            "- Optional models can be downloaded now or later in Settings.\n"
            "- If a download fails, the app is still installed."
        )
        return "\n\n".join(parts)
    def _default_choice(self, section_key: str) -> str:
        section = dict(self._downloads.get(section_key) or {})
        for option in section.get("options") if isinstance(section.get("options"), list) else []:
            if isinstance(option, dict) and bool(option.get("default", False)):
                return str(option.get("id", "")).strip()
        options = section.get("options") if isinstance(section.get("options"), list) else []
        for option in options:
            if isinstance(option, dict):
                return str(option.get("id", "")).strip()
        return ""

    def _default_choices(self, section_key: str) -> list[str]:
        choice = self._default_choice(section_key)
        return [choice] if choice else []

    def _pick_target_dir(self) -> None:
        current = str(self._target_edit.text() or "").strip() or self._target_dir
        picked = QFileDialog.getExistingDirectory(self, "Choose install folder", current)
        if picked:
            self._target_edit.setText(picked)

    def _set_attr(self, name: str, value: str) -> None:
        setattr(self, name, value)
        buttons = getattr(self, f"{name}_buttons", None)
        if isinstance(buttons, dict):
            self._apply_button_group_state(buttons, value)

    def _apply_button_group_state(self, buttons: dict[str, QPushButton], selected: str) -> None:
        for key, button in buttons.items():
            active = key == selected
            button.setChecked(active)

    def _sync_multi_choice(self, attr_name: str, _changed_id: str) -> None:
        buttons = getattr(self, f"{attr_name}_buttons", None)
        if not isinstance(buttons, dict):
            return
        section_key = {
            "_whisper_choices": "whisper",
            "_semantic_choices": "semantic",
            "_summary_choices": "summary",
        }.get(attr_name, "")
        changed_option = self._selected_option(section_key, _changed_id) if section_key else None
        changed_is_noop = str((changed_option or {}).get("mode", "")).strip() in {
            "keep_bundled",
            "skip",
        }
        if changed_is_noop and buttons.get(_changed_id) and buttons[_changed_id].isChecked():
            for key, button in buttons.items():
                if key != _changed_id:
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
        elif not changed_is_noop and buttons.get(_changed_id) and buttons[_changed_id].isChecked():
            for key, button in buttons.items():
                option = self._selected_option(section_key, key) if section_key else None
                if str((option or {}).get("mode", "")).strip() in {"keep_bundled", "skip"}:
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
        selected = [key for key, button in buttons.items() if bool(button.isChecked())]
        setattr(self, attr_name, selected)

    def _apply_check_group_state(self, buttons: dict[str, QCheckBox], selected: list[str]) -> None:
        selected_set = {str(value) for value in selected}
        for key, button in buttons.items():
            button.setChecked(key in selected_set)

    def _go_back(self) -> None:
        index = self._stack.currentIndex()
        if index <= 0 or self._worker is not None:
            return
        self._stack.setCurrentIndex(index - 1)
        self._update_nav()

    def _go_next(self) -> None:
        index = self._stack.currentIndex()
        if index == 0:
            self._target_dir = str(self._target_edit.text() or "").strip()
            self._two_pass = bool(self._two_pass_box.isChecked())
            if not self._target_dir:
                QMessageBox.warning(self, "Install folder", "Choose a folder for the portable app.")
                return
            self._stack.setCurrentIndex(1)
            self._update_nav()
            return
        if index == 1:
            if not self._confirm_overwrite_if_needed():
                return
            self._stack.setCurrentIndex(2)
            self._launch_after_install = True
            self._start_install()
            self._update_nav()
            return
        if index == 2:
            if self._worker is None:
                return
            with self._state_lock:
                done = bool(self._install_state.get("done", False))
            if not done:
                return
            self._stack.setCurrentIndex(3)
            self._update_nav()
            return
        if index == 3:
            self.accept()

    def _confirm_overwrite_if_needed(self) -> bool:
        target = Path(self._target_dir)
        if not target.exists():
            return True
        entries = [entry for entry in target.iterdir()]
        if not entries:
            return True
        answer = QMessageBox.question(
            self,
            "Folder is not empty",
            "The selected folder already contains files. Continue and overwrite matching portable app files?",
        )
        return answer == QMessageBox.Yes

    def _update_nav(self) -> None:
        index = self._stack.currentIndex()
        labels = {
            0: "Step 1 of 4: folder and first-run settings",
            1: "Step 2 of 4: model selection",
            2: "Step 3 of 4: install and downloads",
            3: "Step 4 of 4: finish",
        }
        self._step_label.setText(labels.get(index, ""))
        self._back_btn.setVisible(index > 0 and index < 2 and self._worker is None)
        if index == 2:
            with self._state_lock:
                done = bool(self._install_state.get("done", False))
            self._next_btn.setText("Finish" if done else "Installing...")
            self._next_btn.setEnabled(done)
            return
        if index == 3:
            self._next_btn.setText("Done")
            self._next_btn.setEnabled(True)
            self._back_btn.setVisible(False)
            return
        self._next_btn.setText("Next")
        self._next_btn.setEnabled(True)

    def _start_install(self) -> None:
        if self._worker is not None:
            return
        self._launch_after_install = bool(self._launch_box.isChecked())
        self._create_desktop_shortcut = bool(self._shortcut_box.isChecked())
        self._worker = threading.Thread(target=self._run_install, name="aimn.portable_installer", daemon=True)
        self._worker.start()
        self._refresh_install_progress()

    def _run_install(self) -> None:
        target_dir = Path(self._target_dir)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            self._set_state(phase="extract", message="Extracting portable bundle", overall_progress=1)
            self._extract_payload(target_dir)
            self._set_state(phase="settings", message="Applying first-run settings", overall_progress=45)
            self._write_installed_settings(target_dir)
            self._download_optional_models(target_dir)
            if self._create_desktop_shortcut:
                self._create_desktop_shortcut_link(target_dir)
            self._set_state(
                phase="done",
                message="Installation complete",
                overall_progress=100,
                done=True,
                target_dir=str(target_dir),
            )
            if self._launch_after_install:
                self._launch_installed_app(target_dir)
        except Exception as exc:
            errors = [str(exc)]
            self._set_state(
                phase="error",
                message=f"Installation failed: {exc}",
                overall_progress=100,
                done=True,
                errors=errors,
            )

    def _extract_payload(self, target_dir: Path) -> None:
        with zipfile.ZipFile(self._payload_zip, "r") as archive:
            members = archive.infolist()
            total = max(1, len(members))
            for index, member in enumerate(members, start=1):
                archive.extract(member, target_dir)
                progress = int(index * 100 / total)
                overall = min(40, int(progress * 0.4))
                self._set_state(extract_progress=progress, overall_progress=overall)

    def _write_installed_settings(self, target_dir: Path) -> None:
        ui_settings_path = target_dir / "config" / "settings" / "ui.json"
        ui_payload = _load_json(ui_settings_path)
        ui_payload["ui.locale"] = self._ui_locale
        ui_payload["ui.theme"] = _normalize_theme_id(self._ui_theme)
        _write_json(ui_settings_path, ui_payload)

        tx_settings_path = target_dir / "config" / "settings" / "plugins" / "transcription.whisperadvanced.json"
        tx_payload = _load_json(tx_settings_path)
        if self._transcription_language == "auto":
            tx_payload["language_mode"] = "auto"
            tx_payload["language_code"] = ""
        else:
            tx_payload["language_mode"] = "manual"
            tx_payload["language_code"] = self._transcription_language
        tx_payload["two_pass"] = bool(self._two_pass)
        _write_json(tx_settings_path, tx_payload)

        pipeline_path = target_dir / "config" / "settings" / "pipeline" / "default.json"
        pipeline_payload = _load_json(pipeline_path)
        stages = pipeline_payload.get("stages")
        if not isinstance(stages, dict):
            stages = {}
            pipeline_payload["stages"] = stages
        tx_stage = stages.get("transcription")
        if not isinstance(tx_stage, dict):
            tx_stage = {}
            stages["transcription"] = tx_stage
        tx_params = tx_stage.get("params")
        if not isinstance(tx_params, dict):
            tx_params = {}
            tx_stage["params"] = tx_params
        tx_params["language_mode"] = tx_payload.get("language_mode", "auto")
        tx_params["language_code"] = tx_payload.get("language_code", "")
        tx_params["two_pass"] = bool(self._two_pass)
        _write_json(pipeline_path, pipeline_payload)

    def _download_optional_models(self, target_dir: Path) -> None:
        self._set_state(message="Checking selected optional models", overall_progress=50)

        whisper_options = [
            option for option in self._selected_options("whisper", self._whisper_choices)
            if str(option.get("mode", "")).strip() != "keep_bundled"
        ]
        if whisper_options:
            for index, whisper_option in enumerate(whisper_options, start=1):
                model_id = str(whisper_option.get("model_id", "") or whisper_option.get("id", "")).strip()
                download_url = str(whisper_option.get("download_url", "") or "").strip()
                file_name = str(whisper_option.get("file", "") or self._whisper_file_name(model_id)).strip()
                if not (model_id and download_url and file_name):
                    continue
                target = target_dir / "models" / "whisper" / file_name
                try:
                    self._set_state(message=f"Downloading Whisper model {model_id}", whisper_progress=1)
                    _download_file(
                        download_url,
                        target,
                        progress_cb=lambda value: self._set_state(
                            whisper_progress=max(1, int(value * 100)),
                            overall_progress=50 + int(value * 10),
                        ),
                    )
                    self._activate_whisper_model(target_dir, model_id)
                except Exception as exc:
                    self._record_download_error(
                        "Whisper",
                        model_id,
                        exc,
                        source=download_url,
                        target=target,
                    )
                finally:
                    self._set_state(
                        whisper_progress=int(index * 100 / max(1, len(whisper_options))),
                        overall_progress=60,
                    )
        else:
            self._set_state(whisper_progress=100)

        semantic_options = [
            option for option in self._selected_options("semantic", self._semantic_choices)
            if str(option.get("mode", "")).strip() != "skip"
        ]
        if semantic_options:
            semantic_blocked_reason = ""
            for semantic_option in semantic_options:
                model_id = str(semantic_option.get("model_id", "") or "").strip()
                if not model_id:
                    continue
                target = target_dir / "models" / "embeddings"
                if semantic_blocked_reason:
                    self._record_download_error(
                        "Embeddings",
                        model_id,
                        RuntimeError(f"download_skipped_after_previous_failure:{semantic_blocked_reason}"),
                        source=f"repo:{model_id}",
                        target=target,
                    )
                    continue
                try:
                    self._set_state(
                        message=f"Downloading embedding model {model_id}",
                        semantic_indeterminate=True,
                        overall_progress=62,
                    )
                    _snapshot_download(model_id, target)
                    self._activate_semantic_model(target_dir, model_id)
                except Exception as exc:
                    if _is_certificate_error(exc):
                        semantic_blocked_reason = "certificate_verify_failed"
                    self._record_download_error(
                        "Embeddings",
                        model_id,
                        exc,
                        source=f"repo:{model_id}",
                        target=target,
                    )
                finally:
                    self._set_state(semantic_indeterminate=False, overall_progress=80)
        else:
            self._set_state(semantic_indeterminate=False)

        summary_options = [
            option for option in self._selected_options("summary", self._summary_choices)
            if str(option.get("mode", "")).strip() != "skip"
        ]
        if summary_options:
            for index, summary_option in enumerate(summary_options, start=1):
                model_id = str(summary_option.get("model_id", "") or "").strip()
                download_url = str(summary_option.get("download_url", "") or "").strip()
                file_name = str(summary_option.get("file", "") or "").strip()
                quant = str(summary_option.get("quant", "") or "Q4_K_M").strip() or "Q4_K_M"
                if not (model_id and download_url and file_name):
                    continue
                target = target_dir / "models" / "llama" / file_name
                try:
                    self._set_state(
                        message=f"Downloading summary model {model_id}",
                        summary_progress=1,
                        overall_progress=82,
                    )
                    _download_file(
                        download_url,
                        target,
                        progress_cb=lambda value: self._set_state(
                            summary_progress=max(1, int(value * 100)),
                            overall_progress=82 + int(value * 16),
                        ),
                    )
                    self._activate_summary_model(target_dir, model_id, quant)
                except Exception as exc:
                    self._record_download_error(
                        "Summary",
                        model_id,
                        exc,
                        source=download_url,
                        target=target,
                    )
                finally:
                    self._set_state(
                        summary_progress=int(index * 100 / max(1, len(summary_options))),
                        overall_progress=98,
                    )
        else:
            self._set_state(summary_progress=100)
    def _activate_whisper_model(self, target_dir: Path, model_id: str) -> None:
        tx_settings_path = target_dir / "config" / "settings" / "plugins" / "transcription.whisperadvanced.json"
        tx_payload = _load_json(tx_settings_path)
        tx_payload["model"] = model_id
        tx_payload["model_id"] = model_id
        _write_json(tx_settings_path, tx_payload)

        pipeline_path = target_dir / "config" / "settings" / "pipeline" / "default.json"
        pipeline_payload = _load_json(pipeline_path)
        stages = pipeline_payload.get("stages")
        if not isinstance(stages, dict):
            return
        tx_stage = stages.get("transcription")
        if not isinstance(tx_stage, dict):
            return
        tx_params = tx_stage.get("params")
        if not isinstance(tx_params, dict):
            tx_params = {}
            tx_stage["params"] = tx_params
        tx_params["model"] = model_id
        tx_params["model_id"] = model_id
        _write_json(pipeline_path, pipeline_payload)

    def _activate_semantic_model(self, target_dir: Path, model_id: str) -> None:
        for plugin_file in (
            target_dir / "config" / "settings" / "plugins" / "text_processing.semantic_refiner.json",
            target_dir / "config" / "settings" / "plugins" / "text_processing.minutes_heuristic_v2.json",
        ):
            payload = _load_json(plugin_file)
            payload["embeddings_enabled"] = True
            payload["embeddings_model_id"] = model_id
            payload["embeddings_allow_download"] = False
            payload["allow_download"] = False
            _write_json(plugin_file, payload)

        pipeline_path = target_dir / "config" / "settings" / "pipeline" / "default.json"
        pipeline_payload = _load_json(pipeline_path)
        stages = pipeline_payload.get("stages")
        if not isinstance(stages, dict):
            return
        text_stage = stages.get("text_processing")
        if not isinstance(text_stage, dict):
            return
        params = text_stage.get("params")
        if not isinstance(params, dict):
            params = {}
            text_stage["params"] = params
        params["embeddings_model_id"] = model_id
        params["embeddings_allow_download"] = False
        params["allow_download"] = False
        _write_json(pipeline_path, pipeline_payload)

    def _activate_summary_model(self, target_dir: Path, model_id: str, quant: str) -> None:
        llm_settings_path = target_dir / "config" / "settings" / "plugins" / "llm.llama_cli.json"
        llm_payload = _load_json(llm_settings_path)
        llm_payload["model_id"] = model_id
        llm_payload["model_quant"] = quant
        llm_payload["model_path"] = ""
        llm_payload["ctx_size"] = 32768
        _write_json(llm_settings_path, llm_payload)

        pipeline_path = target_dir / "config" / "settings" / "pipeline" / "default.json"
        pipeline_payload = _load_json(pipeline_path)
        stages = pipeline_payload.get("stages")
        if not isinstance(stages, dict):
            return
        llm_stage = stages.get("llm_processing")
        if not isinstance(llm_stage, dict):
            return
        params = llm_stage.get("params")
        if not isinstance(params, dict):
            params = {}
            llm_stage["params"] = params
        params["model_id"] = model_id
        params["model_quant"] = quant
        params["model_path"] = ""
        params["ctx_size"] = 32768
        _write_json(pipeline_path, pipeline_payload)

    def _launch_installed_app(self, target_dir: Path) -> None:
        exe = target_dir / "AI Meeting Manager Core Free.exe"
        if exe.exists():
            try:
                subprocess.Popen([str(exe)], cwd=str(target_dir))
            except Exception:
                return

    def _create_desktop_shortcut_link(self, target_dir: Path) -> None:
        exe = target_dir / "AI Meeting Manager Core Free.exe"
        if not exe.exists():
            return
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        shortcut = desktop / "AI Meeting Manager Core Free.lnk"
        shortcut_arg = self._ps_single_quoted(str(shortcut))
        exe_arg = self._ps_single_quoted(str(exe))
        target_dir_arg = self._ps_single_quoted(str(target_dir))
        script = (
            "$shell = New-Object -ComObject WScript.Shell; "
            f"$shortcut = $shell.CreateShortcut({shortcut_arg}); "
            f"$shortcut.TargetPath = {exe_arg}; "
            f"$shortcut.WorkingDirectory = {target_dir_arg}; "
            f"$shortcut.IconLocation = {exe_arg}; "
            "$shortcut.Save()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self._record_download_error(
                "Desktop shortcut",
                str(shortcut),
                exc,
                target=shortcut,
            )

    @staticmethod
    def _ps_single_quoted(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _selected_option(self, section_key: str, option_id: str) -> dict[str, Any] | None:
        section = dict(self._downloads.get(section_key) or {})
        for option in section.get("options") if isinstance(section.get("options"), list) else []:
            if isinstance(option, dict) and str(option.get("id", "")).strip() == str(option_id or "").strip():
                return dict(option)
        return None

    def _selected_options(self, section_key: str, option_ids: list[str]) -> list[dict[str, Any]]:
        requested = {str(option_id or "").strip() for option_id in option_ids}
        if not requested:
            return []
        section = dict(self._downloads.get(section_key) or {})
        selected: list[dict[str, Any]] = []
        for option in section.get("options") if isinstance(section.get("options"), list) else []:
            if not isinstance(option, dict):
                continue
            option_id = str(option.get("id", "")).strip()
            if option_id in requested:
                selected.append(dict(option))
        return selected

    def _record_download_error(
        self,
        category: str,
        model_id: str,
        exc: Exception,
        *,
        source: str | Path | None = None,
        target: str | Path | None = None,
    ) -> None:
        model = str(model_id or "unknown").strip() or "unknown"
        parts = [
            f"{category} model {model}",
            f"error={exc}",
            "install_continued=true",
        ]
        if source:
            parts.append(f"source={source}")
        if target:
            parts.append(f"target={target}")
        hint = self._download_error_hint(exc)
        if hint:
            parts.append(f"hint={hint}")
        message = " | ".join(parts)
        with self._state_lock:
            existing = self._install_state.get("download_errors")
            if not isinstance(existing, list):
                existing = []
            existing.append(message)
            self._install_state["download_errors"] = existing
            self._install_state["errors"] = list(existing)

    @staticmethod
    def _download_error_hint(exc: Exception) -> str:
        text = str(exc)
        lowered = text.lower()
        if "certificate_verify_failed" in lowered or "self-signed certificate" in lowered:
            return (
                "Certificate verification failed. Check corporate proxy/root CA, "
                "or download this model later from Settings."
            )
        if "connecterror" in lowered or "timed out" in lowered or "urlopen error" in lowered:
            return "Network/proxy connection failed. Check connectivity or download later from Settings."
        return ""

    @staticmethod
    def _whisper_file_name(model_id: str) -> str:
        mapping = {
            "tiny": "ggml-tiny.bin",
            "base": "ggml-base.bin",
            "small": "ggml-small.bin",
            "small-q8_0": "ggml-small-q8_0.bin",
            "medium": "ggml-medium.bin",
            "medium-q8_0": "ggml-medium-q8_0.bin",
            "large-v3-turbo": "ggml-large-v3-turbo.bin",
            "large-v3-turbo-q5_0": "ggml-large-v3-turbo-q5_0.bin",
            "large-v3-turbo-q8_0": "ggml-large-v3-turbo-q8_0.bin",
            "large-v3": "ggml-large-v3.bin",
            "large-v3-q5_0": "ggml-large-v3-q5_0.bin",
        }
        return mapping.get(str(model_id or "").strip(), "")

    def _set_state(self, **updates: Any) -> None:
        with self._state_lock:
            self._install_state.update(updates)

    def _refresh_install_progress(self) -> None:
        with self._state_lock:
            state = dict(self._install_state)
        self._install_message.setText(str(state.get("message", "") or ""))
        self._overall_bar.setValue(int(state.get("overall_progress", 0) or 0))
        self._extract_bar.setValue(int(state.get("extract_progress", 0) or 0))
        self._whisper_bar.setValue(int(state.get("whisper_progress", 0) or 0))
        if bool(state.get("semantic_indeterminate", False)):
            self._semantic_bar.setRange(0, 0)
        else:
            self._semantic_bar.setRange(0, 100)
            self._semantic_bar.setValue(100 if int(state.get("overall_progress", 0) or 0) >= 80 else 0)
        self._summary_bar.setValue(int(state.get("summary_progress", 0) or 0))
        if self._stack.currentIndex() == 2:
            self._update_nav()
        if self._stack.currentIndex() == 3:
            self._update_nav()
        if bool(state.get("done", False)) and self._stack.currentIndex() == 2:
            errors = state.get("errors")
            if isinstance(errors, list) and errors:
                body = (
                    "The app was installed, but some optional model downloads failed.\n"
                    "You can download those models later from Settings.\n\n"
                    + "\n".join(str(item) for item in errors)
                )
            else:
                body = (
                    "The portable app was installed in:\n"
                    f"{state.get('target_dir', self._target_dir)}\n\n"
                    "You can now run the app from the install folder."
                )
            self._replace_finish_card("Installation complete", body)

    def _replace_finish_card(self, title: str, body: str) -> None:
        parent_layout = self._finish_card.parentWidget().layout()
        if parent_layout is None:
            return
        parent_layout.removeWidget(self._finish_card)
        self._finish_card.deleteLater()
        self._finish_card = self._card(title, body)
        parent_layout.insertWidget(0, self._finish_card)


def main() -> int:
    root = _resource_root()
    payload_zip = root / "core_free_release_payload.zip"
    manifest = root / "manifest.json"
    if not payload_zip.exists():
        QMessageBox.critical(None, "Installer", f"Payload archive not found:\n{payload_zip}")
        return 2
    _app = QApplication(sys.argv)
    dialog = PortableInstallerDialog(payload_zip=payload_zip, manifest_path=manifest)
    return 0 if dialog.exec() == QDialog.Accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())


