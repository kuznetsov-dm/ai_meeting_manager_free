# ruff: noqa: E402
import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_health_action_check_controller import (
    PluginHealthActionCheckController,  # noqa: E402
)
from aimn.core.plugin_health_action_probe_controller import (
    PluginHealthActionProbeController,  # noqa: E402
)
from aimn.core.plugin_health_model_policy_controller import (
    PluginHealthModelPolicyController,  # noqa: E402
)


class TestPluginHealthActionCheckController(unittest.TestCase):
    def test_full_check_requires_installed_model_from_list_models(self) -> None:
        calls: list[tuple[str, str, dict, dict | None]] = []

        def invoke_action(plugin_id: str, action_id: str, payload: dict, settings_override: dict | None) -> object:
            calls.append((plugin_id, action_id, dict(payload), dict(settings_override or {})))
            if action_id == "list_models":
                return {
                    "status": "success",
                    "message": "models_loaded",
                    "data": {
                        "models": [
                            {"model_id": "installed-model", "installed": True},
                        ]
                    },
                }
            return {"status": "success", "message": "model_ok"}

        checks, issues = PluginHealthActionCheckController.run_action_checks(
            plugin_id="llm.demo",
            settings={"model_id": "installed-model", "timeout_seconds": 30},
            stage_params={},
            full_check=True,
            action_ids={"list_models", "test_model"},
            plugin_capabilities={"models": {"storage": "local"}},
            coerce_bool=lambda value: bool(value),
            cap_get=lambda payload, *keys, default=None: (
                payload.get(keys[0], {}) if isinstance(payload, dict) and keys else default
            ),
            resolve_model_id=PluginHealthModelPolicyController.resolve_model_id,
            settings_override_for_actions=PluginHealthActionProbeController.settings_override_for_actions,
            preflight_settings_override=PluginHealthModelPolicyController.preflight_settings_override,
            models_storage_is_local=PluginHealthModelPolicyController.models_storage_is_local,
            probe_sequence=PluginHealthActionProbeController.probe_sequence,
            invoke_action=invoke_action,
            unpack_action_result=PluginHealthActionProbeController.unpack_action_result,
            is_success_status=lambda value: str(value).lower() in {"success", "ok"},
            extract_installed_models=lambda data: ["installed-model"],
            extract_models=lambda data: ["installed-model"],
            issue_from_action_failure=lambda action_id, message, data, model_id: {
                "action_id": action_id,
                "message": message,
                "data": data,
                "model_id": model_id,
            },
            issue_from_action_warnings=lambda **kwargs: None,
        )

        self.assertEqual(issues, [])
        self.assertEqual(checks, ["action:list_models", "action:test_model"])
        self.assertEqual([item[1] for item in calls], ["list_models", "test_model"])

    def test_returns_issue_when_no_installed_models_are_available(self) -> None:
        checks, issues = PluginHealthActionCheckController.run_action_checks(
            plugin_id="llm.demo",
            settings={"timeout_seconds": 30},
            stage_params={},
            full_check=True,
            action_ids={"list_models"},
            plugin_capabilities={"models": {"storage": "local"}},
            coerce_bool=lambda value: bool(value),
            cap_get=lambda payload, *keys, default=None: default,
            resolve_model_id=PluginHealthModelPolicyController.resolve_model_id,
            settings_override_for_actions=PluginHealthActionProbeController.settings_override_for_actions,
            preflight_settings_override=PluginHealthModelPolicyController.preflight_settings_override,
            models_storage_is_local=PluginHealthModelPolicyController.models_storage_is_local,
            probe_sequence=PluginHealthActionProbeController.probe_sequence,
            invoke_action=lambda plugin_id, action_id, payload, settings_override: {
                "status": "success",
                "message": "models_loaded",
                "data": {"models": []},
            },
            unpack_action_result=PluginHealthActionProbeController.unpack_action_result,
            is_success_status=lambda value: str(value).lower() in {"success", "ok"},
            extract_installed_models=lambda data: [],
            extract_models=lambda data: [],
            issue_from_action_failure=lambda action_id, message, data, model_id: {
                "action_id": action_id,
                "message": message,
                "data": data,
                "model_id": model_id,
            },
            issue_from_action_warnings=lambda **kwargs: None,
        )

        self.assertEqual(checks, ["action:list_models"])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["message"], "model_not_found")

    def test_preflight_uses_quick_timeout_override(self) -> None:
        call_overrides: list[dict | None] = []

        checks, issues = PluginHealthActionCheckController.run_action_checks(
            plugin_id="llm.demo",
            settings={"timeout_seconds": 30},
            stage_params={},
            full_check=False,
            action_ids={"test_connection"},
            plugin_capabilities={},
            coerce_bool=lambda value: bool(value),
            cap_get=lambda payload, *keys, default=None: default,
            resolve_model_id=PluginHealthModelPolicyController.resolve_model_id,
            settings_override_for_actions=PluginHealthActionProbeController.settings_override_for_actions,
            preflight_settings_override=PluginHealthModelPolicyController.preflight_settings_override,
            models_storage_is_local=PluginHealthModelPolicyController.models_storage_is_local,
            probe_sequence=PluginHealthActionProbeController.probe_sequence,
            invoke_action=lambda plugin_id, action_id, payload, settings_override: (
                call_overrides.append(dict(settings_override or {})) or {"status": "success", "message": "ok"}
            ),
            unpack_action_result=PluginHealthActionProbeController.unpack_action_result,
            is_success_status=lambda value: str(value).lower() in {"success", "ok"},
            extract_installed_models=lambda data: [],
            extract_models=lambda data: [],
            issue_from_action_failure=lambda action_id, message, data, model_id: {
                "action_id": action_id,
                "message": message,
                "data": data,
                "model_id": model_id,
            },
            issue_from_action_warnings=lambda **kwargs: None,
        )

        self.assertEqual(issues, [])
        self.assertEqual(checks, ["action:test_connection"])
        self.assertTrue(call_overrides)
        self.assertEqual(call_overrides[-1]["timeout_seconds"], 8)
