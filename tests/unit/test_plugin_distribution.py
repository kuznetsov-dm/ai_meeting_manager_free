import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
test_root = Path(__file__).resolve().parent
for path in (repo_root, src_root, test_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from signing_helpers import generate_test_rsa_keypair, sign_rsa_sha256  # noqa: E402

from aimn.core.plugin_catalog import create_default_catalog  # noqa: E402
from aimn.core.plugin_distribution import PluginDistributionResolver  # noqa: E402
from aimn.core.plugin_trust import canonical_json_bytes  # noqa: E402


def _write_plugin(root: Path, plugin_id: str, version: str, entrypoint: str) -> None:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": plugin_id,
        "name": plugin_id,
        "product_name": plugin_id,
        "highlights": "Highlights",
        "description": "Description",
        "version": version,
        "api_version": "1",
        "entrypoint": entrypoint,
        "hooks": [{"name": "transcribe.run"}],
        "artifacts": ["transcript"],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _write_trust_policy(root: Path, *, publisher_id: str = "apogee", trust_level: str = "first_party") -> None:
    keypair = generate_test_rsa_keypair()
    (root / "config" / "plugin_trust_policy.json").write_text(
        json.dumps(
            {
                "publishers": {
                    publisher_id: {
                        "trust_level": trust_level,
                        "require_checksum": False,
                        "require_signature": True,
                        "signature": {
                            "algorithm": "rsa-sha256",
                            "public_exponent": str(keypair["public_exponent"]),
                            "modulus_hex": str(keypair["modulus_hex"]),
                        },
                    }
                }
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_signed_entitlements(root: Path, payload: dict, *, publisher_id: str = "apogee") -> None:
    keypair = generate_test_rsa_keypair()
    signature = sign_rsa_sha256(
        canonical_json_bytes(payload),
        int(keypair["private_exponent"]),
        int(keypair["modulus"]),
    )
    signed = dict(payload)
    signed["_meta"] = {
        "publisher_id": publisher_id,
        "signature_algorithm": "rsa-sha256",
        "signature": signature,
    }
    (root / "config" / "plugin_entitlements.json").write_text(
        json.dumps(signed, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


class TestPluginDistribution(unittest.TestCase):
    def test_installed_root_overrides_bundled_root_for_same_plugin_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            bundled = app_root / "plugins"
            installed = app_root / "config" / "plugins_installed"
            (app_root / "config").mkdir(parents=True, exist_ok=True)
            _write_plugin(bundled, "transcription.sample", "1.0.0", "plugins.transcription.sample:Plugin")
            _write_plugin(
                installed,
                "transcription.sample",
                "2.0.0",
                "transcription_sample.plugin:Plugin",
            )
            (app_root / "config" / "plugin_distribution.json").write_text(
                json.dumps({"baseline_plugin_ids": ["transcription.sample"]}, ensure_ascii=True),
                encoding="utf-8",
            )
            (app_root / "config" / "plugin_entitlements.json").write_text(
                json.dumps({"platform_edition": {"enabled": False, "status": "inactive"}}, ensure_ascii=True),
                encoding="utf-8",
            )
            (app_root / "config" / "installed_plugins.json").write_text(
                json.dumps({"version": "1", "plugins": {}}, ensure_ascii=True),
                encoding="utf-8",
            )

            catalog = create_default_catalog(app_root)
            plugin = catalog.plugin_by_id("transcription.sample")

            self.assertIsNotNone(plugin)
            assert plugin is not None
            self.assertEqual(plugin.version, "2.0.0")
            self.assertEqual(plugin.source_kind, "installed")
            self.assertTrue(plugin.included_in_core)
            self.assertTrue(plugin.entitled)

    def test_platform_locked_optional_plugin_without_platform_edition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            bundled = app_root / "plugins"
            (app_root / "config").mkdir(parents=True, exist_ok=True)
            _write_plugin(bundled, "llm.optional_paid", "1.0.0", "plugins.llm.optional_paid:Plugin")
            (app_root / "config" / "plugin_distribution.json").write_text(
                json.dumps(
                    {
                        "baseline_plugin_ids": [],
                        "default_optional_requires_platform_edition": True,
                        "plugin_overrides": {
                            "llm.optional_paid": {
                                "pricing_model": "subscription",
                                "catalog_enabled": True,
                            }
                        },
                    },
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )
            (app_root / "config" / "plugin_entitlements.json").write_text(
                json.dumps({"platform_edition": {"enabled": False, "status": "inactive"}}, ensure_ascii=True),
                encoding="utf-8",
            )
            (app_root / "config" / "installed_plugins.json").write_text(
                json.dumps({"version": "1", "plugins": {}}, ensure_ascii=True),
                encoding="utf-8",
            )

            catalog = create_default_catalog(app_root)
            plugin = catalog.plugin_by_id("llm.optional_paid")

            self.assertIsNotNone(plugin)
            assert plugin is not None
            self.assertFalse(plugin.entitled)
            self.assertEqual(plugin.access_state, "platform_locked")

    def test_active_subscription_entitlement_unlocks_optional_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            (app_root / "config").mkdir(parents=True, exist_ok=True)
            resolver = PluginDistributionResolver(app_root)
            manifest_path = app_root / "plugins" / "service.optional"
            manifest_path.mkdir(parents=True, exist_ok=True)
            plugin_manifest_path = manifest_path / "plugin.json"
            plugin_manifest_path.write_text(
                json.dumps(
                    {
                        "id": "service.optional",
                        "name": "service.optional",
                        "product_name": "service.optional",
                        "highlights": "Highlights",
                        "description": "Description",
                        "version": "1.0.0",
                        "api_version": "1",
                        "entrypoint": "plugins.service.optional:Plugin",
                        "hooks": [{"name": "service.after_meeting"}],
                        "artifacts": ["debug_json"],
                        "distribution": {
                            "pricing_model": "subscription",
                            "catalog_enabled": True
                        }
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (app_root / "config" / "plugin_distribution.json").write_text(
                json.dumps(
                    {
                        "default_optional_requires_platform_edition": True,
                        "plugin_overrides": {
                            "service.optional": {
                                "pricing_model": "subscription",
                                "catalog_enabled": True
                            }
                        }
                    },
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )
            _write_trust_policy(app_root)
            _write_signed_entitlements(
                app_root,
                {
                    "platform_edition": {"enabled": True, "status": "active"},
                    "plugins": {"service.optional": {"status": "active"}},
                },
            )
            (app_root / "config" / "installed_plugins.json").write_text(
                json.dumps({"version": "1", "plugins": {}}, ensure_ascii=True),
                encoding="utf-8",
            )

            # Recreate resolver after config files exist.
            resolver = PluginDistributionResolver(app_root)
            from aimn.core.plugin_manifest import load_plugin_manifest  # noqa: E402

            manifest = load_plugin_manifest(plugin_manifest_path)
            access = resolver.resolve_plugin("service.optional", manifest.distribution, plugin_manifest_path)

            self.assertTrue(access.entitled)
            self.assertEqual(access.access_state, "active")

    def test_core_free_catalog_keeps_only_bundled_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AIMN_RELEASE_PROFILE": "core_free"},
            clear=False,
        ):
            app_root = Path(tmp)
            bundled = app_root / "plugins"
            (app_root / "config").mkdir(parents=True, exist_ok=True)
            _write_plugin(
                bundled,
                "transcription.whisperadvanced",
                "1.0.0",
                "plugins.transcription.whisper_advanced.whisper_advanced:Plugin",
            )
            _write_plugin(
                bundled,
                "llm.llama_cli",
                "1.0.0",
                "plugins.llm.llama_cli.llama_cli:Plugin",
            )
            _write_plugin(
                bundled,
                "management.unified",
                "1.0.0",
                "plugins.management.unified.unified:Plugin",
            )
            (app_root / "config" / "plugin_entitlements.json").write_text(
                json.dumps({"platform_edition": {"enabled": False, "status": "inactive"}}, ensure_ascii=True),
                encoding="utf-8",
            )
            (app_root / "config" / "installed_plugins.json").write_text(
                json.dumps({"version": "1", "plugins": {}}, ensure_ascii=True),
                encoding="utf-8",
            )

            catalog = create_default_catalog(app_root)

            self.assertIsNotNone(catalog.plugin_by_id("transcription.whisperadvanced"))
            self.assertIsNotNone(catalog.plugin_by_id("llm.llama_cli"))
            self.assertIsNone(catalog.plugin_by_id("management.unified"))


if __name__ == "__main__":
    unittest.main()

