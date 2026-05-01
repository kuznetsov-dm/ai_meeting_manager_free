# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QListWidget, QTextEdit

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.transcript_evidence_controller import TranscriptEvidenceController
from aimn.ui.controllers.transcript_segments_view_controller import (
    TranscriptSegmentsViewCallbacks,
    TranscriptSegmentsViewController,
)


class _TestTranscriptEditor(QTextEdit):
    clickedAt = Signal(int)
    doubleClickedAt = Signal(int)


class TestTranscriptSegmentsViewController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _build_callbacks(self) -> tuple[TranscriptSegmentsViewCallbacks, dict[str, list[object]]]:
        events: dict[str, list[object]] = {
            "highlights": [],
            "seeks": [],
            "plays": [],
            "layers": [],
            "creates": [],
            "suggestions": [],
        }

        def highlight(editor: object, start: int, end: int) -> None:
            events["highlights"].append((editor, int(start), int(end)))

        def seek(ms: int) -> None:
            events["seeks"].append(int(ms))

        def play() -> None:
            events["plays"].append(True)

        def set_layers(editor: object, layer: str, selections: object) -> None:
            count = len(selections) if isinstance(selections, list) else 0
            events["layers"].append((editor, str(layer), count))

        callbacks = TranscriptSegmentsViewCallbacks(
            editor_factory=_TestTranscriptEditor,
            format_ms=TranscriptEvidenceController.ms_to_hhmmss,
            highlight_transcript_range=highlight,
            seek_ms=seek,
            play=play,
            current_artifact_identity=lambda: ("transcription", "T05", "transcript"),
            selection_evidence_payload=lambda _cursor, _ranges, _records: {"segment_index_start": 0},
            suggestion_span_at_position=lambda _spans, _position: None,
            label_text=lambda _key, default: str(default),
            emit_create_requested=lambda action, payload: events["creates"].append((action, payload)),
            emit_suggestion_action_requested=lambda action, payload: events["suggestions"].append((action, payload)),
            set_editor_layer_selections=set_layers,
            management_overlay_selections=lambda _editor, _spans: [],
            find_segment_row_for_cursor=TranscriptEvidenceController.find_segment_row_for_cursor,
            find_segment_row_by_timestamp=TranscriptEvidenceController.find_segment_row_by_timestamp,
            build_segment_text_ranges=TranscriptEvidenceController.build_segment_text_ranges,
        )
        return callbacks, events

    def test_build_view_selects_first_segment_without_seek_or_play(self) -> None:
        callbacks, events = self._build_callbacks()
        records = [
            {"index": 0, "start_ms": 0, "end_ms": 1200, "text": "Alpha"},
            {"index": 1, "start_ms": 1201, "end_ms": 2400, "text": "Beta"},
        ]

        root = TranscriptSegmentsViewController.build_view(
            records,
            transcript_text="Alpha\nBeta",
            callbacks=callbacks,
        )
        QApplication.processEvents()

        list_widget = root.findChild(QListWidget, "transcriptSegmentsList")
        self.assertIsNotNone(list_widget)
        self.assertEqual(list_widget.count(), 2)
        self.assertEqual(list_widget.currentRow(), 0)
        self.assertEqual(len(events["highlights"]), 1)
        self.assertEqual(events["seeks"], [])
        self.assertEqual(events["plays"], [])

    def test_clicking_transcript_row_requests_seek_without_autoplay(self) -> None:
        callbacks, events = self._build_callbacks()
        records = [
            {"index": 0, "start_ms": 0, "end_ms": 1200, "text": "Alpha"},
            {"index": 1, "start_ms": 1201, "end_ms": 2400, "text": "Beta"},
        ]

        root = TranscriptSegmentsViewController.build_view(
            records,
            transcript_text="Alpha\nBeta",
            callbacks=callbacks,
        )
        QApplication.processEvents()

        editor = root.findChild(_TestTranscriptEditor)
        list_widget = root.findChild(QListWidget, "transcriptSegmentsList")
        self.assertIsNotNone(editor)
        self.assertIsNotNone(list_widget)

        editor.clickedAt.emit(6)
        QApplication.processEvents()

        self.assertEqual(list_widget.currentRow(), 1)
        self.assertEqual(events["seeks"], [1201])
        self.assertEqual(events["plays"], [])
        self.assertGreaterEqual(len(events["highlights"]), 2)

    def test_double_clicking_transcript_row_requests_seek_and_play(self) -> None:
        callbacks, events = self._build_callbacks()
        records = [
            {"index": 0, "start_ms": 0, "end_ms": 1200, "text": "Alpha"},
            {"index": 1, "start_ms": 1201, "end_ms": 2400, "text": "Beta"},
        ]

        root = TranscriptSegmentsViewController.build_view(
            records,
            transcript_text="Alpha\nBeta",
            callbacks=callbacks,
        )
        QApplication.processEvents()

        editor = root.findChild(_TestTranscriptEditor)
        list_widget = root.findChild(QListWidget, "transcriptSegmentsList")
        self.assertIsNotNone(editor)
        self.assertIsNotNone(list_widget)

        editor.doubleClickedAt.emit(6)
        QApplication.processEvents()

        self.assertEqual(list_widget.currentRow(), 1)
        self.assertEqual(events["seeks"], [1201])
        self.assertEqual(events["plays"], [True])
        self.assertGreaterEqual(len(events["highlights"]), 2)


if __name__ == "__main__":
    unittest.main()
