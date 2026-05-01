import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.logs_buffer_controller import LogsBufferController  # noqa: E402


class TestLogsBufferController(unittest.TestCase):
    def test_update_buffer_appends_only_new_entries(self) -> None:
        text, count = LogsBufferController.update_buffer(
            [SimpleNamespace(message="a"), SimpleNamespace(message="b")],
            current_text="a",
            current_count=1,
        )

        self.assertEqual(text, "a\nb")
        self.assertEqual(count, 2)

    def test_update_buffer_rebuilds_when_count_changes_non_incrementally(self) -> None:
        text, count = LogsBufferController.update_buffer(
            [SimpleNamespace(message="x"), SimpleNamespace(message="y")],
            current_text="stale",
            current_count=5,
        )

        self.assertEqual(text, "x\ny")
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
