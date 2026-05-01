import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_catalog import create_default_catalog  # noqa: E402


class TestPluginCatalogOptions(unittest.TestCase):
    def test_option_with_empty_value_is_preserved(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins" / "service" / "demo"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "id": "service.demo",
                "name": "Demo",
                "product_name": "Demo",
                "highlights": "",
                "description": "",
                "version": "1.0.0",
                "api_version": "1",
                "entrypoint": "plugins.service.demo.plugin:Plugin",
                "hooks": [],
                "artifacts": [],
                "ui_stage": "service",
                "ui_schema": {
                    "settings": [
                        {
                            "key": "language_code",
                            "label": "Language",
                            "value": "",
                            "options": [
                                {"label": "(not set)", "value": ""},
                                {"label": "English", "value": "en"},
                            ],
                        }
                    ]
                },
            }
            (plugin_dir / "plugin.json").write_text(
                json.dumps(manifest, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            catalog = create_default_catalog(root)

        schema = catalog.schema_for("service.demo")
        self.assertIsNotNone(schema)
        options = schema.settings[0].options if schema else []
        self.assertEqual(options[0].value, "")
        self.assertEqual(options[1].value, "en")

    def test_catalog_ignores_repo_test_plugin_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            visible_dir = root / "plugins" / "service" / "demo"
            hidden_dir = root / "plugins" / "_test_demo_plugin"
            visible_dir.mkdir(parents=True, exist_ok=True)
            hidden_dir.mkdir(parents=True, exist_ok=True)
            (visible_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "service.demo",
                        "name": "Demo",
                        "product_name": "Demo",
                        "highlights": "",
                        "description": "",
                        "version": "1.0.0",
                        "api_version": "1",
                        "entrypoint": "plugins.service.demo.demo:Plugin",
                        "hooks": [],
                        "artifacts": [],
                        "ui_stage": "service",
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (hidden_dir / "plugin.json").write_text(
                json.dumps(
                    {
                        "id": "service.test_hidden",
                        "name": "Test Hidden",
                        "product_name": "Test Hidden",
                        "highlights": "",
                        "description": "",
                        "version": "1.0.0",
                        "api_version": "1",
                        "entrypoint": "plugins._test_demo_plugin.hidden:Plugin",
                        "hooks": [],
                        "artifacts": [],
                        "ui_stage": "service",
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )

            catalog = create_default_catalog(root)

        self.assertIsNotNone(catalog.plugin_by_id("service.demo"))
        self.assertIsNone(catalog.plugin_by_id("service.test_hidden"))


if __name__ == "__main__":
    unittest.main()
