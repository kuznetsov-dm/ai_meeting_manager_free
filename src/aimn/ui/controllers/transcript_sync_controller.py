from __future__ import annotations

import re
from collections.abc import Sequence

from PySide6.QtCore import QPoint

from aimn.ui.controllers.transcript_evidence_controller import safe_int

_TS_RE = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})")


class TranscriptSyncController:
    @staticmethod
    def extract_timestamp_seconds(text: str) -> float | None:
        match = _TS_RE.search(str(text or ""))
        if not match:
            return None
        h = int(match.group("h"))
        m = int(match.group("m"))
        s = int(match.group("s"))
        return float(h * 3600 + m * 60 + s)

    @staticmethod
    def line_text_at_position(editor: object, position: int) -> str:
        cursor = editor.textCursor()
        cursor.setPosition(max(0, int(position)))
        return str(cursor.block().text() or "")

    @staticmethod
    def payload_focus_data(payload: dict | None) -> tuple[int, tuple[int, int] | None]:
        if not isinstance(payload, dict):
            return 0, None
        start_ms = safe_int(payload.get("start_ms"), 0)
        text_range = payload.get("text_range")
        if (
            isinstance(text_range, (tuple, list))
            and len(text_range) == 2
            and safe_int(text_range[0], -1) >= 0
            and safe_int(text_range[1], -1) >= safe_int(text_range[0], -1)
        ):
            return start_ms, (int(text_range[0]), int(text_range[1]))
        return start_ms, None

    @staticmethod
    def activate_row_bundle(*, row: int, count: int, current_row: int) -> tuple[int, bool] | None:
        target = int(row)
        if target < 0 or target >= int(count):
            return None
        return target, target != int(current_row)

    @staticmethod
    def row_item_payload(*, list_widget: object, row: int) -> dict | None:
        target = int(row)
        if target < 0 or target >= int(list_widget.count()):
            return None
        item = list_widget.item(target)
        payload = item.data(0x0100) if item is not None else None  # Qt.UserRole
        return dict(payload) if isinstance(payload, dict) else None

    @staticmethod
    def row_activation_payload(
        *,
        list_widget: object,
        row: int,
        current_row: int,
    ) -> tuple[int, bool, dict | None] | None:
        bundle = TranscriptSyncController.activate_row_bundle(
            row=row,
            count=int(list_widget.count()),
            current_row=current_row,
        )
        if bundle is None:
            return None
        target, needs_selection = bundle
        payload = None if needs_selection else TranscriptSyncController.row_item_payload(
            list_widget=list_widget,
            row=target,
        )
        return target, needs_selection, payload

    @staticmethod
    def selection_apply_bundle(
        *,
        selected_payload: object,
        play_on_select: object,
        seek_on_select: object,
    ) -> tuple[dict, bool, bool] | None:
        if not isinstance(selected_payload, dict):
            return None
        return dict(selected_payload), bool(play_on_select), bool(seek_on_select)

    @staticmethod
    def clicked_row(
        *,
        position: int,
        ranges: list[tuple[int, int] | None],
        records: list[dict],
        find_segment_row_for_cursor,
        find_segment_row_by_timestamp,
        line_text: str,
    ) -> int:
        row = int(find_segment_row_for_cursor(int(position), ranges))
        if row >= 0:
            return row
        seconds = TranscriptSyncController.extract_timestamp_seconds(line_text)
        if seconds is None:
            return -1
        return int(find_segment_row_by_timestamp(records, seconds))

    @staticmethod
    def text_scroll_target_row(
        *,
        editor: object,
        ranges: Sequence[tuple[int, int] | None],
        current_row: int,
        find_segment_row_for_cursor,
    ) -> int:
        if not ranges:
            return -1
        center = QPoint(8, max(0, int(editor.viewport().height()) // 2))
        cursor = editor.cursorForPosition(center)
        row = int(find_segment_row_for_cursor(int(cursor.position()), list(ranges)))
        if row < 0 or row == int(current_row):
            return -1
        return row

    @staticmethod
    def segments_scroll_target_row(*, list_widget: object, current_row: int) -> int:
        if int(list_widget.count()) <= 0:
            return -1
        center_item = list_widget.itemAt(QPoint(8, max(0, int(list_widget.viewport().height()) // 2)))
        if center_item is None:
            return -1
        row = int(list_widget.row(center_item))
        if row < 0 or row == int(current_row):
            return -1
        return row
