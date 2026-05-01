import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_manifest import load_plugin_manifest  # noqa: E402


def _write_manifest(root: Path, payload: dict) -> Path:
    path = root / "plugin.json"
    path.write_text(
        __import__("json").dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return path


class TestPluginManifestParsing(unittest.TestCase):
    def test_manifest_loads_without_ui(self) -> None:
        payload = {
            "id": "demo.plugin",
            "name": "Demo",
            "product_name": "Demo",
            "highlights": "",
            "description": "",
            "version": "0.1.0",
            "api_version": "1",
            "entrypoint": "plugins.demo:Plugin",
            "hooks": [{"name": "transcribe.run"}],
            "artifacts": ["transcript"],
        }
        with TemporaryDirectory() as tmp:
            path = _write_manifest(Path(tmp), payload)
            manifest = load_plugin_manifest(path)
            self.assertEqual(manifest.plugin_id, "demo.plugin")

    def test_manifest_accepts_ui_fields_but_ignores_them(self) -> None:
        payload_tabs = {
            "id": "demo.tabs",
            "name": "Demo Tabs",
            "product_name": "Demo Tabs",
            "highlights": "",
            "description": "",
            "version": "0.1.0",
            "api_version": "1",
            "entrypoint": "plugins.demo:Plugin",
            "hooks": [{"name": "transcribe.run"}],
            "artifacts": ["transcript"],
            "ui": {"tabs": ["DemoTab"]},
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_tabs = load_plugin_manifest(_write_manifest(root, payload_tabs))
            self.assertEqual(manifest_tabs.plugin_id, "demo.tabs")
            self.assertFalse(hasattr(manifest_tabs, "ui"))

    def test_manifest_parses_optional_dependencies(self) -> None:
        payload = {
            "id": "demo.deps",
            "name": "Demo Deps",
            "product_name": "Demo Deps",
            "highlights": "",
            "description": "",
            "version": "0.1.0",
            "api_version": "1",
            "entrypoint": "plugins.demo:Plugin",
            "hooks": [{"name": "transcribe.run"}],
            "artifacts": ["transcript"],
            "dependencies": ["requests==2.32.3", "nltk>=3.9", "requests==2.32.3", "  "],
        }
        with TemporaryDirectory() as tmp:
            manifest = load_plugin_manifest(_write_manifest(Path(tmp), payload))
            self.assertEqual(manifest.dependencies, ["requests==2.32.3", "nltk>=3.9"])

    def test_manifest_rejects_non_list_dependencies(self) -> None:
        payload = {
            "id": "demo.baddeps",
            "name": "Demo Bad Deps",
            "product_name": "Demo Bad Deps",
            "highlights": "",
            "description": "",
            "version": "0.1.0",
            "api_version": "1",
            "entrypoint": "plugins.demo:Plugin",
            "hooks": [{"name": "transcribe.run"}],
            "artifacts": ["transcript"],
            "dependencies": {"requests": "2.32.3"},
        }
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_plugin_manifest(_write_manifest(Path(tmp), payload))

    def test_manifest_supports_ui_hidden_flag(self) -> None:
        payload = {
            "id": "demo.hidden",
            "name": "Demo Hidden",
            "product_name": "Demo Hidden",
            "highlights": "",
            "description": "",
            "version": "0.1.0",
            "api_version": "1",
            "entrypoint": "plugins.demo:Plugin",
            "hooks": [{"name": "transcribe.run"}],
            "artifacts": ["transcript"],
            "ui_hidden": True,
        }
        with TemporaryDirectory() as tmp:
            manifest = load_plugin_manifest(_write_manifest(Path(tmp), payload))
            self.assertTrue(manifest.ui_hidden)


if __name__ == "__main__":
    unittest.main()
