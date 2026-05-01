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

from aimn.core.plugin_entitlements_service import PluginEntitlementsService  # noqa: E402
from aimn.core.plugin_trust import canonical_json_bytes  # noqa: E402


def _write_trust_policy(root: Path) -> None:
    keypair = generate_test_rsa_keypair()
    rotated_keypair = generate_test_rsa_keypair("rotated")
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
                            },
                            {
                                "key_id": "rotated_2026",
                                "algorithm": "rsa-sha256",
                                "public_exponent": str(rotated_keypair["public_exponent"]),
                                "modulus_hex": str(rotated_keypair["modulus_hex"]),
                            },
                        ],
                    }
                }
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


class TestPluginEntitlementsService(unittest.TestCase):
    def test_unsigned_pro_entitlements_are_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True, exist_ok=True)
            _write_trust_policy(root)
            payload = {
                "platform_edition": {"enabled": True, "status": "active"},
                "plugins": {"service.pro_notes": {"status": "active"}},
            }
            (root / "config" / "plugin_entitlements.json").write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            snapshot = PluginEntitlementsService(root).load()

            self.assertFalse(snapshot.verified)
            self.assertEqual(snapshot.reason, "signature_missing")
            self.assertFalse(snapshot.payload["platform_edition"]["enabled"])
            self.assertEqual(snapshot.payload["plugins"]["service.pro_notes"]["status"], "inactive")

    def test_signed_pro_entitlements_are_accepted(self) -> None:
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
            signed = dict(payload)
            signed["_meta"] = {
                "publisher_id": "apogee",
                "signature_algorithm": "rsa-sha256",
                "signature": signature,
            }
            (root / "config" / "plugin_entitlements.json").write_text(
                json.dumps(signed, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            snapshot = PluginEntitlementsService(root).load()

            self.assertTrue(snapshot.verified)
            self.assertEqual(snapshot.reason, "verified")
            self.assertTrue(snapshot.payload["platform_edition"]["enabled"])
            self.assertEqual(snapshot.payload["plugins"]["service.pro_notes"]["status"], "active")

    def test_signed_pro_entitlements_accept_rotated_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_trust_policy(root)
            payload = {
                "platform_edition": {"enabled": True, "status": "active"},
                "plugins": {"service.pro_notes": {"status": "grace"}},
            }
            keypair = generate_test_rsa_keypair("rotated")
            signature = sign_rsa_sha256(
                canonical_json_bytes(payload),
                int(keypair["private_exponent"]),
                int(keypair["modulus"]),
            )
            signed = dict(payload)
            signed["_meta"] = {
                "publisher_id": "apogee",
                "signature_algorithm": "rsa-sha256",
                "signing_key_id": "rotated_2026",
                "signature": signature,
            }
            (root / "config" / "plugin_entitlements.json").write_text(
                json.dumps(signed, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            snapshot = PluginEntitlementsService(root).load()

            self.assertTrue(snapshot.verified)
            self.assertEqual(snapshot.payload["plugins"]["service.pro_notes"]["status"], "grace")

    def test_local_developer_entitlements_are_kept_in_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIMN_RELEASE_PROFILE", None)
            root = Path(tmp)
            (root / "config").mkdir(parents=True, exist_ok=True)
            _write_trust_policy(root)
            payload = {
                "edition": "platform_pro_dev",
                "platform_edition": {"enabled": True, "status": "active", "mode": "developer"},
                "plugins": {"service.pro_notes": {"status": "active"}},
            }
            (root / "config" / "plugin_entitlements.json").write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            snapshot = PluginEntitlementsService(root).load()

            self.assertFalse(snapshot.verified)
            self.assertEqual(snapshot.reason, "developer_override")
            self.assertTrue(snapshot.payload["platform_edition"]["enabled"])
            self.assertEqual(snapshot.payload["plugins"]["service.pro_notes"]["status"], "active")


if __name__ == "__main__":
    unittest.main()
