import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.widgets.meetings_workspace_v2 import HistoryPanelV2  # noqa: E402


def _meeting(base_name: str) -> object:
    return SimpleNamespace(
        base_name=base_name,
        meeting_id=f"id-{base_name}",
        processing_status="completed",
        source=SimpleNamespace(items=[]),
        display_title=base_name,
        display_meeting_time="",
        display_processed_time="",
        display_stats="",
        pipeline_runs=[],
    )


class TestHistoryPanelSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_selecting_same_base_name_does_not_emit_twice(self) -> None:
        panel = HistoryPanelV2()
        panel.set_meetings([_meeting("m1"), _meeting("m2")])
        seen: list[str] = []
        panel.meetingSelected.connect(lambda base: seen.append(str(base)))

        panel.select_by_base_name("m1")
        panel.select_by_base_name("m1")
        QApplication.processEvents()

        self.assertEqual(seen, ["m1"])


if __name__ == "__main__":
    unittest.main()
