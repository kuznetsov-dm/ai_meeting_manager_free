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


class TestPluginPassportUiCopyIgnored(unittest.TestCase):
    def test_passport_does_not_override_ui_copy(self) -> None:
        plugin = PluginDescriptor(
            plugin_id="test.plugin",
            stage_id="text_processing",
            name="Technical Name",
            module="test.module",
            class_name="Plugin",
            product_name="FromManifest",
            highlights="FromManifestHighlights",
            description="FromManifestDescription",
            icon_key="manifest_icon",
        )

        passport = {
            "product_name": "FromPassport",
            "highlights": "FromPassportHighlights",
            "description": "FromPassportDescription",
            "icon_key": "passport_icon",
            "provider": {"name": "Provider", "description": "Provider description"},
            "models": [{"id": "m1", "name": "Model 1", "description": "Model description"}],
        }

        _apply_plugin_passport(plugin, passport)

        self.assertEqual(plugin.product_name, "FromManifest")
        self.assertEqual(plugin.highlights, "FromManifestHighlights")
        self.assertEqual(plugin.description, "FromManifestDescription")
        self.assertEqual(plugin.icon_key, "manifest_icon")

        self.assertEqual(plugin.provider_name, "Provider")
        self.assertEqual(plugin.provider_description, "Provider description")
        self.assertIn("m1", plugin.model_info)
        self.assertEqual(plugin.model_info["m1"]["model_name"], "Model 1")
        self.assertEqual(plugin.model_info["m1"]["model_description"], "Model description")


if __name__ == "__main__":
    unittest.main()
