import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QTextEdit

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.document_view_factory_controller import (  # noqa: E402
    DocumentViewFactoryController,
)


class TestDocumentViewFactoryController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_build_results_view_returns_empty_editor_when_no_rows(self) -> None:
        view = DocumentViewFactoryController.build_results_view(
            answer_text="",
            has_rows=False,
            editor_factory=QTextEdit,
        )

        self.assertIsNone(view.list_widget)
        self.assertEqual(view.editor.toPlainText(), "No matches.")

    def test_build_results_view_and_population_create_list_items(self) -> None:
        view = DocumentViewFactoryController.build_results_view(
            answer_text="Summary",
            has_rows=True,
            editor_factory=QTextEdit,
        )
        self.assertIsNotNone(view.list_widget)
        DocumentViewFactoryController.populate_results_list_widget(
            view.list_widget,
            [
                SimpleNamespace(
                    item_text="Result 1",
                    tooltip="tip",
                    payload={"meeting_id": "m1"},
                    left=1,
                    right=5,
                )
            ],
        )
        self.assertEqual(view.list_widget.count(), 1)
        self.assertEqual(view.list_widget.item(0).text(), "Result 1")

    def test_build_transcript_view_and_population_create_segment_rows(self) -> None:
        view = DocumentViewFactoryController.build_transcript_view(editor_factory=QTextEdit)
        DocumentViewFactoryController.populate_transcript_list_widget(
            view.list_widget,
            [SimpleNamespace(label="00:00 Intro", payload={"index": 0})],
        )

        self.assertEqual(view.list_widget.count(), 1)
        self.assertEqual(view.list_widget.item(0).text(), "00:00 Intro")
