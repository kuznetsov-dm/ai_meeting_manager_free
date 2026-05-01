import json
import unittest
from pathlib import Path


class TestLocaleDeadKeys(unittest.TestCase):
    def test_removed_dead_prefixes_do_not_reappear(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        locale_dir = repo_root / "src" / "aimn" / "ui" / "locales"
        blocked_prefixes = (
            "management.",
            "meetings.management_create.",
            "settings.credentials.",
            "settings.paths.",
            "settings.models.",
        )
        blocked_keys = {
            "meetings.context.stage.health_check",
            "meetings.context.artifact.health_check",
            "plugins.button.sync_catalog",
            "plugins.button.import_license",
            "plugins.button.install_catalog",
            "plugins.button.update_catalog",
            "plugins.status.installable",
            "plugins.status.catalog_locked",
            "plugins.status.update_available",
            "plugins.status.available",
            "plugins.meta.catalog_version",
            "plugins.meta.trust",
            "plugins.meta.verification",
            "plugins.howto.remote_installable",
            "plugins.howto.remote_locked",
            "plugins.dialog.catalog_locked_message",
            "plugins.dialog.install_catalog_done_message",
            "plugins.dialog.sync_catalog_failed_title",
            "plugins.dialog.sync_catalog_done_title",
            "plugins.dialog.sync_catalog_done_message",
            "plugins.dialog.import_license",
            "plugins.dialog.import_license_failed_title",
            "plugins.dialog.import_license_done_title",
            "plugins.dialog.import_license_done_message",
        }

        for locale_name in ("en.json", "ru.json"):
            payload = json.loads((locale_dir / locale_name).read_text(encoding="utf-8"))
            keys = set(payload.keys())
            with self.subTest(locale=locale_name):
                for prefix in blocked_prefixes:
                    self.assertFalse(
                        any(key.startswith(prefix) for key in keys),
                        f"Found dead locale prefix {prefix!r} in {locale_name}",
                    )
                unexpected = keys & blocked_keys
                self.assertEqual(set(), unexpected)


if __name__ == "__main__":
    unittest.main()
