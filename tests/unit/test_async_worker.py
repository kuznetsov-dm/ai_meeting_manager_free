import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.services.async_worker import run_async  # noqa: E402


class TestAsyncWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_run_async_calls_finished(self) -> None:
        loop = QEventLoop()
        seen: dict[str, object] = {}

        def _finished(request_id: int, result: object) -> None:
            seen["request_id"] = int(request_id)
            seen["result"] = result
            loop.quit()

        run_async(request_id=11, fn=lambda: "ok", on_finished=_finished)
        QTimer.singleShot(1500, loop.quit)
        loop.exec()

        self.assertEqual(seen.get("request_id"), 11)
        self.assertEqual(seen.get("result"), "ok")

    def test_run_async_calls_error(self) -> None:
        loop = QEventLoop()
        seen: dict[str, object] = {}

        def _failed(request_id: int, error: Exception) -> None:
            seen["request_id"] = int(request_id)
            seen["error"] = str(error)
            loop.quit()

        def _boom() -> str:
            raise RuntimeError("boom")

        run_async(request_id=19, fn=_boom, on_finished=lambda _rid, _result: None, on_error=_failed)
        QTimer.singleShot(1500, loop.quit)
        loop.exec()

        self.assertEqual(seen.get("request_id"), 19)
        self.assertEqual(seen.get("error"), "boom")


if __name__ == "__main__":
    unittest.main()
