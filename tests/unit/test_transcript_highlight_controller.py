import sys
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat
from PySide6.QtWidgets import QApplication, QPlainTextEdit

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.transcript_evidence_controller import TranscriptSuggestionSpan  # noqa: E402
from aimn.ui.controllers.transcript_highlight_controller import TranscriptHighlightController  # noqa: E402


class TestTranscriptHighlightController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_management_overlay_selections_build_for_spans(self) -> None:
        editor = QPlainTextEdit()
        editor.setPlainText("Alpha beta gamma")

        selections = TranscriptHighlightController.management_overlay_selections(
            editor,
            [TranscriptSuggestionSpan("s-1", "task", "Task", 0, 5, 0.9, "Alpha", {})],
        )

        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].cursor.selectedText(), "Alpha")
        self.assertEqual(selections[0].format.underlineStyle(), QTextCharFormat.SingleUnderline)
        self.assertEqual(selections[0].format.foreground().style(), Qt.BrushStyle.NoBrush)

    def test_focus_range_selections_include_primary_range(self) -> None:
        editor = QPlainTextEdit()
        editor.setPlainText("Alpha beta gamma")

        selections = TranscriptHighlightController.focus_range_selections(
            editor,
            start=6,
            end=10,
            terms=["beta"],
        )

        self.assertGreaterEqual(len(selections), 1)
        self.assertEqual(selections[0].cursor.selectedText(), "beta")


if __name__ == "__main__":
    unittest.main()
