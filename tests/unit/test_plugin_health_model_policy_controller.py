import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_health_model_policy_controller import (  # noqa: E402
    PluginHealthModelPolicyController,
)


class TestPluginHealthModelPolicyController(unittest.TestCase):
    def test_models_storage_is_local(self) -> None:
        self.assertTrue(
            PluginHealthModelPolicyController.models_storage_is_local({"models": {"storage": "local"}})
        )
        self.assertFalse(
            PluginHealthModelPolicyController.models_storage_is_local({"models": {"storage": "cloud"}})
        )
        self.assertFalse(PluginHealthModelPolicyController.models_storage_is_local(None))

    def test_resolve_model_id_prefers_stage_params_then_enabled_rows(self) -> None:
        resolved_from_stage = PluginHealthModelPolicyController.resolve_model_id(
            {"model": "stage-model"},
            {"model_id": "saved-model"},
        )
        resolved_from_rows = PluginHealthModelPolicyController.resolve_model_id(
            {},
            {
                "models": [
                    {"model_id": "m-disabled", "enabled": False},
                    {"id": "m-enabled", "enabled": True},
                ]
            },
        )

        self.assertEqual(resolved_from_stage, "stage-model")
        self.assertEqual(resolved_from_rows, "m-enabled")

    def test_preflight_settings_override_clamps_timeout(self) -> None:
        override = PluginHealthModelPolicyController.preflight_settings_override(
            {"timeout_seconds": 30, "model_id": "m1"}
        )
        fallback = PluginHealthModelPolicyController.preflight_settings_override(
            {"timeout_seconds": "bad"}
        )
        absent = PluginHealthModelPolicyController.preflight_settings_override({})

        self.assertEqual(int(override.get("timeout_seconds", 0)), 8)
        self.assertEqual(int(fallback.get("timeout_seconds", 0)), 8)
        self.assertIsNone(absent)


if __name__ == "__main__":
    unittest.main()
