# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_health_local_prereq_controller import PluginHealthLocalPrereqController


class TestPluginHealthLocalPrereqController(unittest.TestCase):
    def test_check_local_binary_prerequisites_reports_missing_binary(self) -> None:
        issues: list[dict] = []

        ran = PluginHealthLocalPrereqController.check_local_binary_prerequisites(
            {},
            {},
            capabilities={"runtime": {"local_binary": {"setting_key": "binary_path", "label": "Tool"}}},
            value_resolver=lambda stage_params, settings, key: stage_params.get(key) or settings.get(key),
            coerce_bool=bool,
            resolve_existing_path=lambda raw, env_key, executable: "",
            issue_factory=lambda code, summary, detail, hint: {
                "code": code,
                "summary": summary,
                "detail": detail,
                "hint": hint,
            },
            issues=issues,
        )

        self.assertTrue(ran)
        self.assertEqual(issues[0]["code"], "local_binary_missing")

    def test_check_local_model_cache_prerequisites_reports_not_cached(self) -> None:
        issues: list[dict] = []

        ran = PluginHealthLocalPrereqController.check_local_model_cache_prerequisites(
            {"model_id": "demo-model", "allow_download": False},
            {},
            capabilities={"health": {"local_model_cache": {"cache_dir_key": "cache_dir"}}},
            value_resolver=lambda stage_params, settings, key: stage_params.get(key) or settings.get(key),
            coerce_bool=bool,
            resolve_existing_path=lambda raw, env_key, executable: "",
            resolve_existing_dir=lambda raw, env_key: str(raw or ""),
            local_model_present=lambda cache_dir, globs: False,
            issue_factory=lambda code, summary, detail, hint: {
                "code": code,
                "summary": summary,
                "detail": detail,
                "hint": hint,
            },
            issues=issues,
        )

        self.assertTrue(ran)
        self.assertEqual(issues[0]["code"], "local_model_not_cached")

    def test_run_local_prereq_checks_adds_check_name_when_any_rule_runs(self) -> None:
        checks, issues = PluginHealthLocalPrereqController.run_local_prereq_checks(
            "llm.demo",
            {"binary_path": "bin/demo"},
            {},
            capabilities={"runtime": {"local_binary": {"setting_key": "binary_path"}}},
            value_resolver=lambda stage_params, settings, key: stage_params.get(key) or settings.get(key),
            coerce_bool=bool,
            resolve_existing_path=lambda raw, env_key, executable: str(raw or ""),
            resolve_existing_dir=lambda raw, env_key: str(raw or ""),
            local_model_present=lambda cache_dir, globs: False,
            issue_factory=lambda code, summary, detail, hint: {
                "code": code,
                "summary": summary,
                "detail": detail,
                "hint": hint,
            },
        )

        self.assertEqual(checks, ["local_prerequisites"])
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
