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

from aimn.core.plugins_config import PluginsConfig  # noqa: E402
from aimn.core.stages.transcription import TranscriptionAdapter  # noqa: E402


class TestTranscriptionCachePolicy(unittest.TestCase):
    def test_stable_fingerprint_ignores_transcription_model_id_duplicate(self) -> None:
        adapter = TranscriptionAdapter(
            policy=SimpleNamespace(stage_id="transcription"),
            config=PluginsConfig({}),
        )

        stable = adapter._stable_fingerprint_params(
            {
                "model": "tiny",
                "model_id": "tiny",
                "language_mode": "auto",
                "allow_download": False,
            }
        )

        self.assertEqual(
            stable,
            {
                "model": "tiny",
                "language_mode": "auto",
                "allow_download": False,
            },
        )

    def test_stable_fingerprint_promotes_model_id_when_model_missing(self) -> None:
        adapter = TranscriptionAdapter(
            policy=SimpleNamespace(stage_id="transcription"),
            config=PluginsConfig({}),
        )

        stable = adapter._stable_fingerprint_params(
            {
                "model_id": "tiny",
                "language_mode": "auto",
            }
        )

        self.assertEqual(
            stable,
            {
                "model": "tiny",
                "language_mode": "auto",
            },
        )


if __name__ == "__main__":
    unittest.main()
