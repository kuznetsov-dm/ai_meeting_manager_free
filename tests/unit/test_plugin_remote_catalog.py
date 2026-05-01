import json
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_catalog import create_default_catalog  # noqa: E402
from aimn.core.plugins_config import PluginsConfig  # noqa: E402


def _write_remote_catalog(root: Path, entries: list[dict]) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "plugin_catalog.json").write_text(
        json.dumps({"catalog_version": "2026-03-13", "plugins": entries}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def _write_distribution(root: Path, payload: dict) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "plugin_distribution.json").write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (config_dir / "plugin_entitlements.json").write_text(
        json.dumps({"platform_edition": {"enabled": False, "status": "inactive"}}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (config_dir / "installed_plugins.json").write_text(
        json.dumps({"version": "1", "plugins": {}}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def _write_local_plugin(root: Path, plugin_id: str, version: str) -> None:
    plugin_dir = root / "plugins" / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "name": plugin_id,
                "product_name": plugin_id,
                "highlights": "Highlights",
                "description": "Description",
                "version": version,
                "api_version": "1",
                "entrypoint": "plugins.demo.plugin:Plugin",
                "hooks": [{"name": "service.after_meeting"}],
                "artifacts": ["debug_json"],
                "ui_stage": "service",
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


class TestPluginRemoteCatalog(unittest.TestCase):
    def test_remote_only_free_plugin_appears_as_installable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_distribution(root, {"baseline_plugin_ids": []})
            _write_remote_catalog(
                root,
                [
                    {
                        "plugin_id": "service.remote_notes",
                        "version": "1.2.0",
                        "api_version": "1",
                        "stage_id": "service",
                        "owner_type": "third_party",
                        "pricing_model": "free",
                        "catalog_enabled": True,
                        "name": "Remote Notes",
                        "product_name": "Remote Notes",
                        "highlights": "From catalog",
                        "description": "Remote-only plugin",
                        "download_url": "https://example.test/service.remote_notes-1.2.0.zip",
                    }
                ],
            )

            catalog = create_default_catalog(root, config=PluginsConfig({"allowlist": {"ids": []}}))
            plugin = catalog.plugin_by_id("service.remote_notes")

            self.assertIsNotNone(plugin)
            assert plugin is not None
            self.assertTrue(plugin.remote_only)
            self.assertFalse(plugin.installed)
            self.assertEqual(plugin.runtime_state, "installable")
            self.assertEqual(plugin.download_url, "https://example.test/service.remote_notes-1.2.0.zip")

    def test_remote_only_paid_plugin_can_appear_locked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_distribution(
                root,
                {
                    "baseline_plugin_ids": [],
                    "default_optional_requires_platform_edition": True,
                    "plugin_overrides": {
                        "service.remote_paid": {
                            "pricing_model": "subscription",
                            "catalog_enabled": True,
                        }
                    },
                },
            )
            _write_remote_catalog(
                root,
                [
                    {
                        "plugin_id": "service.remote_paid",
                        "version": "2.0.0",
                        "api_version": "1",
                        "stage_id": "service",
                        "owner_type": "third_party",
                        "pricing_model": "subscription",
                        "catalog_enabled": True,
                        "name": "Remote Paid",
                        "product_name": "Remote Paid",
                    }
                ],
            )

            catalog = create_default_catalog(root, config=PluginsConfig({"allowlist": {"ids": []}}))
            plugin = catalog.plugin_by_id("service.remote_paid")

            self.assertIsNotNone(plugin)
            assert plugin is not None
            self.assertEqual(plugin.runtime_state, "installable_locked")
            self.assertFalse(plugin.entitled)

    def test_local_plugin_is_augmented_with_remote_update_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_distribution(root, {"baseline_plugin_ids": []})
            _write_local_plugin(root, "service.demo", "1.0.0")
            _write_remote_catalog(
                root,
                [
                    {
                        "plugin_id": "service.demo",
                        "version": "1.4.0",
                        "api_version": "1",
                        "stage_id": "service",
                        "owner_type": "first_party",
                        "pricing_model": "free",
                        "catalog_enabled": True,
                        "provider_name": "Apogee",
                    }
                ],
            )

            catalog = create_default_catalog(root, config=PluginsConfig({"allowlist": {"ids": ["service.demo"]}}))
            plugin = catalog.plugin_by_id("service.demo")

            self.assertIsNotNone(plugin)
            assert plugin is not None
            self.assertFalse(plugin.remote_only)
            self.assertTrue(plugin.has_update)
            self.assertEqual(plugin.remote_version, "1.4.0")
            self.assertEqual(plugin.provider_name, "Apogee")


if __name__ == "__main__":
    unittest.main()
