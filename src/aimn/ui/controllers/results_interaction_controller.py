from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPoint, Qt

from aimn.ui.controllers.transcript_evidence_controller import safe_int
from aimn.ui.controllers.transcript_interaction_controller import TranscriptInteractionController
from aimn.ui.controllers.transcript_navigation_controller import TranscriptNavigationController


class ResultsInteractionController:
    @staticmethod
    def open_args(payload: dict) -> tuple[str, str, str, str, int, int] | None:
        return TranscriptInteractionController.global_search_open_args(payload)

    @staticmethod
    def item_payload_bundle(payload: object) -> tuple[dict, int, int] | None:
        if not isinstance(payload, dict):
            return None
        left = safe_int(payload.get("left"), -1)
        right = safe_int(payload.get("right"), -1)
        if left < 0 or right < left:
            return None
        active_payload = dict(payload.get("payload", {}) or {})
        return active_payload, left, right

    @staticmethod
    def active_payload_for_position(
        active_blocks: Sequence[tuple[int, int, dict, int]],
        position: int,
    ) -> tuple[dict, int, int, int] | None:
        row = TranscriptNavigationController.row_for_position(active_blocks, position)
        if row < 0:
            return None
        for left, right, payload, block_row in active_blocks:
            if int(block_row) != int(row):
                continue
            return dict(payload), int(left), int(right), int(row)
        return None

    @staticmethod
    def row_for_editor_center(
        *,
        active_blocks: Sequence[tuple[int, int, dict, int]],
        position: int,
        current_row: int,
    ) -> int:
        row = TranscriptNavigationController.row_for_position(active_blocks, int(position))
        if row < 0 or row == int(current_row):
            return -1
        return int(row)

    @staticmethod
    def text_scroll_target_row(*, editor: object, active_blocks: Sequence[tuple[int, int, dict, int]], current_row: int) -> int:
        center = QPoint(8, max(0, int(editor.viewport().height()) // 2))
        cursor = editor.cursorForPosition(center)
        return ResultsInteractionController.row_for_editor_center(
            active_blocks=active_blocks,
            position=int(cursor.position()),
            current_row=int(current_row),
        )

    @staticmethod
    def item_activation_bundle(
        *,
        item_payload: object,
        row: int,
        current_row: int,
    ) -> tuple[dict, int, int, int, bool] | None:
        bundle = ResultsInteractionController.item_payload_bundle(item_payload)
        if bundle is None:
            return None
        active_payload, left, right = bundle
        item_row = int(row)
        return active_payload, int(left), int(right), item_row, item_row != int(current_row)

    @staticmethod
    def item_open_bundle(
        *,
        item_payload: object,
        row: int,
        current_row: int,
    ) -> tuple[dict, int, int, int, bool, tuple[str, str, str, str, int, int] | None] | None:
        bundle = ResultsInteractionController.item_activation_bundle(
            item_payload=item_payload,
            row=row,
            current_row=current_row,
        )
        if bundle is None:
            return None
        active_payload, left, right, item_row, needs_selection = bundle
        return (
            active_payload,
            left,
            right,
            item_row,
            needs_selection,
            ResultsInteractionController.open_args(active_payload),
        )

    @staticmethod
    def text_click_bundle(
        *,
        active_blocks: Sequence[tuple[int, int, dict, int]],
        position: int,
        current_row: int,
    ) -> tuple[dict, int, int, int, bool] | None:
        payload = ResultsInteractionController.active_payload_for_position(active_blocks, int(position))
        if payload is None:
            return None
        active_payload, left, right, row = payload
        return active_payload, int(left), int(right), int(row), int(row) != int(current_row)

    @staticmethod
    def text_open_bundle(
        *,
        active_blocks: Sequence[tuple[int, int, dict, int]],
        position: int,
        current_row: int,
    ) -> tuple[dict, int, int, int, bool, tuple[str, str, str, str, int, int] | None] | None:
        bundle = ResultsInteractionController.text_click_bundle(
            active_blocks=active_blocks,
            position=position,
            current_row=current_row,
        )
        if bundle is None:
            return None
        active_payload, left, right, row, needs_selection = bundle
        return (
            active_payload,
            left,
            right,
            row,
            needs_selection,
            ResultsInteractionController.open_args(active_payload),
        )

    @staticmethod
    def list_scroll_target_bundle(
        *,
        list_widget: object,
        current_row: int,
    ) -> tuple[int, int, int, bool] | None:
        center_item = list_widget.itemAt(QPoint(8, max(0, int(list_widget.viewport().height()) // 2)))
        if center_item is None:
            return None
        row = int(list_widget.row(center_item))
        if row < 0:
            return None
        bundle = ResultsInteractionController.list_scroll_bundle(
            row=row,
            current_row=int(current_row),
            payload=center_item.data(Qt.UserRole),
        )
        if bundle is None:
            return None
        left, right, should_select = bundle
        return int(row), int(left), int(right), bool(should_select)

    @staticmethod
    def list_scroll_bundle(*, row: int, current_row: int, payload: object) -> tuple[int, int, bool] | None:
        bundle = ResultsInteractionController.item_payload_bundle(payload)
        if bundle is None:
            return None
        _active_payload, left, right = bundle
        return int(left), int(right), int(row) != int(current_row)
