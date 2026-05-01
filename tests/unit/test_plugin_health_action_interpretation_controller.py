import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_health_action_interpretation_controller import (  # noqa: E402
    PluginHealthActionInterpretationController,
)


class TestPluginHealthActionInterpretationController(unittest.TestCase):
    def test_warning_issue_requires_full_check_and_health_action(self) -> None:
        issue = PluginHealthActionInterpretationController.issue_from_action_warnings(
            action_id="test_connection",
            message="connection_ok",
            data={"detail": "mock output used"},
            warnings=["mock_fallback"],
            model_id="glm-4.5-air",
            full_check=True,
            normalize_code=lambda value, fallback: f"norm:{value}:{fallback}",
            issue_factory=lambda code, summary, detail, hint: {
                "code": code,
                "summary": summary,
                "detail": detail,
                "hint": hint,
            },
        )

        self.assertEqual(issue["code"], "norm:test_connection:check")
        self.assertIn("returned warnings", issue["summary"])
        self.assertIn("model_id='glm-4.5-air'", issue["detail"])
        self.assertIn("mock_fallback", issue["detail"])
        self.assertIn("mock output used", issue["detail"])

    def test_warning_issue_ignores_non_health_action_or_quick_check(self) -> None:
        issue_quick = PluginHealthActionInterpretationController.issue_from_action_warnings(
            action_id="test_connection",
            message="connection_ok",
            data={},
            warnings=["mock_fallback"],
            model_id="",
            full_check=False,
            normalize_code=lambda value, fallback: value or fallback,
            issue_factory=lambda code, summary, detail, hint: (code, summary, detail, hint),
        )
        issue_non_health = PluginHealthActionInterpretationController.issue_from_action_warnings(
            action_id="list_models",
            message="ok",
            data={},
            warnings=["mock_fallback"],
            model_id="",
            full_check=True,
            normalize_code=lambda value, fallback: value or fallback,
            issue_factory=lambda code, summary, detail, hint: (code, summary, detail, hint),
        )

        self.assertIsNone(issue_quick)
        self.assertIsNone(issue_non_health)

    def test_failure_issue_adds_server_quick_fix_for_connection_failure(self) -> None:
        issue = PluginHealthActionInterpretationController.issue_from_action_failure(
            plugin_id="llm.ollama",
            action_id="test_connection",
            message="connection_failed",
            data={},
            model_id="",
            plugin_capabilities={"health": {"server": {"auto_start_action": "start_server"}}},
            normalize_code=lambda value, fallback: f"norm:{value}:{fallback}",
            quick_fix_factory=lambda action_id, label, payload: {
                "action_id": action_id,
                "label": label,
                "payload": payload,
            },
            issue_factory=lambda code, summary, detail, hint, quick_fix=None: {
                "code": code,
                "summary": summary,
                "detail": detail,
                "hint": hint,
                "quick_fix": quick_fix,
            },
        )

        self.assertEqual(issue["code"], "norm:connection_failed:action_test_connection_failed")
        self.assertIn("connection_failed", issue["summary"])
        self.assertIn("start local server", issue["hint"].lower())
        self.assertEqual(issue["quick_fix"]["action_id"], "start_server")
        self.assertEqual(issue["quick_fix"]["payload"]["timeout_seconds"], 12)

    def test_failure_issue_for_missing_model_uses_model_specific_detail(self) -> None:
        issue = PluginHealthActionInterpretationController.issue_from_action_failure(
            plugin_id="llm.openrouter",
            action_id="test_model",
            message="model_not_found",
            data={"status": "404"},
            model_id="m-selected",
            plugin_capabilities={},
            normalize_code=lambda value, fallback: f"norm:{value}:{fallback}",
            quick_fix_factory=lambda action_id, label, payload: {
                "action_id": action_id,
                "label": label,
                "payload": payload,
            },
            issue_factory=lambda code, summary, detail, hint, quick_fix=None: {
                "code": code,
                "summary": summary,
                "detail": detail,
                "hint": hint,
                "quick_fix": quick_fix,
            },
        )

        self.assertEqual(issue["detail"], "model_id='m-selected'")
        self.assertIn("download", issue["hint"].lower())
        self.assertIsNone(issue["quick_fix"])

    def test_extract_models_and_installed_models(self) -> None:
        data = {
            "models": [
                {"model_id": "m1", "installed": True},
                {"id": "m2", "status": "ready"},
                {"model_id": "m3", "installed": False},
                {"id": "m4", "status": "remote"},
                "bad",
            ]
        }

        self.assertEqual(
            PluginHealthActionInterpretationController.extract_models(data),
            ["m1", "m2", "m3", "m4"],
        )
        self.assertEqual(
            PluginHealthActionInterpretationController.extract_installed_models(data),
            ["m1", "m2"],
        )


if __name__ == "__main__":
    unittest.main()
