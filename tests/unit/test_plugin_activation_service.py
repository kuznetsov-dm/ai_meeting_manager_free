import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
test_root = Path(__file__).resolve().parent
for path in (repo_root, src_root, test_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from signing_helpers import generate_test_rsa_keypair, sign_rsa_sha256  # noqa: E402

from aimn.core.plugin_activation_service import PluginActivationService  # noqa: E402
from aimn.core.plugin_catalog import create_default_catalog  # noqa: E402
from aimn.core.plugin_trust import canonical_json_bytes  # noqa: E402
from aimn.core.plugins_config import PluginsConfig  # noqa: E402


def _write_plugin(root: Path, plugin_id: str, *, default_visibility: str = "visible") -> None:
    plugin_dir = root / "plugins" / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": plugin_id,
        "name": plugin_id,
        "product_name": plugin_id,
        "highlights": "Highlights",
        "description": "Description",
        "version": "1.0.0",
        "api_version": "1",
        "entrypoint": "plugins.demo.plugin:Plugin",
        "hooks": [{"name": "service.after_meeting"}],
        "artifacts": ["debug_json"],
        "ui_stage": "service",
        "default_visibility": default_visibility,
        "distribution": {
            "pricing_model": "subscription",
            "catalog_enabled": True,
        },
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


class TestPluginActivationService(unittest.TestCase):
    def test_apply_to_registry_payload_overrides_default_lists(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            activation = PluginActivationService(root)
            activation.set_enabled("service.demo", False)
            payload = {"allowlist": {"ids": ["service.demo", "service.other"]}}

            merged = activation.apply_to_registry_payload(payload)

            self.assertEqual(merged["allowlist"]["ids"], ["service.other"])

    def test_hidden_locked_plugin_stays_hidden_until_activated_or_entitled(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True, exist_ok=True)
            _write_plugin(root, "service.hidden_paid", default_visibility="hidden")
            (root / "config" / "plugin_distribution.json").write_text(
                json.dumps(
                    {
                        "baseline_plugin_ids": [],
                        "default_optional_requires_platform_edition": True,
                        "plugin_overrides": {
                            "service.hidden_paid": {
                                "pricing_model": "subscription",
                                "catalog_enabled": True,
                            }
                        },
                    },
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )
            (root / "config" / "plugin_entitlements.json").write_text(
                json.dumps({"platform_edition": {"enabled": False, "status": "inactive"}}, ensure_ascii=True),
                encoding="utf-8",
            )
            (root / "config" / "installed_plugins.json").write_text(
                json.dumps({"version": "1", "plugins": {}}, ensure_ascii=True),
                encoding="utf-8",
            )

            catalog = create_default_catalog(root, config=PluginsConfig({"allowlist": {"ids": []}}))
            self.assertIsNone(catalog.plugin_by_id("service.hidden_paid"))

            activation = PluginActivationService(root)
            activation.set_enabled("service.hidden_paid", True)
            visible = create_default_catalog(root, config=PluginsConfig({"allowlist": {"ids": []}}))
            plugin = visible.plugin_by_id("service.hidden_paid")

            self.assertIsNotNone(plugin)
            assert plugin is not None
            self.assertEqual(plugin.runtime_state, "visible_locked")

    def test_entitled_plugin_is_available_inactive_until_user_activates_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True, exist_ok=True)
            _write_plugin(root, "service.optional_paid")
            (root / "config" / "plugin_distribution.json").write_text(
                json.dumps(
                    {
                        "baseline_plugin_ids": [],
                        "default_optional_requires_platform_edition": True,
                        "plugin_overrides": {
                            "service.optional_paid": {
                                "pricing_model": "subscription",
                                "catalog_enabled": True,
                            }
                        },
                    },
                    ensure_ascii=True,
                ),
                encoding="utf-8",
            )
            _write_trust_policy(root)
            _write_signed_entitlements(
                root,
                {
                    "platform_edition": {"enabled": True, "status": "active"},
                    "plugins": {"service.optional_paid": {"status": "active"}},
                },
            )
            (root / "config" / "installed_plugins.json").write_text(
                json.dumps({"version": "1", "plugins": {}}, ensure_ascii=True),
                encoding="utf-8",
            )

            activation = PluginActivationService(root)
            activation.set_enabled("service.optional_paid", False)
            inactive_catalog = create_default_catalog(root, config=PluginsConfig({"allowlist": {"ids": []}}))
            inactive_plugin = inactive_catalog.plugin_by_id("service.optional_paid")

            self.assertIsNotNone(inactive_plugin)
            assert inactive_plugin is not None
            self.assertEqual(inactive_plugin.runtime_state, "available_inactive")

            activation.set_enabled("service.optional_paid", True)
            active_catalog = create_default_catalog(root, config=PluginsConfig({"allowlist": {"ids": []}}))
            active_plugin = active_catalog.plugin_by_id("service.optional_paid")

            self.assertIsNotNone(active_plugin)
            assert active_plugin is not None
            self.assertEqual(active_plugin.runtime_state, "active")


if __name__ == "__main__":
    unittest.main()
