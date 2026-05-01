import json
import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.contracts import KIND_SUMMARY, HookContext  # noqa: E402
from aimn.core.plugin_catalog import create_default_catalog  # noqa: E402
from aimn.core.plugin_health_service import PluginHealthService  # noqa: E402
from aimn.core.plugin_manager import PluginManager  # noqa: E402
from aimn.core.plugins_config import PluginsConfig  # noqa: E402


def _live_enabled() -> bool:
    return str(os.getenv("AIMN_LIVE_TESTS", "")).strip().lower() in {"1", "true", "yes", "on"}


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _looks_secret(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if not lowered:
        return False
    if lowered in {"api_key", "key", "token", "secret", "password"}:
        return True
    return lowered.endswith("_key") or lowered.endswith("_token") or lowered.endswith("_secret")


def _pick_model_id(settings: dict, list_models_payload: dict | None = None) -> str:
    rows = settings.get("models")
    direct = str(settings.get("model_id", "") or "").strip()
    if direct and isinstance(rows, list):
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if model_id != direct:
                continue
            if entry.get("installed") is False:
                direct = ""
            break
    if direct:
        return direct
    if isinstance(rows, list):
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            if entry.get("enabled") is not True:
                continue
            if entry.get("installed") is False:
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if model_id:
                return model_id
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            if entry.get("installed") is False:
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if model_id:
                return model_id
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            if entry.get("enabled") is not True:
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if model_id:
                return model_id
    payload_rows = []
    if isinstance(list_models_payload, dict):
        raw = list_models_payload.get("models")
        if isinstance(raw, list):
            payload_rows = raw
    for entry in payload_rows:
        if not isinstance(entry, dict):
            continue
        if entry.get("installed") is False:
            continue
        model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if model_id:
            return model_id
    return ""


class _StaticCatalogService:
    def __init__(self, app_root: Path, config: PluginsConfig) -> None:
        self._snapshot = SimpleNamespace(
            stamp="live-static",
            catalog=create_default_catalog(app_root, config=config),
            config=config,
        )

    def load(self):
        return self._snapshot


class _ManagerActionService:
    def __init__(self, manager: PluginManager) -> None:
        self._manager = manager

    def list_actions(self, plugin_id: str):
        return list(self._manager.actions_for(plugin_id))

    def invoke_action(
        self,
        plugin_id: str,
        action: str,
        payload: dict,
        *,
        settings_override: dict | None = None,
    ):
        return self._manager.invoke_action(
            plugin_id,
            action,
            payload,
            settings_override=settings_override,
        )


class TestPluginHealthRuntimeLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not _live_enabled():
            raise unittest.SkipTest("Set AIMN_LIVE_TESTS=1 to run live plugin health/runtime tests.")
        raw_plugins = str(
            os.getenv(
                "AIMN_LIVE_HEALTH_PLUGINS",
                "llm.ollama,llm.zai,llm.openrouter,llm.deepseek,llm.llama_cli",
            )
        )
        cls.plugin_ids = [item.strip() for item in raw_plugins.split(",") if item.strip()]
        if not cls.plugin_ids:
            raise unittest.SkipTest("AIMN_LIVE_HEALTH_PLUGINS is empty.")
        selected_config = PluginsConfig({"enabled": cls.plugin_ids})
        cls.catalog_service = _StaticCatalogService(repo_root, selected_config)
        snapshot = cls.catalog_service.load()
        filtered: list[str] = []
        for plugin_id in cls.plugin_ids:
            plugin = snapshot.catalog.plugin_by_id(plugin_id)
            if not plugin:
                continue
            if not bool(getattr(plugin, "installed", False)):
                continue
            if not bool(getattr(plugin, "enabled", False)):
                continue
            filtered.append(plugin_id)
        cls.plugin_ids = filtered
        if not cls.plugin_ids:
            raise unittest.SkipTest("None of AIMN_LIVE_HEALTH_PLUGINS are enabled in plugins registry.")
        selected_config = PluginsConfig({"enabled": cls.plugin_ids})
        cls.catalog_service = _StaticCatalogService(repo_root, selected_config)
        cls.manager = PluginManager(repo_root, selected_config)
        cls.manager.load()
        cls.health = PluginHealthService(
            repo_root,
            catalog_service=cls.catalog_service,
            action_service=_ManagerActionService(cls.manager),
        )
        logs_dir = repo_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        cls.log_path = logs_dir / f"plugin_health_runtime_live_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        cls._append_log("suite_start", {"plugins": cls.plugin_ids})

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "manager", None):
            cls.manager.shutdown()
        cls._append_log("suite_end", {})

    @classmethod
    def _append_log(cls, event: str, payload: dict) -> None:
        record = {"ts": _timestamp(), "event": event, "payload": payload}
        with cls.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    def test_health_matches_runtime_smoke(self) -> None:
        sample_text = (
            "Meeting notes: finalized sprint scope, assigned owner for release checklist, "
            "and agreed to deliver demo by Friday."
        )
        for plugin_id in self.plugin_ids:
            with self.subTest(plugin_id=plugin_id):
                manifest = self.manager.manifest_for(plugin_id)
                if not manifest:
                    self._append_log("plugin_missing", {"plugin_id": plugin_id})
                    continue

                settings = self.manager.get_settings(plugin_id, include_secrets=True)
                safe_settings = {
                    key: ("***" if _looks_secret(key) else value) for key, value in dict(settings or {}).items()
                }
                self._append_log(
                    "plugin_settings",
                    {
                        "plugin_id": plugin_id,
                        "keys": sorted(safe_settings.keys()),
                    },
                )

                stage_params = {}
                model_id_hint = _pick_model_id(settings)
                if model_id_hint:
                    stage_params["model_id"] = model_id_hint
                runtime_settings = {**dict(settings or {}), **dict(stage_params)}
                report = self.health.check_plugin(
                    plugin_id,
                    stage_id="llm_processing",
                    stage_params=stage_params,
                    full_check=True,
                    force=True,
                    max_age_seconds=0.0,
                    allow_disabled=True,
                    allow_stale_on_error=False,
                )
                self._append_log(
                    "health_report",
                    {
                        "plugin_id": plugin_id,
                        "healthy": report.healthy,
                        "checks": list(report.checks),
                        "issues": [
                            {
                                "code": issue.code,
                                "severity": issue.severity,
                                "summary": issue.summary,
                                "detail": issue.detail,
                            }
                            for issue in report.issues
                        ],
                    },
                )
                self.assertTrue(
                    report.healthy,
                    f"{plugin_id}: health check is not healthy; see {self.log_path}",
                )

                actions = {str(item.action_id) for item in self.manager.actions_for(plugin_id)}
                action_result = None
                list_models_payload = None
                if "list_models" in actions:
                    action_result = self.manager.invoke_action(
                        plugin_id, "list_models", {}, settings_override=runtime_settings
                    )
                    if isinstance(action_result.data, dict):
                        list_models_payload = dict(action_result.data)
                    self._append_log(
                        "action_result",
                        {
                            "plugin_id": plugin_id,
                            "action": "list_models",
                            "status": action_result.status,
                            "message": action_result.message,
                        },
                    )
                    self.assertEqual(
                        action_result.status,
                        "success",
                        f"{plugin_id}: list_models failed ({action_result.message}); see {self.log_path}",
                    )

                if "test_model" in actions:
                    model_id = _pick_model_id(settings, list_models_payload=list_models_payload)
                    self.assertTrue(
                        model_id,
                        f"{plugin_id}: cannot resolve model_id for test_model; see {self.log_path}",
                    )
                    action_result = self.manager.invoke_action(
                        plugin_id,
                        "test_model",
                        {"model_id": model_id},
                        settings_override={**dict(runtime_settings or {}), "model_id": model_id},
                    )
                    self._append_log(
                        "action_result",
                        {
                            "plugin_id": plugin_id,
                            "action": "test_model",
                            "model_id": model_id,
                            "status": action_result.status,
                            "message": action_result.message,
                        },
                    )
                    self.assertEqual(
                        action_result.status,
                        "success",
                        f"{plugin_id}: test_model failed ({action_result.message}); see {self.log_path}",
                    )
                elif "test_connection" in actions:
                    action_result = self.manager.invoke_action(
                        plugin_id, "test_connection", {}, settings_override=runtime_settings
                    )
                    self._append_log(
                        "action_result",
                        {
                            "plugin_id": plugin_id,
                            "action": "test_connection",
                            "status": action_result.status,
                            "message": action_result.message,
                        },
                    )
                    self.assertEqual(
                        action_result.status,
                        "success",
                        f"{plugin_id}: test_connection failed ({action_result.message}); see {self.log_path}",
                    )

                hook_names = {spec.name for spec in list(getattr(manifest, "hooks", []))}
                if "derive.after_postprocess" not in hook_names:
                    self._append_log("runtime_skipped", {"plugin_id": plugin_id, "reason": "hook_not_available"})
                    continue

                output_dir = repo_root / "output"
                output_dir.mkdir(parents=True, exist_ok=True)
                ctx = HookContext(
                    plugin_id=plugin_id,
                    meeting_id="live-health-smoke",
                    alias="live-health-smoke",
                    input_text=sample_text,
                    force_run=True,
                    plugin_config=dict(runtime_settings or {}),
                    _output_dir=str(output_dir),
                    _storage_dir=str(self.manager.get_storage_path(plugin_id)),
                    _schema_resolver=self.manager.artifact_schema,
                    _get_secret=lambda key, _pid=plugin_id: self.manager.get_secret(_pid, key),
                    _resolve_service=self.manager.get_service,
                )
                executions = self.manager.execute_connector(
                    "derive.after_postprocess", ctx, allowed_plugin_ids=[plugin_id]
                )
                self.assertTrue(executions, f"{plugin_id}: no runtime execution for derive.after_postprocess")
                execution = executions[0]
                self._append_log(
                    "runtime_execution",
                    {
                        "plugin_id": plugin_id,
                        "error": execution.error,
                        "has_result": execution.result is not None,
                        "warnings": list(getattr(execution.result, "warnings", []) or []),
                    },
                )
                self.assertIsNone(execution.error, f"{plugin_id}: runtime error ({execution.error})")
                self.assertIsNotNone(execution.result, f"{plugin_id}: runtime returned no result")

                warnings = [str(item).strip() for item in list(execution.result.warnings or []) if str(item).strip()]
                self.assertFalse(
                    any(item in {"mock_fallback", "mock_output"} for item in warnings),
                    f"{plugin_id}: runtime returned mock fallback warnings={warnings}",
                )
                summary = next((out for out in execution.result.outputs if out.kind == KIND_SUMMARY), None)
                self.assertIsNotNone(summary, f"{plugin_id}: runtime did not return summary artifact")
                self.assertTrue(
                    str(summary.content or "").strip(),
                    f"{plugin_id}: runtime summary content is empty",
                )


if __name__ == "__main__":
    unittest.main()
