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

from aimn.ui.controllers.results_view_controller import (  # noqa: E402
    ResultsViewCallbacks,
    ResultsViewController,
)


class _TestResultsEditor(QTextEdit):
    clickedAt = Signal(int)
    doubleClickedAt = Signal(int)


class TestResultsViewController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_build_view_materializes_results_and_selects_first_row(self) -> None:
        highlights: list[tuple[int, int, list[str]]] = []
        opened: list[tuple[str, str, str, str, int, int]] = []

        root = ResultsViewController.build_view(
            query="roadmap",
            rows=[
                {
                    "title": "Meeting A  00:00:01  #2",
                    "preview": "roadmap text",
                    "text": "roadmap text",
                    "payload": {
                        "meeting_id": "m1",
                        "stage_id": "llm_processing",
                        "alias": "A1",
                        "kind": "summary",
                        "segment_index": 2,
                        "start_ms": 1200,
                    },
                    "terms": ["roadmap"],
                }
            ],
            answer_text="Answer",
            callbacks=ResultsViewCallbacks(
                editor_factory=_TestResultsEditor,
                apply_editor_term_highlights=lambda _editor, _terms: None,
                highlight_range=lambda _editor, left, right, terms: highlights.append(
                    (int(left), int(right), list(terms or []))
                ),
                emit_open=lambda args: opened.append(args),
            ),
        )
        QApplication.processEvents()

        list_widget = root.findChild(QListWidget, "globalSearchSegmentsList")
        editor = root.findChild(_TestResultsEditor)
        self.assertIsNotNone(list_widget)
        self.assertIsNotNone(editor)
        self.assertEqual(list_widget.count(), 1)
        self.assertEqual(list_widget.currentRow(), 0)
        self.assertGreaterEqual(len(highlights), 1)

        item = list_widget.item(0)
        list_widget.itemActivated.emit(item)
        QApplication.processEvents()

        self.assertEqual(opened, [("m1", "llm_processing", "A1", "summary", 2, 1200)])


if __name__ == "__main__":
    unittest.main()
