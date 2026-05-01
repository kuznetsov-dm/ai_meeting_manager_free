from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QWidget


class AudioPlaybackController:
    @staticmethod
    def set_audio_enabled(widgets: Sequence[QWidget], enabled: bool) -> None:
        for widget in widgets:
            widget.setEnabled(bool(enabled))

    @staticmethod
    def ensure_audio_source_loaded(player: object, current_audio_path: str, loaded_audio_path: str) -> tuple[bool, str]:
        path = str(current_audio_path or "").strip()
        loaded = str(loaded_audio_path or "").strip()
        if not path:
            return False, loaded
        if loaded == path:
            return True, loaded
        player.setSource(QUrl.fromLocalFile(path))
        return True, path

    @staticmethod
    def release_audio_source(player: object, slider: object) -> str:
        player.stop()
        player.setSource(QUrl())
        slider.setRange(0, 0)
        slider.setValue(0)
        return ""

    @staticmethod
    def set_duration(slider: object, duration: int) -> None:
        slider.setRange(0, max(0, int(duration)))

    @staticmethod
    def sync_position(slider: object, position: int) -> None:
        if not slider.isSliderDown():
            slider.setValue(max(0, int(position)))
