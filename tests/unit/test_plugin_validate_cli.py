import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import aimn.cli as cli_module  # noqa: E402


class TestPluginValidateCli(unittest.TestCase):
    def test_validate_manifest_raw_rejects_string_options(self) -> None:
        payload = {
            "id": "service.bad_options",
            "name": "Bad Options",
            "product_name": "Bad Options",
            "highlights": "",
            "description": "",
            "version": "1.0.0",
            "api_version": "1",
            "entrypoint": "plugins.service.bad_options:Plugin",
            "hooks": [],
            "artifacts": [],
            "ui_schema": {
                "settings": [
                    {
                        "key": "target_service",
                        "label": "Target",
                        "value": "todoist",
                        "options": ["todoist", "notion"],
                    }
                ]
            },
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            errors = cli_module._validate_manifest_raw(path)
        self.assertTrue(any("ui_schema_options_invalid:target_service" in item for item in errors))

    def test_validate_manifest_raw_rejects_invalid_ui_stage(self) -> None:
        payload = {
            "id": "service.bad_stage",
            "name": "Bad Stage",
            "product_name": "Bad Stage",
            "highlights": "",
            "description": "",
            "version": "1.0.0",
            "api_version": "1",
            "entrypoint": "plugins.service.bad_stage:Plugin",
            "hooks": [],
            "artifacts": [],
            "ui_stage": "text_processing",
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            errors = cli_module._validate_manifest_raw(path)
        self.assertIn("ui_stage_invalid:text_processing", errors)

    def test_validate_manifest_raw_allows_empty_option_value(self) -> None:
        payload = {
            "id": "service.empty_option",
            "name": "Empty Option",
            "product_name": "Empty Option",
            "highlights": "",
            "description": "",
            "version": "1.0.0",
            "api_version": "1",
            "entrypoint": "plugins.service.empty_option:Plugin",
            "hooks": [],
            "artifacts": [],
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
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            errors = cli_module._validate_manifest_raw(path)
        self.assertEqual(errors, [])

    def test_validate_manifest_raw_rejects_invalid_plugin_id_pattern(self) -> None:
        payload = {
            "id": "BadPlugin",
            "name": "Bad Plugin",
            "product_name": "Bad Plugin",
            "highlights": "",
            "description": "",
            "version": "1.0.0",
            "api_version": "1",
            "entrypoint": "plugins.service.bad_plugin:Plugin",
            "hooks": [],
            "artifacts": [],
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "plugin.json"
            path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            errors = cli_module._validate_manifest_raw(path)
        self.assertTrue(any(item.startswith("schema_invalid:id:") for item in errors))

    def test_resolve_manifest_paths_supports_root_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir(parents=True, exist_ok=True)
            (root / "b").mkdir(parents=True, exist_ok=True)
            (root / "a" / "plugin.json").write_text("{}", encoding="utf-8")
            (root / "b" / "plugin.json").write_text("{}", encoding="utf-8")
            paths = cli_module._resolve_manifest_paths(root)
        self.assertEqual(len(paths), 2)

    def test_validate_entrypoint_source_flags_invalid_management_store_api(self) -> None:
        source = "\n".join(
            [
                "from aimn.plugins.api import open_management_store",
                "def run(ctx):",
                "    store = open_management_store(ctx)",
                "    return store.get_tasks('m1')",
            ]
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_module.py"
            path.write_text(source, encoding="utf-8")
            errors = cli_module._validate_entrypoint_source(SimpleNamespace(__file__=str(path)))
        self.assertIn("management_store_method_invalid:get_tasks", errors)

    def test_validate_entrypoint_source_flags_resolve_prompt_signature(self) -> None:
        source = "\n".join(
            [
                "from aimn.plugins.api import resolve_prompt",
                "def run():",
                "    return resolve_prompt([], 'preset')",
            ]
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample_module.py"
            path.write_text(source, encoding="utf-8")
            errors = cli_module._validate_entrypoint_source(SimpleNamespace(__file__=str(path)))
        self.assertIn("resolve_prompt_signature_invalid", errors)

    def test_lint_alias_routes_to_plugin_validate_handler(self) -> None:
        with patch("aimn.cli._cmd_plugin_validate", return_value=77) as mocked:
            with patch.object(
                sys,
                "argv",
                ["aimn", "plugin", "lint", "plugins/search/simple"],
            ):
                code = cli_module.main()
        self.assertEqual(code, 77)
        mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
