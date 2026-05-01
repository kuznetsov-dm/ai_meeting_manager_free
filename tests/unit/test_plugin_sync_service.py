import json
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
test_root = Path(__file__).resolve().parent
for path in (repo_root, src_root, test_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from signing_helpers import generate_test_rsa_keypair, sign_rsa_sha256  # noqa: E402

from aimn.core.plugin_sync_service import PluginSyncService  # noqa: E402
from aimn.core.plugin_trust import canonical_json_bytes  # noqa: E402


def _write_trust_policy(root: Path) -> None:
    keypair = generate_test_rsa_keypair()
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "plugin_trust_policy.json").write_text(
        json.dumps(
            {
                "publishers": {
                    "apogee": {
                        "trust_level": "first_party",
                        "require_checksum": False,
                        "require_signature": True,
                        "signature_keys": [
                            {
                                "key_id": "primary",
                                "algorithm": "rsa-sha256",
                                "public_exponent": str(keypair["public_exponent"]),
                                "modulus_hex": str(keypair["modulus_hex"]),
                            }
                        ],
                    }
                }
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


class TestPluginSyncService(unittest.TestCase):
    def test_sync_catalog_from_configured_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "catalog_source.json"
            source_path.write_text(
                json.dumps(
                    {
                        "catalog_version": "2026-03-13",
                        "plugins": [
                            {
                                "plugin_id": "service.remote_notes",
                                "version": "1.2.0",
                                "api_version": "1",
                                "stage_id": "service",
                                "owner_type": "third_party",
                                "pricing_model": "free",
                                "catalog_enabled": True,
                            }
                        ],
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "config" / "plugin_sync.json").write_text(
                json.dumps({"catalog_url": str(source_path)}, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            result = PluginSyncService(root).sync_catalog()

            self.assertEqual(result.plugin_count, 1)
            target_path = root / "config" / "plugin_catalog.json"
            self.assertEqual(result.path, target_path)
            payload = json.loads(target_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["plugins"][0]["plugin_id"], "service.remote_notes")

    def test_import_signed_entitlements_writes_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_trust_policy(root)
            payload = {
                "platform_edition": {"enabled": True, "status": "active"},
                "plugins": {"service.pro_notes": {"status": "active"}},
            }
            keypair = generate_test_rsa_keypair()
            signature = sign_rsa_sha256(
                canonical_json_bytes(payload),
                int(keypair["private_exponent"]),
                int(keypair["modulus"]),
            )
            source_path = root / "license.json"
            source_path.write_text(
                json.dumps(
                    {
                        **payload,
                        "_meta": {
                            "publisher_id": "apogee",
                            "signature_algorithm": "rsa-sha256",
                            "signing_key_id": "primary",
                            "signature": signature,
                        },
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = PluginSyncService(root).import_entitlements(source_path)

            self.assertTrue(result.verified)
            self.assertTrue(result.platform_edition_enabled)
            stored = json.loads((root / "config" / "plugin_entitlements.json").read_text(encoding="utf-8"))
            self.assertTrue(stored["platform_edition"]["enabled"])

    def test_import_invalid_pro_entitlements_does_not_overwrite_existing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_trust_policy(root)
            (root / "config" / "plugin_entitlements.json").write_text(
                json.dumps(
                    {"platform_edition": {"enabled": False, "status": "inactive"}},
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            source_path = root / "license_invalid.json"
            source_path.write_text(
                json.dumps(
                    {
                        "platform_edition": {"enabled": True, "status": "active"},
                        "plugins": {"service.pro_notes": {"status": "active"}},
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "plugin_entitlements_import_invalid:signature_missing"):
                PluginSyncService(root).import_entitlements(source_path)

            stored = json.loads((root / "config" / "plugin_entitlements.json").read_text(encoding="utf-8"))
            self.assertFalse(stored["platform_edition"]["enabled"])


if __name__ == "__main__":
    unittest.main()
