import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPlainTextEdit

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.text_search_highlight_controller import (  # noqa: E402
    TextSearchHighlightController,
)


class TestTextSearchHighlightController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_build_match_cursors_finds_case_insensitive_hits(self) -> None:
        editor = QPlainTextEdit()
        editor.setPlainText("Alpha beta ALPHA")

        cursors = TextSearchHighlightController.build_match_cursors(editor, "alpha")

        self.assertEqual(len(cursors), 2)
        self.assertEqual(cursors[0].selectedText(), "Alpha")
        self.assertEqual(cursors[1].selectedText(), "ALPHA")

    def test_layer_selections_round_trip_and_refresh(self) -> None:
        editor = QPlainTextEdit()
        editor.setPlainText("Alpha beta")
        cursors = TextSearchHighlightController.build_match_cursors(editor, "beta")
        selections = TextSearchHighlightController.build_search_highlight_selections(editor, cursors)

        TextSearchHighlightController.set_editor_layer_selections(editor, "search", selections)

        stored = TextSearchHighlightController.editor_layer_selections(editor, "search")
        self.assertEqual(len(stored), 1)
        self.assertEqual(len(editor.extraSelections()), 1)

    def test_apply_match_selection_moves_cursor_and_reports_position(self) -> None:
        editor = QPlainTextEdit()
        editor.setPlainText("Alpha beta gamma beta")
        cursors = TextSearchHighlightController.build_match_cursors(editor, "beta")

        result = TextSearchHighlightController.apply_match_selection(editor, cursors, 1)

        self.assertEqual(result, (2, 2))
        self.assertEqual(editor.textCursor().selectedText(), "beta")


if __name__ == "__main__":
    unittest.main()
