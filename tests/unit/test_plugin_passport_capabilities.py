import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.contracts import PluginDescriptor  # noqa: E402
from aimn.core.plugin_catalog import _apply_plugin_passport  # noqa: E402


class TestPluginPassportCapabilities(unittest.TestCase):
    def test_passport_applies_capabilities_and_model_id_alias(self) -> None:
        plugin = PluginDescriptor(
            plugin_id="test.plugin",
            stage_id="llm_processing",
            name="Technical Name",
            module="test.module",
            class_name="Plugin",
        )

        passport = {
            "provider": {"name": "Provider", "description": "Provider description"},
            "models": [{"model_id": "m1", "name": "Model 1", "description": "Model description"}],
            "capabilities": {"models": {"local_files": {"default_root": "models/llama", "glob": "*.gguf"}}},
        }

        _apply_plugin_passport(plugin, passport)

        self.assertIn("m1", plugin.model_info)
        self.assertEqual(plugin.model_info["m1"]["model_name"], "Model 1")
        self.assertIn("models", plugin.capabilities)
        self.assertIn("local_files", plugin.capabilities.get("models", {}))


if __name__ == "__main__":
    unittest.main()

