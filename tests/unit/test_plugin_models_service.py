import json
import shutil
import sys
import time
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.plugin_models_service import PluginModelsService  # noqa: E402


class TestPluginModelsService(unittest.TestCase):
    def _workspace_root(self, name: str) -> Path:
        root = repo_root / "logs" / "_test_tmp" / name
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_load_models_config_migrates_legacy_enabled_rows(self) -> None:
        app_root = self._workspace_root("plugin_models_service_load")
        settings_dir = app_root / "config" / "settings" / "plugins"
        settings_dir.mkdir(parents=True, exist_ok=True)
        plugin_path = settings_dir / "llm.remote.json"
        plugin_path.write_text(
            json.dumps(
                {
                    "models": [
                        {"model_id": "m1", "enabled": True, "status": "ready"},
                        {"model_id": "m2", "enabled": False, "status": "request_failed"},
                    ]
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )

        service = PluginModelsService(app_root)

        rows = service.load_models_config("llm.remote")

        self.assertEqual(rows[0]["favorite"], True)
        self.assertEqual(rows[0]["availability_status"], "ready")
        self.assertEqual(rows[1]["favorite"], False)
        self.assertEqual(rows[1]["availability_status"], "unavailable")

        persisted = json.loads(plugin_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["models"][0]["favorite"], True)
        self.assertEqual(persisted["models"][1]["availability_status"], "unavailable")

    def test_update_model_enabled_writes_enabled_and_availability_without_new_favorite(self) -> None:
        app_root = self._workspace_root("plugin_models_service_update")
        service = PluginModelsService(app_root)

        service.update_model_enabled("llm.remote", "m1", True)

        plugin_path = app_root / "config" / "settings" / "plugins" / "llm.remote.json"
        payload = json.loads(plugin_path.read_text(encoding="utf-8"))
        row = payload["models"][0]
        self.assertEqual(row["model_id"], "m1")
        self.assertEqual(row["enabled"], True)
        self.assertEqual(row["availability_status"], "unknown")
        self.assertNotIn("favorite", row)

    def test_update_model_favorite_delegates_to_enabled_update_for_compatibility(self) -> None:
        app_root = self._workspace_root("plugin_models_service_favorite")
        service = PluginModelsService(app_root)

        service.update_model_favorite("llm.remote", "m1", False)

        plugin_path = app_root / "config" / "settings" / "plugins" / "llm.remote.json"
        payload = json.loads(plugin_path.read_text(encoding="utf-8"))
        row = payload["models"][0]
        self.assertEqual(row["model_id"], "m1")
        self.assertEqual(row["enabled"], False)
        self.assertNotIn("favorite", row)

    def test_update_model_runtime_status_persists_pipeline_outcome(self) -> None:
        app_root = self._workspace_root("plugin_models_service_runtime_status")
        settings_dir = app_root / "config" / "settings" / "plugins"
        settings_dir.mkdir(parents=True, exist_ok=True)
        plugin_path = settings_dir / "llm.remote.json"
        plugin_path.write_text(
            json.dumps(
                {
                    "models": [
                        {"model_id": "m1", "favorite": True, "enabled": True, "availability_status": "unknown"}
                    ]
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        service = PluginModelsService(app_root)

        service.update_model_runtime_status(
            "llm.remote",
            "m1",
            availability_status="limited",
            failure_code="rate_limited",
            summary_quality="failed",
        )

        payload = json.loads(plugin_path.read_text(encoding="utf-8"))
        row = payload["models"][0]
        self.assertEqual(row["availability_status"], "limited")
        self.assertEqual(row["failure_code"], "rate_limited")
        self.assertEqual(row["last_pipeline_quality"], "failed")
        self.assertEqual(row["favorite"], True)
        self.assertEqual(row["enabled"], True)

    def test_update_model_runtime_status_rate_limited_sets_cooldown_and_disables_selection(self) -> None:
        app_root = self._workspace_root("plugin_models_service_rate_limited")
        service = PluginModelsService(app_root)

        service.update_model_runtime_status(
            "llm.remote",
            "m1",
            availability_status="limited",
            failure_code="rate_limited",
            summary_quality="failed",
        )

        plugin_path = app_root / "config" / "settings" / "plugins" / "llm.remote.json"
        payload = json.loads(plugin_path.read_text(encoding="utf-8"))
        row = payload["models"][0]
        self.assertEqual(row["availability_status"], "limited")
        self.assertEqual(row["selectable"], False)
        self.assertGreater(int(row["cooldown_until"]), int(time.time()))
        self.assertEqual(row["pipeline_failure_streak"], 1)

    def test_update_model_runtime_status_provider_blocked_marks_account_block(self) -> None:
        app_root = self._workspace_root("plugin_models_service_provider_blocked")
        service = PluginModelsService(app_root)

        service.update_model_runtime_status(
            "llm.remote",
            "m1",
            availability_status="unavailable",
            failure_code="provider_blocked",
            summary_quality="failed",
        )

        plugin_path = app_root / "config" / "settings" / "plugins" / "llm.remote.json"
        payload = json.loads(plugin_path.read_text(encoding="utf-8"))
        row = payload["models"][0]
        self.assertEqual(row["availability_status"], "unavailable")
        self.assertEqual(row["blocked_for_account"], True)
        self.assertEqual(row["selectable"], False)

    def test_update_model_runtime_status_ready_resets_failure_policy_fields(self) -> None:
        app_root = self._workspace_root("plugin_models_service_ready_reset")
        settings_dir = app_root / "config" / "settings" / "plugins"
        settings_dir.mkdir(parents=True, exist_ok=True)
        plugin_path = settings_dir / "llm.remote.json"
        plugin_path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "model_id": "m1",
                            "favorite": True,
                            "enabled": True,
                            "availability_status": "limited",
                            "failure_code": "rate_limited",
                            "selectable": False,
                            "cooldown_until": int(time.time()) + 300,
                            "pipeline_failure_streak": 2,
                            "blocked_for_account": True,
                        }
                    ]
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        service = PluginModelsService(app_root)

        service.update_model_runtime_status(
            "llm.remote",
            "m1",
            availability_status="ready",
            failure_code="",
            summary_quality="usable",
        )

        payload = json.loads(plugin_path.read_text(encoding="utf-8"))
        row = payload["models"][0]
        self.assertEqual(row["availability_status"], "ready")
        self.assertEqual(row["pipeline_failure_streak"], 0)
        self.assertEqual(row["blocked_for_account"], False)
        self.assertEqual(row["cooldown_until"], 0)
        self.assertEqual(row["selectable"], True)


if __name__ == "__main__":
    unittest.main()
