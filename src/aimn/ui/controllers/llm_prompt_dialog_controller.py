from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QInputDialog, QLabel, QVBoxLayout, QWidget


class LlmPromptDialogController:
    @staticmethod
    def prompt_agenda_selection(
        *,
        parent: QWidget,
        agendas: list[dict],
        saved: dict,
        texts: dict[str, str] | None = None,
    ) -> dict | None:
        labels = dict(texts or {})

        def txt(key: str, default: str) -> str:
            return str(labels.get(key, default) or default)

        by_id = {str(item.get("id", "") or ""): item for item in agendas}
        has_saved_manual = bool(
            saved
            and not str(saved.get("agenda_id", "") or "").strip()
            and str(saved.get("agenda_text", "") or "").strip()
        )

        dialog = QDialog(parent)
        dialog.setWindowTitle(txt("title", "Planned Agenda"))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        intro = QLabel(
            txt(
                "intro",
                "Select the planned agenda to include in AI Processing prompt.\n"
                "The assistant will reuse approved topics and avoid duplicate entities.",
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        combo = QComboBox(dialog)
        combo.addItem(txt("none_option", "No planned agenda"), "__none__")
        for item in agendas:
            agenda_id = str(item.get("id", "") or "").strip()
            title = str(item.get("title", "") or "").strip() or agenda_id
            if not agenda_id:
                continue
            combo.addItem(title, agenda_id)
        if has_saved_manual:
            combo.addItem(txt("saved_manual_option", "Saved manual agenda"), "__saved_manual__")
        combo.addItem(txt("manual_option", "Manual agenda..."), "__manual__")
        saved_agenda_id = str(saved.get("agenda_id", "") or "").strip()
        if saved_agenda_id:
            idx = combo.findData(saved_agenda_id)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        elif has_saved_manual:
            idx = combo.findData("__saved_manual__")
            if idx >= 0:
                combo.setCurrentIndex(idx)
        layout.addWidget(combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(txt("confirm_button", "Use selection"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return None

        selected = str(combo.currentData() or "__none__").strip()
        if selected == "__none__":
            return {"agenda_id": "", "agenda_title": "", "agenda_text": ""}
        if selected == "__saved_manual__":
            return {
                "agenda_id": "",
                "agenda_title": str(saved.get("agenda_title", "") or "").strip()
                or txt("manual_title", "Manual planned agenda"),
                "agenda_text": str(saved.get("agenda_text", "") or "").strip(),
            }
        if selected == "__manual__":
            text, ok = QInputDialog.getMultiLineText(
                parent,
                txt("manual_dialog_title", "Manual Agenda"),
                txt("manual_dialog_prompt", "Enter planned agenda text for this run:"),
                str(saved.get("agenda_text", "") or "").strip(),
            )
            if not ok:
                return None
            agenda_text = str(text or "").strip()
            if not agenda_text:
                return {"agenda_id": "", "agenda_title": "", "agenda_text": ""}
            return {
                "agenda_id": "",
                "agenda_title": txt("manual_title", "Manual planned agenda"),
                "agenda_text": agenda_text,
            }

        item = by_id.get(selected)
        if not isinstance(item, dict):
            return {"agenda_id": "", "agenda_title": "", "agenda_text": ""}
        return {
            "agenda_id": str(item.get("id", "") or "").strip(),
            "agenda_title": str(item.get("title", "") or "").strip(),
            "agenda_text": str(item.get("text", "") or "").strip(),
        }
