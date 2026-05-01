import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtGui import QTextDocument

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.transcript_sync_controller import TranscriptSyncController  # noqa: E402


class _EditorStub:
    def __init__(self, text: str) -> None:
        self._document = QTextDocument(text)
        self._cursor = self._document.find("")
        self._viewport = _ViewportStub(height=120)

    def textCursor(self):
        return self._cursor

    def viewport(self):
        return self._viewport

    def cursorForPosition(self, _point: QPoint):
        return self._cursor


class _ViewportStub:
    def __init__(self, *, height: int) -> None:
        self._height = int(height)

    def height(self) -> int:
        return self._height


class _ItemStub:
    def __init__(self, payload: object = None) -> None:
        self._payload = payload

    def data(self, _role: int):
        return self._payload


class _ListWidgetStub:
    def __init__(
        self,
        *,
        count: int,
        row: int,
        item_at_center: object | None,
        items: list[object] | None = None,
    ) -> None:
        self._count = int(count)
        self._row = int(row)
        self._item_at_center = item_at_center
        self._items = list(items or [])
        self._viewport = _ViewportStub(height=120)

    def count(self) -> int:
        return self._count

    def viewport(self):
        return self._viewport

    def itemAt(self, _point: QPoint):
        return self._item_at_center

    def row(self, _item: object) -> int:
        return self._row

    def item(self, index: int):
        if 0 <= int(index) < len(self._items):
            return self._items[int(index)]
        return None


class TestTranscriptSyncController(unittest.TestCase):
    def test_extract_timestamp_seconds_parses_hhmmss(self) -> None:
        self.assertEqual(TranscriptSyncController.extract_timestamp_seconds("at 00:03:30 now"), 210.0)
        self.assertIsNone(TranscriptSyncController.extract_timestamp_seconds("no timestamp"))

    def test_payload_focus_data_returns_start_ms_and_range(self) -> None:
        start_ms, text_range = TranscriptSyncController.payload_focus_data(
            {"start_ms": 210000, "text_range": (5, 10)}
        )

        self.assertEqual(start_ms, 210000)
        self.assertEqual(text_range, (5, 10))

    def test_clicked_row_falls_back_to_timestamp_lookup(self) -> None:
        row = TranscriptSyncController.clicked_row(
            position=3,
            ranges=[],
            records=[{"start_ms": 210000, "end_ms": 216000}],
            find_segment_row_for_cursor=lambda _position, _ranges: -1,
            find_segment_row_by_timestamp=lambda _records, seconds: 0 if seconds == 210.0 else -1,
            line_text="00:03:30  Ivan  Alpha",
        )

        self.assertEqual(row, 0)

    def test_activate_row_bundle_validates_bounds_and_selection_need(self) -> None:
        self.assertEqual(
            TranscriptSyncController.activate_row_bundle(row=2, count=5, current_row=1),
            (2, True),
        )
        self.assertEqual(
            TranscriptSyncController.activate_row_bundle(row=2, count=5, current_row=2),
            (2, False),
        )
        self.assertIsNone(TranscriptSyncController.activate_row_bundle(row=5, count=5, current_row=1))

    def test_row_activation_payload_reuses_list_payload_when_row_already_selected(self) -> None:
        list_widget = _ListWidgetStub(
            count=3,
            row=1,
            item_at_center=None,
            items=[_ItemStub(), _ItemStub({"start_ms": 1000}), _ItemStub()],
        )

        self.assertEqual(
            TranscriptSyncController.row_activation_payload(
                list_widget=list_widget,
                row=1,
                current_row=1,
            ),
            (1, False, {"start_ms": 1000}),
        )
        self.assertEqual(
            TranscriptSyncController.row_activation_payload(
                list_widget=list_widget,
                row=2,
                current_row=1,
            ),
            (2, True, None),
        )

    def test_selection_apply_bundle_normalizes_payload_and_flags(self) -> None:
        bundle = TranscriptSyncController.selection_apply_bundle(
            selected_payload={"start_ms": 1000},
            play_on_select=1,
            seek_on_select=0,
        )

        assert bundle is not None
        payload, play, seek = bundle
        self.assertEqual(payload["start_ms"], 1000)
        self.assertTrue(play)
        self.assertFalse(seek)
        self.assertIsNone(
            TranscriptSyncController.selection_apply_bundle(
                selected_payload=None,
                play_on_select=False,
                seek_on_select=True,
            )
        )

    def test_text_scroll_target_row_returns_center_match_only_when_row_changes(self) -> None:
        editor = _EditorStub("00:00:01 Alpha")
        editor.textCursor().setPosition(4)

        self.assertEqual(
            TranscriptSyncController.text_scroll_target_row(
                editor=editor,
                ranges=[(0, 8)],
                current_row=1,
                find_segment_row_for_cursor=lambda _position, _ranges: 0,
            ),
            0,
        )
        self.assertEqual(
            TranscriptSyncController.text_scroll_target_row(
                editor=editor,
                ranges=[(0, 8)],
                current_row=0,
                find_segment_row_for_cursor=lambda _position, _ranges: 0,
            ),
            -1,
        )

    def test_segments_scroll_target_row_uses_center_item(self) -> None:
        item = _ItemStub()
        list_widget = _ListWidgetStub(count=3, row=1, item_at_center=item)

        self.assertEqual(
            TranscriptSyncController.segments_scroll_target_row(
                list_widget=list_widget,
                current_row=0,
            ),
            1,
        )
        self.assertEqual(
            TranscriptSyncController.segments_scroll_target_row(
                list_widget=list_widget,
                current_row=1,
            ),
            -1,
        )


if __name__ == "__main__":
    unittest.main()
