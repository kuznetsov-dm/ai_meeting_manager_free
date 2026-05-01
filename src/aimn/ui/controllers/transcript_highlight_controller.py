from __future__ import annotations

import re
from collections.abc import Sequence

from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit

from aimn.ui.controllers.transcript_evidence_controller import TranscriptSuggestionSpan


TextEditorWidget = QTextEdit | QPlainTextEdit


class TranscriptHighlightController:
    @staticmethod
    def management_overlay_selections(
        editor: TextEditorWidget,
        spans: Sequence[TranscriptSuggestionSpan],
    ) -> list[QTextEdit.ExtraSelection]:
        selections: list[QTextEdit.ExtraSelection] = []
        if not spans:
            return selections
        dark = int(editor.palette().color(QPalette.Base).lightness()) < 128
        palette = {
            "task": ("#B45309", "#F59E0B") if dark else ("#FDE68A", "#B45309"),
            "project": ("#0369A1", "#38BDF8") if dark else ("#BFDBFE", "#1D4ED8"),
            "agenda": ("#166534", "#4ADE80") if dark else ("#BBF7D0", "#166534"),
        }
        for span in spans:
            bg_hex, fg_hex = palette.get(span.kind, ("#6B7280", "#E5E7EB") if dark else ("#E5E7EB", "#374151"))
            cursor = QTextCursor(editor.document())
            cursor.setPosition(int(span.left))
            cursor.setPosition(int(span.right), QTextCursor.KeepAnchor)
            fmt = QTextCharFormat()
            bg = QColor(bg_hex)
            bg.setAlpha(46 if dark else 34)
            fmt.setBackground(bg)
            fmt.setUnderlineStyle(QTextCharFormat.SingleUnderline)
            fmt.setUnderlineColor(QColor(fg_hex))
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
        return selections

    @staticmethod
    def focus_range_selections(
        editor: TextEditorWidget,
        *,
        start: int,
        end: int,
        terms: Sequence[str] | None = None,
    ) -> list[QTextEdit.ExtraSelection]:
        length = len(editor.toPlainText())
        left = max(0, min(int(start), length))
        right = max(left, min(int(end), length))
        text = str(editor.toPlainText() or "")
        selections: list[QTextEdit.ExtraSelection] = []

        if terms:
            wanted: list[str] = []
            seen_terms: set[str] = set()
            for token in terms:
                value = str(token or "").strip()
                if len(value) < 1:
                    continue
                key = value.casefold()
                if key in seen_terms:
                    continue
                seen_terms.add(key)
                wanted.append(value)
                if len(wanted) >= 96:
                    break
            wanted.sort(key=lambda item: len(str(item or "")), reverse=True)
            if wanted and text:
                dark = int(editor.palette().color(QPalette.Base).lightness()) < 128
                term_fmt = QTextCharFormat()
                if dark:
                    term_fmt.setBackground(QColor("#1D4ED8"))
                    term_fmt.setForeground(QColor("#F8FAFC"))
                else:
                    term_fmt.setBackground(QColor("#F59E0B"))
                    term_fmt.setForeground(QColor("#111827"))
                term_fmt.setFontWeight(700)
                used: set[tuple[int, int]] = set()
                max_matches = 1600
                for token in wanted:
                    pattern = re.compile(re.escape(str(token)), flags=re.IGNORECASE)
                    for match in pattern.finditer(text):
                        match_left = int(match.start())
                        match_right = int(match.end())
                        if match_right <= match_left:
                            continue
                        key = (match_left, match_right)
                        if key in used:
                            continue
                        used.add(key)
                        cursor = QTextCursor(editor.document())
                        cursor.setPosition(match_left)
                        cursor.setPosition(match_right, QTextCursor.KeepAnchor)
                        sel = QTextEdit.ExtraSelection()
                        sel.cursor = cursor
                        sel.format = term_fmt
                        selections.append(sel)
                        if len(selections) >= max_matches:
                            break
                    if len(selections) >= max_matches:
                        break

        range_cursor = QTextCursor(editor.document())
        range_cursor.setPosition(left)
        range_cursor.setPosition(right, QTextCursor.KeepAnchor)
        range_fmt = QTextCharFormat()
        dark = int(editor.palette().color(QPalette.Base).lightness()) < 128
        if dark:
            range_bg = QColor("#38BDF8")
            range_bg.setAlpha(88)
        else:
            range_bg = QColor("#2563EB")
            range_bg.setAlpha(56)
        range_fmt.setBackground(range_bg)
        range_sel = QTextEdit.ExtraSelection()
        range_sel.cursor = range_cursor
        range_sel.format = range_fmt
        selections.insert(0, range_sel)
        return selections
