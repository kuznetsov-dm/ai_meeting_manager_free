import json
import unittest
from pathlib import Path


class TestLocaleModelManagementKeys(unittest.TestCase):
    def test_required_model_management_keys_exist_in_all_locales(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        locale_dir = repo_root / "src" / "aimn" / "ui" / "locales"
        required_keys = {
            "models.button.retest_failed",
            "models.status.ready",
            "models.status.cooling_down",
            "models.status.blocked",
            "models.status.blocked_for_account",
            "models.status.needs_test",
            "models.status.auth_issue",
            "models.badge.observed_success",
            "models.meta.observed_success",
            "models.meta.blocked_for_account",
            "models.meta.retry_after",
            "models.meta.last_checked",
            "models.meta.last_ok",
            "models.meta.provider_status",
            "models.note.retest_failed_complete",
        }

        for locale_name in ("en.json", "ru.json"):
            payload = json.loads((locale_dir / locale_name).read_text(encoding="utf-8"))
            missing = sorted(key for key in required_keys if not str(payload.get(key, "")).strip())
            with self.subTest(locale=locale_name):
                self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
