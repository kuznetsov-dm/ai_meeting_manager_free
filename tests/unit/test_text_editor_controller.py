import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.text_editor_controller import TextEditorController  # noqa: E402


class TestTextEditorController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_build_readonly_plain_text_configures_editor(self) -> None:
        editor = TextEditorController.build_readonly_plain_text("Summary text")

        self.assertIsInstance(editor, QPlainTextEdit)
        self.assertTrue(editor.isReadOnly())
        self.assertEqual(editor.toPlainText(), "Summary text")

    def test_extract_text_editor_from_direct_widget_and_nested_child(self) -> None:
        direct = QTextEdit()
        self.assertIs(TextEditorController.extract_text_editor(direct), direct)

        host = QWidget()
        layout = QVBoxLayout(host)
        nested = QPlainTextEdit()
        layout.addWidget(nested)

        self.assertIs(TextEditorController.extract_text_editor(host), nested)
        self.assertIsNone(TextEditorController.extract_text_editor(QWidget()))


if __name__ == "__main__":
    unittest.main()
