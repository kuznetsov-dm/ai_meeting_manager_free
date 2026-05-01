# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QTextEdit, QWidget

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.widgets.meetings_workspace_v2 import _LazyArtifactView  # noqa: E402


class TestLazyArtifactView(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_ensure_loaded_tolerates_runtime_error(self) -> None:
        view = _LazyArtifactView(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        view.ensure_loaded()

        self.assertEqual(view.layout().count(), 1)
        widget = view.layout().itemAt(0).widget()
        self.assertIsInstance(widget, QTextEdit)
        self.assertTrue(widget.isReadOnly())
        self.assertEqual(widget.toPlainText(), "")

    def test_ensure_loaded_uses_loader_widget_once(self) -> None:
        calls: list[str] = []
        expected = QWidget()
        view = _LazyArtifactView(lambda: calls.append("load") or expected)

        view.ensure_loaded()
        view.ensure_loaded()

        self.assertEqual(calls, ["load"])
        self.assertIs(view.layout().itemAt(0).widget(), expected)


if __name__ == "__main__":
    unittest.main()
