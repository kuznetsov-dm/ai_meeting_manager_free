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

from aimn.ui.widgets.variants_panels import TranscriptionPanel  # noqa: E402


class TestTranscriptionPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_collect_settings_keeps_multiple_models_for_same_provider(self) -> None:
        panel = TranscriptionPanel()
        stage = SimpleNamespace(
            current_settings={"plugin_id": "transcription.whisperadvanced"},
            ui_metadata={
                "available_providers": [("transcription.whisperadvanced", "Whisper Advanced")],
                "selected_provider": "transcription.whisperadvanced",
                "enabled_providers": ["transcription.whisperadvanced"],
                "provider_params": {
                    "transcription.whisperadvanced": {
                        "model": "small",
                        "language_mode": "auto",
                        "language_code": "",
                        "two_pass": False,
                        "preset_profile": "silero_vad_ru",
                    }
                },
                "selected_models": {"transcription.whisperadvanced": ["small", "medium"]},
                "installed_models": ["small", "medium", "large-v3"],
                "transcription_preset_providers": ["transcription.whisperadvanced"],
            },
        )

        panel.apply_stage(stage)

        payload = panel.collect_settings()["__stage_payload__"]
        self.assertEqual(payload["plugin_id"], "transcription.whisperadvanced")
        self.assertEqual(
            [entry["plugin_id"] for entry in payload["variants"]],
            ["transcription.whisperadvanced", "transcription.whisperadvanced"],
        )
        self.assertEqual(
            [entry["params"]["model"] for entry in payload["variants"]],
            ["small", "medium"],
        )
        self.assertEqual(payload["params"]["model"], "small")
        self.assertEqual(payload["params"]["preset_profile"], "silero_vad_ru")

        panel._toggle_model("large-v3", True)  # noqa: SLF001
        payload = panel.collect_settings()["__stage_payload__"]
        models = [entry["params"]["model"] for entry in payload["variants"]]
        self.assertEqual(models, ["small", "medium", "large-v3"])


if __name__ == "__main__":
    unittest.main()
