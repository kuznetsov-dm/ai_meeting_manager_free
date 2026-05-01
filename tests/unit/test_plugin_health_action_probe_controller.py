import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_health_action_probe_controller import (  # noqa: E402
    PluginHealthActionProbeController,
)


class TestPluginHealthActionProbeController(unittest.TestCase):
    def test_settings_override_for_full_check_keeps_stage_model_path_and_selected_model(self) -> None:
        override = PluginHealthActionProbeController.settings_override_for_actions(
            settings={"timeout_seconds": 30, "model_id": "saved-model"},
            stage_model_path="models/llama/tiny.gguf",
            stage_model_id="",
            model_id="",
            full_check=True,
            preflight_settings_override=lambda payload: {"should_not": "happen", **payload},
        )

        self.assertIsInstance(override, dict)
        self.assertEqual(str(override.get("model_path", "")), "models/llama/tiny.gguf")
        self.assertEqual(str(override.get("model_id", "")), "")
        self.assertEqual(int(override.get("timeout_seconds", 0)), 30)

    def test_settings_override_for_quick_check_prefers_preflight_override(self) -> None:
        override = PluginHealthActionProbeController.settings_override_for_actions(
            settings={"timeout_seconds": 30, "api_key": "x"},
            stage_model_path="",
            stage_model_id="glm-4.5-air",
            model_id="glm-4-flash",
            full_check=False,
            preflight_settings_override=lambda payload: {**payload, "timeout_seconds": 8},
        )

        self.assertEqual(int(override.get("timeout_seconds", 0)), 8)
        self.assertEqual(str(override.get("model_id", "")), "glm-4.5-air")

    def test_probe_sequence_prefers_test_model_on_full_check(self) -> None:
        probes = PluginHealthActionProbeController.probe_sequence(
            action_ids={"test_model", "test_connection", "health_check"},
            full_check=True,
            model_id="m1",
            ran_list_models=False,
        )

        self.assertEqual(probes, [("test_model", {"model_id": "m1"})])

    def test_probe_sequence_falls_back_to_connection_or_list_models(self) -> None:
        connection_probes = PluginHealthActionProbeController.probe_sequence(
            action_ids={"test_connection", "list_models"},
            full_check=False,
            model_id="",
            ran_list_models=False,
        )
        list_only_probes = PluginHealthActionProbeController.probe_sequence(
            action_ids={"list_models"},
            full_check=True,
            model_id="",
            ran_list_models=False,
        )

        self.assertEqual(connection_probes, [("test_connection", {})])
        self.assertEqual(list_only_probes, [("list_models", {})])

    def test_unpack_action_result_merges_top_level_and_nested_warnings(self) -> None:
        status, message, data, warnings = PluginHealthActionProbeController.unpack_action_result(
            {
                "status": "success",
                "message": "ok",
                "warnings": ["timeout"],
                "data": {"warnings": ["mock_fallback"], "value": 1},
            }
        )

        self.assertEqual(status, "success")
        self.assertEqual(message, "ok")
        self.assertEqual(data["value"], 1)
        self.assertEqual(warnings, ["timeout", "mock_fallback"])

    def test_unpack_action_result_supports_action_result_like_objects(self) -> None:
        result = SimpleNamespace(
            status="error",
            message="connection_failed",
            data={"warnings": ["server_not_running"]},
            warnings=["socket_timeout"],
        )

        status, message, data, warnings = PluginHealthActionProbeController.unpack_action_result(result)

        self.assertEqual(status, "error")
        self.assertEqual(message, "connection_failed")
        self.assertEqual(data["warnings"], ["server_not_running"])
        self.assertEqual(warnings, ["socket_timeout", "server_not_running"])


if __name__ == "__main__":
    unittest.main()
