import json
import sys
import tempfile
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from aimn.core.app_paths import get_default_input_dir, get_output_dir, is_input_monitoring_enabled  # noqa: E402


class TestAppPathPreferences(unittest.TestCase):
    def test_output_and_input_dirs_are_loaded_from_path_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            settings_dir = app_root / "config" / "settings" / "plugins"
            settings_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "default_input_dir": "input_drop",
                "default_output_dir": "processed_out",
                "monitor_input_dir": True,
            }
            (settings_dir / "ui.path_preferences.json").write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            self.assertEqual(get_default_input_dir(app_root), (app_root / "input_drop").resolve())
            self.assertEqual(get_output_dir(app_root), (app_root / "processed_out").resolve())
            self.assertTrue(is_input_monitoring_enabled(app_root))


if __name__ == "__main__":
    unittest.main()
