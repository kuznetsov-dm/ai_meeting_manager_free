import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestSecretStorageEncryption(unittest.TestCase):
    def test_settings_store_roundtrip_secret(self) -> None:
        from aimn.core.settings_store import SettingsStore

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SettingsStore(root / "config" / "settings", repo_root=root)
            plugin_id = "service.secret_test"
            store.set_settings(
                plugin_id,
                {"api_key": "token-123", "plain": "ok"},
                secret_fields=["api_key"],
                preserve_secrets=[],
            )

            plain = store.get_settings(plugin_id, include_secrets=False)
            merged = store.get_settings(plugin_id, include_secrets=True)

            self.assertNotIn("api_key", plain)
            self.assertEqual(str(plain.get("plain", "")), "ok")
            self.assertEqual(str(merged.get("api_key", "")), "token-123")

    def test_secret_crypto_roundtrip_when_enabled(self) -> None:
        from aimn.core.secret_crypto import (
            decrypt_secret,
            encrypt_secret,
            secrets_encryption_enabled,
        )

        source = "my-secret-value"
        encrypted = encrypt_secret(source)
        restored = decrypt_secret(encrypted)
        self.assertEqual(restored, source)
        if os.name == "nt" and secrets_encryption_enabled():
            self.assertTrue(encrypted == source or encrypted.startswith("enc:v1:"))
        else:
            self.assertEqual(encrypted, source)

    def test_secrets_do_not_collide_for_same_suffix_plugin_ids(self) -> None:
        from aimn.core.settings_store import SettingsStore

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SettingsStore(root / "config" / "settings", repo_root=root)
            store.set_settings(
                "llm.demo",
                {"api_key": "one"},
                secret_fields=["api_key"],
                preserve_secrets=[],
            )
            store.set_settings(
                "service.demo",
                {"api_key": "two"},
                secret_fields=["api_key"],
                preserve_secrets=[],
            )

            self.assertEqual(store.get_settings("llm.demo", include_secrets=True).get("api_key"), "one")
            self.assertEqual(store.get_settings("service.demo", include_secrets=True).get("api_key"), "two")


if __name__ == "__main__":
    unittest.main()
