from __future__ import annotations

from PySide6.QtWidgets import (
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

TextEditorWidget = QTextEdit | QPlainTextEdit


class TextEditorController:
    @staticmethod
    def build_readonly_plain_text(text: str) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(str(text or ""))
        view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        return view

    @staticmethod
    def extract_text_editor(widget: QWidget | None) -> TextEditorWidget | None:
        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            return widget
        if widget is None:
            return None
        found = widget.findChild(QTextEdit)
        if isinstance(found, QTextEdit):
            return found
        plain = widget.findChild(QPlainTextEdit)
        return plain if isinstance(plain, QPlainTextEdit) else None
