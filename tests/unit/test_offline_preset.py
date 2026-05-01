import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.pipeline_presets import offline_plugin_ids  # noqa: E402
from aimn.core.plugins_registry import ensure_plugins_enabled  # noqa: E402


class TestOfflinePreset(unittest.TestCase):
    def test_offline_plugins_removed_from_disabled(self) -> None:
        offline_ids = offline_plugin_ids(repo_root)
        payload = {"disabled": {"ids": offline_ids}}
        updated = ensure_plugins_enabled(payload, offline_ids)
        disabled = updated.get("disabled", {})
        ids = disabled.get("ids", [])
        self.assertEqual(ids, [])

    def test_offline_plugins_added_to_enabled(self) -> None:
        offline_ids = offline_plugin_ids(repo_root)
        payload = {"enabled": {"ids": ["llm.openrouter"]}}
        updated = ensure_plugins_enabled(payload, offline_ids)
        enabled = updated.get("enabled", {})
        ids = enabled.get("ids", [])
        for plugin_id in offline_ids:
            self.assertIn(plugin_id, ids)


if __name__ == "__main__":
    unittest.main()
