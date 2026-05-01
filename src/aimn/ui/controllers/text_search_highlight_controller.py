from __future__ import annotations

import re
from collections.abc import Sequence

from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit

from aimn.core.api import query_variants


TextEditorWidget = QTextEdit | QPlainTextEdit


class TextSearchHighlightController:
    @staticmethod
    def editor_layer_attr(layer: str) -> str:
        return f"_aimn_{str(layer or '').strip()}_extra_selections"

    @staticmethod
    def editor_layer_selections(
        editor: TextEditorWidget,
        layer: str,
    ) -> list[QTextEdit.ExtraSelection]:
        value = getattr(editor, TextSearchHighlightController.editor_layer_attr(layer), None)
        if not isinstance(value, list):
            return []
        return list(value)

    @staticmethod
    def refresh_editor_extra_selections(editor: TextEditorWidget) -> None:
        merged: list[QTextEdit.ExtraSelection] = []
        for layer in ("overlay", "search", "focus"):
            merged.extend(TextSearchHighlightController.editor_layer_selections(editor, layer))
        editor.setExtraSelections(merged)

    @staticmethod
    def set_editor_layer_selections(
        editor: TextEditorWidget,
        layer: str,
        selections: Sequence[QTextEdit.ExtraSelection] | None,
    ) -> None:
        setattr(
            editor,
            TextSearchHighlightController.editor_layer_attr(layer),
            list(selections or []),
        )
        TextSearchHighlightController.refresh_editor_extra_selections(editor)

    @staticmethod
    def build_match_cursors(
        editor: TextEditorWidget,
        query: str,
        *,
        max_variants: int = 24,
        max_spans: int = 1200,
        max_cursors: int = 500,
    ) -> list[QTextCursor]:
        text = str(editor.toPlainText() or "")
        token_query = str(query or "").strip()
        if not text or not token_query:
            return []
        variants = query_variants(token_query, include_wildcards=False, max_variants=max_variants)
        spans: list[tuple[int, int]] = []
        seen_spans: set[tuple[int, int]] = set()
        for term in variants:
            token = str(term or "").strip()
            if not token:
                continue
            pattern = re.compile(re.escape(token), flags=re.IGNORECASE)
            for match in pattern.finditer(text):
                left = int(match.start())
                right = int(match.end())
                if right <= left:
                    continue
                key = (left, right)
                if key in seen_spans:
                    continue
                seen_spans.add(key)
                spans.append(key)
                if len(spans) >= max_spans:
                    break
            if len(spans) >= max_spans:
                break
        spans.sort(key=lambda pair: (pair[0], pair[1]))
        found: list[QTextCursor] = []
        for left, right in spans:
            cursor = QTextCursor(editor.document())
            cursor.setPosition(int(left))
            cursor.setPosition(int(right), QTextCursor.KeepAnchor)
            found.append(cursor)
            if len(found) >= max_cursors:
                break
        return found

    @staticmethod
    def build_search_highlight_selections(
        editor: TextEditorWidget,
        cursors: Sequence[QTextCursor],
    ) -> list[QTextEdit.ExtraSelection]:
        fmt = QTextCharFormat()
        dark = int(editor.palette().color(QPalette.Base).lightness()) < 128
        if dark:
            fmt.setBackground(QColor("#1D4ED8"))
            fmt.setForeground(QColor("#F8FAFC"))
        else:
            fmt.setBackground(QColor("#F59E0B"))
            fmt.setForeground(QColor("#111827"))
        fmt.setFontWeight(700)
        selections: list[QTextEdit.ExtraSelection] = []
        for cursor in cursors:
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            selections.append(sel)
        return selections

    @staticmethod
    def build_term_highlight_selections(
        editor: TextEditorWidget,
        terms: Sequence[str],
        *,
        max_matches: int = 1600,
    ) -> list[QTextEdit.ExtraSelection]:
        text = str(editor.toPlainText() or "")
        wanted: list[str] = []
        seen: set[str] = set()
        for token in terms or []:
            value = str(token or "").strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            wanted.append(value)
        if not text or not wanted:
            return []
        fmt = QTextCharFormat()
        dark = int(editor.palette().color(QPalette.Base).lightness()) < 128
        if dark:
            fmt.setBackground(QColor("#1D4ED8"))
            fmt.setForeground(QColor("#F8FAFC"))
        else:
            fmt.setBackground(QColor("#F59E0B"))
            fmt.setForeground(QColor("#111827"))
        fmt.setFontWeight(700)
        selections: list[QTextEdit.ExtraSelection] = []
        used: set[tuple[int, int]] = set()
        for token in wanted:
            pattern = re.compile(re.escape(str(token)), flags=re.IGNORECASE)
            for match in pattern.finditer(text):
                left = int(match.start())
                right = int(match.end())
                if right <= left:
                    continue
                key = (left, right)
                if key in used:
                    continue
                used.add(key)
                cursor = QTextCursor(editor.document())
                cursor.setPosition(left)
                cursor.setPosition(right, QTextCursor.KeepAnchor)
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                selections.append(sel)
                if len(selections) >= max_matches:
                    return selections
        return selections

    @staticmethod
    def next_match_index(current_index: int, total: int, delta: int) -> int:
        count = max(0, int(total))
        if count <= 0:
            return -1
        return (int(current_index) + int(delta)) % count

    @staticmethod
    def apply_match_selection(
        editor: TextEditorWidget,
        cursors: Sequence[QTextCursor],
        match_index: int,
    ) -> tuple[int, int] | None:
        if not cursors or int(match_index) < 0:
            return None
        total = len(cursors)
        idx = max(0, min(int(match_index), total - 1))
        cursor = cursors[idx]
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        return idx + 1, total
