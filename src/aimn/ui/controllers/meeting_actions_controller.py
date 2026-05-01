from __future__ import annotations

import re
from typing import Callable

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout, QWidget

from aimn.ui.controllers.meeting_action_flow_controller import MeetingRerunSelection


class MeetingActionsController:
    def __init__(
        self,
        *,
        paths,
        meeting_service,
        artifact_service,
        settings_store,
        catalog_service,
        action_service,
        rename_settings_id: str,
        rename_modes: set[str],
    ) -> None:
        self._paths = paths
        self._meeting_service = meeting_service
        self._artifact_service = artifact_service
        self._settings_store = settings_store
        self._catalog_service = catalog_service
        self._action_service = action_service
        self._rename_settings_id = str(rename_settings_id or "").strip()
        self._rename_modes = {str(item or "").strip().lower() for item in (rename_modes or set()) if str(item or "").strip()}

    @staticmethod
    def default_rerun_stage(stage_order: list[str], is_stage_disabled: Callable[[str], bool]) -> str:
        for stage_id in stage_order:
            if not is_stage_disabled(stage_id):
                return stage_id
        return ""

    @staticmethod
    def confirm_source_rename(
        parent: QWidget,
        *,
        title: str = "Rename source file?",
        message: str = (
            "Rename original source file too?\n\n"
            "This works only for files in app-managed import folders.\n"
            "External files stay unchanged for safety."
        ),
    ) -> bool:
        reply = QMessageBox.question(
            parent,
            str(title or "Rename source file?"),
            str(message or ""),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    @staticmethod
    def prompt_rerun_stage(
        *,
        parent: QWidget,
        stage_order: list[str],
        is_stage_disabled: Callable[[str], bool],
        default_stage_id: str,
        stage_display_name: Callable[[str], str],
        no_stages_title: str = "No Stages Enabled",
        no_stages_message: str = "Enable at least one stage to rerun.",
        dialog_title: str = "Run from stage",
        description: str = "Choose the pipeline stage to start from:",
        run_label: str = "Run",
        force_replace_label: str = "Force replace downstream artifacts",
        force_replace_hint: str = (
            "Use this when the selected stage produced a bad result and all downstream artifacts"
            " must be rebuilt from the new output."
        ),
    ) -> MeetingRerunSelection:
        stages = [sid for sid in stage_order if not is_stage_disabled(sid)]
        if not stages:
            QMessageBox.warning(
                parent,
                str(no_stages_title or "No Stages Enabled"),
                str(no_stages_message or "Enable at least one stage to rerun."),
            )
            return MeetingRerunSelection()

        dialog = QDialog(parent)
        dialog.setWindowTitle(str(dialog_title or "Run from stage"))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        label = QLabel(str(description or "Choose the pipeline stage to start from:"))
        layout.addWidget(label)

        combo = QComboBox(dialog)
        for stage_id in stages:
            combo.addItem(stage_display_name(stage_id), stage_id)
        default_idx = combo.findData(str(default_stage_id or "").strip())
        if default_idx >= 0:
            combo.setCurrentIndex(default_idx)
        layout.addWidget(combo)

        force_replace = QCheckBox(str(force_replace_label or "Force replace downstream artifacts"), dialog)
        force_replace.setToolTip(str(force_replace_hint or ""))
        layout.addWidget(force_replace)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(str(run_label or "Run"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return MeetingRerunSelection()
        return MeetingRerunSelection(
            stage_id=str(combo.currentData() or "").strip(),
            force_replace_downstream=force_replace.isChecked(),
        )

    def meeting_topic_suggestions(self, base_name: str, *, meeting: object | None = None) -> list[str]:
        plugin_id, action_id = self.meeting_topic_suggestions_provider()
        if not plugin_id or not action_id:
            return []
        payload = {"base_name": str(base_name or "").strip()}
        if meeting is not None:
            payload["meeting_id"] = str(getattr(meeting, "meeting_id", "") or "").strip()
        try:
            result = self._action_service.invoke_action(plugin_id, action_id, payload)
        except Exception:
            return []
        status = str(getattr(result, "status", "") or "").strip().lower()
        if status not in {"ok", "success"}:
            return []
        return self.normalize_topic_suggestions(getattr(result, "data", None))

    def meeting_topic_suggestions_provider(self) -> tuple[str, str]:
        catalog = self._catalog_service.load().catalog
        for plugin in catalog.enabled_plugins():
            caps = plugin.capabilities if isinstance(getattr(plugin, "capabilities", None), dict) else {}
            meeting_caps = caps.get("meeting_rename") if isinstance(caps, dict) else None
            if not isinstance(meeting_caps, dict):
                continue
            topic_caps = meeting_caps.get("topic_suggestions")
            action_id = ""
            if isinstance(topic_caps, dict):
                action_id = str(topic_caps.get("action", "") or "").strip()
            elif bool(topic_caps):
                action_id = "suggest_topics"
            if action_id:
                return str(plugin.plugin_id or "").strip(), action_id
        return "", ""

    def meeting_rename_policy(self) -> tuple[str, bool]:
        payload = self._settings_store.get_settings(self._rename_settings_id, include_secrets=False)
        mode_raw = str(payload.get("rename_mode", "") if isinstance(payload, dict) else "").strip().lower()
        mode = mode_raw if mode_raw in self._rename_modes else "artifacts_and_manifest"
        allow_source = bool(payload.get("allow_source_rename", False)) if isinstance(payload, dict) else False
        return mode, allow_source

    @staticmethod
    def normalize_topic_suggestions(payload: object) -> list[str]:
        data = payload if isinstance(payload, dict) else {}
        raw = None
        if isinstance(data, dict):
            raw = data.get("suggestions")
            if raw is None:
                raw = data.get("topics")
            if raw is None:
                raw = data.get("candidates")
        values: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    text = str(item.get("title", "") or item.get("topic", "")).strip()
                else:
                    text = str(item or "").strip()
                if text:
                    values.append(text)
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = re.sub(r"\s+", " ", value.strip().lower())
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(value.strip())
            if len(unique) >= 12:
                break
        return unique

    def delete_meeting_files(self, base_name: str) -> None:
        base = str(base_name or "").strip()
        if not base:
            return
        output_dir = self._paths.output_dir
        meeting = None
        try:
            meeting = self._meeting_service.load_by_base_name(base)
        except Exception:
            meeting = None
        relpaths: set[str] = set()
        if meeting:
            for item in self._artifact_service.list_artifacts(meeting, include_internal=True):
                relpaths.add(item.relpath)
        for relpath in relpaths:
            try:
                path = output_dir / relpath
                if path.exists():
                    path.unlink()
            except Exception:
                continue
        meeting_path = output_dir / f"{base}__MEETING.json"
        try:
            if meeting_path.exists():
                meeting_path.unlink()
        except Exception:
            return

    @staticmethod
    def meeting_display_title(meeting: object) -> str:
        display_title = str(getattr(meeting, "display_title", "") or "").strip()
        if display_title:
            return display_title
        try:
            source = getattr(meeting, "source", None)
            items = getattr(source, "items", None) if source else None
            if items:
                input_name = str(getattr(items[0], "input_filename", "") or "").strip()
                if input_name:
                    return input_name
        except Exception:
            pass
        base = str(getattr(meeting, "base_name", "") or "").strip()
        if base:
            return base
        return str(getattr(meeting, "meeting_id", "") or "").strip()
