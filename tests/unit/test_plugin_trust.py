import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
test_root = Path(__file__).resolve().parent
for path in (repo_root, src_root, test_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from signing_helpers import generate_test_rsa_keypair, sign_rsa_sha256  # noqa: E402

from aimn.core.plugin_package_service import PluginPackageService  # noqa: E402
from aimn.core.plugin_trust import compute_package_checksum  # noqa: E402


def _plugin_payload(plugin_id: str, version: str) -> dict:
    return {
        "id": plugin_id,
        "name": plugin_id,
        "product_name": plugin_id,
        "highlights": "Highlights",
        "description": "Description",
        "version": version,
        "api_version": "1",
        "entrypoint": "partner_module:Plugin",
        "hooks": [{"name": "service.after_meeting"}],
        "artifacts": ["debug_json"],
        "distribution": {
            "owner_type": "third_party",
            "publisher_id": "partner",
            "pricing_model": "free",
            "catalog_enabled": True,
        },
    }


def _write_trust_policy(root: Path) -> None:
    keypair = generate_test_rsa_keypair()
    rotated_keypair = generate_test_rsa_keypair("rotated")
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "plugin_trust_policy.json").write_text(
        json.dumps(
            {
                "allow_untrusted_local_install": True,
                "publishers": {
                    "partner": {
                        "trust_level": "trusted_third_party",
                        "require_checksum": True,
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
                },
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_remote_catalog(
    root: Path,
    *,
    plugin_id: str,
    version: str,
    checksum: str,
    signature: str,
    signing_key_id: str = "primary",
    download_url: str = "",
) -> None:
    (root / "config" / "plugin_catalog.json").write_text(
        json.dumps(
            {
                "catalog_version": "2026-03-13",
                "plugins": [
                    {
                        "plugin_id": plugin_id,
                        "version": version,
                        "api_version": "1",
                        "stage_id": "service",
                        "owner_type": "third_party",
                        "publisher_id": "partner",
                        "pricing_model": "free",
                        "catalog_enabled": True,
                        "download_url": download_url,
                        "checksum_sha256": checksum,
                        "signature": signature,
                        "signature_algorithm": "rsa-sha256",
                        "signing_key_id": signing_key_id,
                    }
                ],
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def _create_plugin_zip(root: Path, *, plugin_id: str, version: str) -> Path:
    source_dir = root / "plugin_source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "plugin.json").write_text(
        json.dumps(_plugin_payload(plugin_id, version), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (source_dir / "partner_module.py").write_text("class Plugin:\n    pass\n", encoding="utf-8")
    package_zip = root / f"{plugin_id}.zip"
    with ZipFile(package_zip, "w") as archive:
        archive.write(source_dir / "plugin.json", arcname=f"{plugin_id}/plugin.json")
        archive.write(source_dir / "partner_module.py", arcname=f"{plugin_id}/partner_module.py")
    return package_zip


class TestPluginTrust(unittest.TestCase):
    def test_install_from_catalog_downloads_and_verifies_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_zip = _create_plugin_zip(root, plugin_id="service.partner_notes", version="1.2.0")
            checksum = compute_package_checksum(package_zip)
            keypair = generate_test_rsa_keypair()
            signature = sign_rsa_sha256(
                f"service.partner_notes:1.2.0:{checksum}".encode("utf-8"),
                int(keypair["private_exponent"]),
                int(keypair["modulus"]),
            )
            _write_trust_policy(root)
            _write_remote_catalog(
                root,
                plugin_id="service.partner_notes",
                version="1.2.0",
                checksum=checksum,
                signature=signature,
                download_url=package_zip.as_uri(),
            )

            result = PluginPackageService(root).install_from_catalog("service.partner_notes")

            self.assertEqual(result.plugin_id, "service.partner_notes")
            self.assertEqual(result.trust_level, "trusted_third_party")
            self.assertEqual(result.verification_state, "verified")

    def test_install_verifies_signed_trusted_third_party_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_zip = _create_plugin_zip(root, plugin_id="service.partner_notes", version="1.2.0")
            checksum = compute_package_checksum(package_zip)
            keypair = generate_test_rsa_keypair()
            signature = sign_rsa_sha256(
                f"service.partner_notes:1.2.0:{checksum}".encode("utf-8"),
                int(keypair["private_exponent"]),
                int(keypair["modulus"]),
            )
            _write_trust_policy(root)
            _write_remote_catalog(
                root,
                plugin_id="service.partner_notes",
                version="1.2.0",
                checksum=checksum,
                signature=signature,
            )

            result = PluginPackageService(root).install_from_path(package_zip)

            self.assertEqual(result.trust_level, "trusted_third_party")
            self.assertEqual(result.verification_state, "verified")
            installed_state = json.loads((root / "config" / "installed_plugins.json").read_text(encoding="utf-8"))
            item = installed_state["plugins"]["service.partner_notes"]
            self.assertEqual(item["trust_level"], "trusted_third_party")
            self.assertEqual(item["verification_state"], "verified")
            self.assertTrue(item["checksum_verified"])
            self.assertTrue(item["signature_verified"])
            self.assertEqual(item["signing_key_id"], "primary")

    def test_install_accepts_rotated_publisher_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_zip = _create_plugin_zip(root, plugin_id="service.partner_notes", version="1.2.0")
            checksum = compute_package_checksum(package_zip)
            keypair = generate_test_rsa_keypair("rotated")
            signature = sign_rsa_sha256(
                f"service.partner_notes:1.2.0:{checksum}".encode("utf-8"),
                int(keypair["private_exponent"]),
                int(keypair["modulus"]),
            )
            _write_trust_policy(root)
            _write_remote_catalog(
                root,
                plugin_id="service.partner_notes",
                version="1.2.0",
                checksum=checksum,
                signature=signature,
                signing_key_id="rotated_2026",
            )

            result = PluginPackageService(root).install_from_path(package_zip)

            self.assertEqual(result.trust_level, "trusted_third_party")
            installed_state = json.loads((root / "config" / "installed_plugins.json").read_text(encoding="utf-8"))
            self.assertEqual(
                installed_state["plugins"]["service.partner_notes"]["signing_key_id"],
                "rotated_2026",
            )

    def test_install_rejects_invalid_signature_for_trusted_third_party_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_zip = _create_plugin_zip(root, plugin_id="service.partner_notes", version="1.2.0")
            checksum = compute_package_checksum(package_zip)
            _write_trust_policy(root)
            _write_remote_catalog(
                root,
                plugin_id="service.partner_notes",
                version="1.2.0",
                checksum=checksum,
                signature="ZmFrZV9zaWduYXR1cmU=",
            )

            with self.assertRaisesRegex(ValueError, "plugin_package_verification_failed:signature_invalid"):
                PluginPackageService(root).install_from_path(package_zip)


if __name__ == "__main__":
    unittest.main()
