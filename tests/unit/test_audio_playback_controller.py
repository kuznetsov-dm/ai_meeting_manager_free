import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QPushButton, QSlider, QWidget

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.audio_playback_controller import AudioPlaybackController  # noqa: E402


class _FakePlayer:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.set_source_calls: list[QUrl] = []

    def stop(self) -> None:
        self.stop_calls += 1

    def setSource(self, value: QUrl) -> None:  # noqa: N802
        self.set_source_calls.append(value)


class TestAudioPlaybackController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_set_audio_enabled_updates_all_widgets(self) -> None:
        widgets = [QPushButton(), QSlider(), QWidget()]

        AudioPlaybackController.set_audio_enabled(widgets, False)

        self.assertTrue(all(not widget.isEnabled() for widget in widgets))

    def test_ensure_audio_source_loaded_reuses_loaded_path(self) -> None:
        player = _FakePlayer()
        path = str(repo_root / "output" / "sample.wav")

        first = AudioPlaybackController.ensure_audio_source_loaded(player, path, "")
        second = AudioPlaybackController.ensure_audio_source_loaded(player, path, path)

        self.assertEqual(first, (True, path))
        self.assertEqual(second, (True, path))
        self.assertEqual(len(player.set_source_calls), 1)

    def test_release_audio_source_resets_slider_and_player(self) -> None:
        player = _FakePlayer()
        slider = QSlider()
        slider.setRange(0, 100)
        slider.setValue(50)

        loaded = AudioPlaybackController.release_audio_source(player, slider)

        self.assertEqual(loaded, "")
        self.assertEqual(player.stop_calls, 1)
        self.assertTrue(player.set_source_calls[-1].isEmpty())
        self.assertEqual(slider.minimum(), 0)
        self.assertEqual(slider.maximum(), 0)
        self.assertEqual(slider.value(), 0)


if __name__ == "__main__":
    unittest.main()
