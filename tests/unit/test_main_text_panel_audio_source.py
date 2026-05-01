import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.widgets.meetings_workspace_v2 import MainTextPanelV2  # noqa: E402


class _FakePlayer:
    def __init__(self) -> None:
        self.play_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0
        self.set_source_calls: list[QUrl] = []
        self.position_calls: list[int] = []

    def play(self) -> None:
        self.play_calls += 1

    def pause(self) -> None:
        self.pause_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def setSource(self, value: QUrl) -> None:  # noqa: N802
        self.set_source_calls.append(value)

    def setPosition(self, value: int) -> None:  # noqa: N802
        self.position_calls.append(int(value))


class TestMainTextPanelAudioSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_audio_source_is_loaded_on_play_and_released_on_stop(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "")
        fake = _FakePlayer()
        panel._player = fake

        path = str(repo_root / "output" / "sample.wav")
        panel.set_audio_path(path)
        self.assertEqual(fake.play_calls, 0)
        self.assertTrue(fake.set_source_calls)
        self.assertTrue(fake.set_source_calls[-1].isEmpty())

        panel._play()
        self.assertEqual(fake.play_calls, 1)
        actual = Path(fake.set_source_calls[-1].toLocalFile()).resolve().as_posix()
        expected = Path(path).resolve().as_posix()
        self.assertEqual(actual, expected)

        panel._stop()
        self.assertGreaterEqual(fake.stop_calls, 2)
        self.assertTrue(fake.set_source_calls[-1].isEmpty())
        self.assertEqual(panel._loaded_audio_path, "")

    def test_set_meeting_context_batches_tab_rebuild(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "")
        rebuild_calls: list[dict] = []
        emit_calls: list[bool] = []

        panel._rebuild_kind_bar = lambda **_kwargs: None
        panel._reset_search_state = lambda *args, **kwargs: None
        panel._rebuild_tabs = lambda **kwargs: rebuild_calls.append(dict(kwargs))
        panel._emit_current_selection = lambda: emit_calls.append(True)

        artifact = SimpleNamespace(kind="transcript", alias="a", stage_id="transcription", relpath="x.txt")
        panel.set_meeting_context(
            artifacts=[artifact],
            segments_relpaths={"a": "segments/a.json"},
            pinned_aliases={"transcription": "a"},
            active_aliases={"transcription": "a"},
            preferred_kind="transcript",
        )

        self.assertEqual(len(rebuild_calls), 1)
        self.assertEqual(len(emit_calls), 1)
        self.assertEqual(panel._segments_relpaths, {"a": "segments/a.json"})
        self.assertEqual(panel._pinned_aliases, {"transcription": "a"})
        self.assertEqual(panel._active_aliases, {"transcription": "a"})


if __name__ == "__main__":
    unittest.main()
