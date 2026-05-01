# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_health_settings_controller import PluginHealthSettingsController


class TestPluginHealthSettingsController(unittest.TestCase):
    def test_required_setting_groups_respect_when_rules(self) -> None:
        groups = PluginHealthSettingsController.required_setting_groups(
            "llm.demo",
            {"provider": "cloud"},
            capabilities={
                "health": {
                    "required_settings": [
                        {"label": "API key", "keys": ["api_key"], "when": {"provider": "cloud"}},
                        {"label": "Ignored", "keys": ["ignored"], "when": {"provider": "local"}},
                    ]
                }
            },
            schema=None,
            looks_like_secret_key=lambda _key: False,
        )

        self.assertEqual(groups, [("API key", ["api_key"])])

    def test_required_setting_groups_fall_back_to_single_secret(self) -> None:
        schema = SimpleNamespace(settings=[SimpleNamespace(key="api_key"), SimpleNamespace(key="timeout_seconds")])

        groups = PluginHealthSettingsController.required_setting_groups(
            "llm.demo",
            {},
            capabilities={},
            schema=schema,
            looks_like_secret_key=lambda key: str(key) == "api_key",
        )

        self.assertEqual(groups, [("Secret", ["api_key"])])

    def test_run_required_settings_checks_builds_issue_objects(self) -> None:
        checks, issues = PluginHealthSettingsController.run_required_settings_checks(
            stage_params={},
            settings={},
            groups=[("API key", ["api_key"])],
            value_resolver=lambda stage_params, settings, key: stage_params.get(key) or settings.get(key),
            issue_factory=lambda code, summary, hint: {
                "code": code,
                "summary": summary,
                "hint": hint,
            },
            normalize_code=lambda label, fallback: f"{label.lower().replace(' ', '_')}::{fallback}",
        )

        self.assertEqual(checks, ["required_settings"])
        self.assertEqual(
            issues,
            [
                {
                    "code": "api_key::required_setting_missing",
                    "summary": "Missing required setting: API key.",
                    "hint": "Add the API key in Settings before running the stage.",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
