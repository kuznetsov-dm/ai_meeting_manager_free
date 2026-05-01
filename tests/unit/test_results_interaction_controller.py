# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.results_interaction_controller import (
    ResultsInteractionController,  # noqa: E402
)


class _ViewportStub:
    def __init__(self, *, height: int) -> None:
        self._height = int(height)

    def height(self) -> int:
        return self._height


class _CursorStub:
    def __init__(self, position: int) -> None:
        self._position = int(position)

    def position(self) -> int:
        return self._position


class _EditorStub:
    def __init__(self, *, position: int) -> None:
        self._position = int(position)
        self._viewport = _ViewportStub(height=120)

    def viewport(self):
        return self._viewport

    def cursorForPosition(self, _point: QPoint):
        return _CursorStub(self._position)


class _ItemStub:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def data(self, _role: int):
        return self._payload


class _ListWidgetStub:
    def __init__(self, *, row: int, item: object | None) -> None:
        self._row = int(row)
        self._item = item
        self._viewport = _ViewportStub(height=120)

    def viewport(self):
        return self._viewport

    def itemAt(self, _point: QPoint):
        return self._item

    def row(self, _item: object) -> int:
        return self._row


class TestResultsInteractionController(unittest.TestCase):
    def test_open_args_delegates_to_global_search_payload_shape(self) -> None:
        args = ResultsInteractionController.open_args(
            {
                "meeting_id": "m-1",
                "stage_id": "llm_processing",
                "alias": "A1",
                "kind": "summary",
                "segment_index": 3,
                "start_ms": 210000,
            }
        )

        self.assertEqual(args, ("m-1", "llm_processing", "A1", "summary", 3, 210000))

    def test_item_payload_bundle_returns_payload_and_range(self) -> None:
        bundle = ResultsInteractionController.item_payload_bundle(
            {"payload": {"meeting_id": "m-1"}, "left": 5, "right": 10}
        )

        self.assertEqual(bundle, ({"meeting_id": "m-1"}, 5, 10))

    def test_active_payload_for_position_uses_active_blocks(self) -> None:
        payload = ResultsInteractionController.active_payload_for_position(
            [(0, 10, {"meeting_id": "m-1"}, 0), (11, 20, {"meeting_id": "m-2"}, 1)],
            15,
        )

        self.assertEqual(payload, ({"meeting_id": "m-2"}, 11, 20, 1))

    def test_row_for_editor_center_skips_current_row(self) -> None:
        row = ResultsInteractionController.row_for_editor_center(
            active_blocks=[(0, 10, {"meeting_id": "m-1"}, 0), (11, 20, {"meeting_id": "m-2"}, 1)],
            position=15,
            current_row=0,
        )

        self.assertEqual(row, 1)
        self.assertEqual(
            ResultsInteractionController.row_for_editor_center(
                active_blocks=[(0, 10, {"meeting_id": "m-1"}, 0)],
                position=5,
                current_row=0,
            ),
            -1,
        )

    def test_text_scroll_target_row_uses_editor_center_cursor(self) -> None:
        row = ResultsInteractionController.text_scroll_target_row(
            editor=_EditorStub(position=15),
            active_blocks=[(0, 10, {"meeting_id": "m-1"}, 0), (11, 20, {"meeting_id": "m-2"}, 1)],
            current_row=0,
        )

        self.assertEqual(row, 1)

    def test_item_activation_bundle_reports_row_and_selection_need(self) -> None:
        bundle = ResultsInteractionController.item_activation_bundle(
            item_payload={"payload": {"meeting_id": "m-1"}, "left": 5, "right": 10},
            row=2,
            current_row=1,
        )

        self.assertEqual(bundle, ({"meeting_id": "m-1"}, 5, 10, 2, True))
        self.assertEqual(
            ResultsInteractionController.item_activation_bundle(
                item_payload={"payload": {"meeting_id": "m-1"}, "left": 5, "right": 10},
                row=2,
                current_row=2,
            ),
            ({"meeting_id": "m-1"}, 5, 10, 2, False),
        )

    def test_item_open_bundle_includes_open_args(self) -> None:
        bundle = ResultsInteractionController.item_open_bundle(
            item_payload={
                "payload": {
                    "meeting_id": "m-1",
                    "stage_id": "llm_processing",
                    "alias": "A1",
                    "kind": "summary",
                    "segment_index": 3,
                    "start_ms": 210000,
                },
                "left": 5,
                "right": 10,
            },
            row=2,
            current_row=1,
        )

        self.assertEqual(
            bundle,
            (
                {
                    "meeting_id": "m-1",
                    "stage_id": "llm_processing",
                    "alias": "A1",
                    "kind": "summary",
                    "segment_index": 3,
                    "start_ms": 210000,
                },
                5,
                10,
                2,
                True,
                ("m-1", "llm_processing", "A1", "summary", 3, 210000),
            ),
        )

    def test_text_click_bundle_reuses_active_payload_resolution(self) -> None:
        bundle = ResultsInteractionController.text_click_bundle(
            active_blocks=[(0, 10, {"meeting_id": "m-1"}, 0), (11, 20, {"meeting_id": "m-2"}, 1)],
            position=15,
            current_row=0,
        )

        self.assertEqual(bundle, ({"meeting_id": "m-2"}, 11, 20, 1, True))
        self.assertIsNone(
            ResultsInteractionController.text_click_bundle(
                active_blocks=[],
                position=3,
                current_row=0,
            )
        )

    def test_text_open_bundle_includes_open_args(self) -> None:
        bundle = ResultsInteractionController.text_open_bundle(
            active_blocks=[
                (
                    11,
                    20,
                    {
                        "meeting_id": "m-2",
                        "stage_id": "transcription",
                        "alias": "T1",
                        "kind": "transcript",
                        "segment_index": 4,
                        "start_ms": 3000,
                    },
                    1,
                )
            ],
            position=15,
            current_row=0,
        )

        self.assertEqual(
            bundle,
            (
                {
                    "meeting_id": "m-2",
                    "stage_id": "transcription",
                    "alias": "T1",
                    "kind": "transcript",
                    "segment_index": 4,
                    "start_ms": 3000,
                },
                11,
                20,
                1,
                True,
                ("m-2", "transcription", "T1", "transcript", 4, 3000),
            ),
        )

    def test_list_scroll_target_bundle_reads_center_item_and_payload(self) -> None:
        bundle = ResultsInteractionController.list_scroll_target_bundle(
            list_widget=_ListWidgetStub(
                row=2,
                item=_ItemStub({"payload": {"meeting_id": "m-1"}, "left": 5, "right": 9}),
            ),
            current_row=1,
        )

        self.assertEqual(bundle, (2, 5, 9, True))
        self.assertIsNone(
            ResultsInteractionController.list_scroll_target_bundle(
                list_widget=_ListWidgetStub(row=0, item=None),
                current_row=0,
            )
        )

    def test_list_scroll_bundle_reuses_item_payload_validation(self) -> None:
        bundle = ResultsInteractionController.list_scroll_bundle(
            row=2,
            current_row=1,
            payload={"payload": {"meeting_id": "m-1"}, "left": 5, "right": 9},
        )

        self.assertEqual(bundle, (5, 9, True))
        self.assertIsNone(
            ResultsInteractionController.list_scroll_bundle(
                row=0,
                current_row=0,
                payload={"payload": {}, "left": -1, "right": 9},
            )
        )


if __name__ == "__main__":
    unittest.main()
