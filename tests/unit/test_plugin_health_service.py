import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.contracts import (  # noqa: E402
    ActionDescriptor,
    ActionResult,
    PluginDescriptor,
    PluginSetting,
    PluginUiSchema,
)
from aimn.core.plugin_health_service import PluginHealthQuickFix, PluginHealthService  # noqa: E402


class _FakeCatalog:
    def __init__(self, plugins: dict[str, PluginDescriptor], schemas: dict[str, PluginUiSchema]) -> None:
        self._plugins = plugins
        self._schemas = schemas

    def plugin_by_id(self, plugin_id: str):
        return self._plugins.get(str(plugin_id))

    def schema_for(self, plugin_id: str):
        return self._schemas.get(str(plugin_id))


class _FakeCatalogService:
    def __init__(self, plugins: dict[str, PluginDescriptor], schemas: dict[str, PluginUiSchema]) -> None:
        self._snapshot = SimpleNamespace(
            stamp="stamp-1",
            catalog=_FakeCatalog(plugins=plugins, schemas=schemas),
        )

    def load(self):
        return self._snapshot


class _BrokenCatalogService:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def load(self):
        raise self._exc


class _FakeSettingsService:
    def __init__(self, settings: dict[str, dict]) -> None:
        self._settings = settings

    def get_settings(self, plugin_id: str, *, include_secrets: bool = True) -> dict:
        payload = self._settings.get(str(plugin_id), {})
        return dict(payload) if isinstance(payload, dict) else {}


class _FakeActionService:
    def __init__(
        self,
        action_ids: dict[str, list[str]],
        results: dict[tuple[str, str], ActionResult],
    ) -> None:
        self._action_ids = action_ids
        self._results = results
        self.calls: list[tuple[str, str]] = []
        self.call_details: list[tuple[str, str, dict | None]] = []

    def list_actions(self, plugin_id: str):
        items = []
        for action_id in self._action_ids.get(str(plugin_id), []):
            items.append(ActionDescriptor(action_id=action_id, label=action_id))
        return items

    def invoke_action(
        self,
        plugin_id: str,
        action: str,
        payload: dict,
        *,
        settings_override: dict | None = None,
    ):
        copied_override = dict(settings_override) if isinstance(settings_override, dict) else None
        key = (str(plugin_id), str(action))
        self.calls.append(key)
        self.call_details.append((key[0], key[1], copied_override))
        return self._results.get(key, ActionResult(status="error", message="action_not_found"))


class _BrokenActionService(_FakeActionService):
    def __init__(self, exc: Exception) -> None:
        super().__init__(action_ids={}, results={})
        self._exc = exc

    def list_actions(self, plugin_id: str):
        raise self._exc

    def invoke_action(
        self,
        plugin_id: str,
        action: str,
        payload: dict,
        *,
        settings_override: dict | None = None,
    ):
        raise self._exc


class _InvokeBrokenActionService(_FakeActionService):
    def __init__(self, exc: Exception, *, action_ids: dict[str, list[str]]) -> None:
        super().__init__(action_ids=action_ids, results={})
        self._exc = exc

    def invoke_action(
        self,
        plugin_id: str,
        action: str,
        payload: dict,
        *,
        settings_override: dict | None = None,
    ):
        raise self._exc


class TestPluginHealthService(unittest.TestCase):
    def setUp(self) -> None:
        PluginHealthService._cache.clear()

    def test_plugin_capabilities_tolerate_catalog_value_error(self) -> None:
        service = PluginHealthService(
            repo_root,
            catalog_service=_BrokenCatalogService(ValueError("bad registry")),
            action_service=_FakeActionService(action_ids={}, results={}),
            settings_service=_FakeSettingsService({}),
        )

        self.assertEqual(service._plugin_capabilities("llm.demo"), {})
        self.assertEqual(service._provider_label("llm.demo"), "")

    def test_settings_with_defaults_tolerate_catalog_runtime_error(self) -> None:
        service = PluginHealthService(
            repo_root,
            catalog_service=_BrokenCatalogService(RuntimeError("schema unavailable")),
            action_service=_FakeActionService(action_ids={}, results={}),
            settings_service=_FakeSettingsService({}),
        )

        payload = service._settings_with_defaults("llm.demo", {"timeout_seconds": 30})

        self.assertEqual(payload, {"timeout_seconds": 30})

    def test_available_action_ids_tolerate_action_service_value_error(self) -> None:
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService({}, {}),
            action_service=_BrokenActionService(ValueError("bad actions registry")),
            settings_service=_FakeSettingsService({}),
        )

        self.assertEqual(service._available_action_ids("llm.demo"), set())

    def test_check_plugin_converts_runtime_error_into_issue(self) -> None:
        plugin_id = "llm.zai"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Z.ai",
                module="plugins.llm.zai",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=_InvokeBrokenActionService(
                RuntimeError("probe exploded"),
                action_ids={plugin_id: ["test_connection"]},
            ),
            settings_service=_FakeSettingsService({plugin_id: {"api_key": "x"}}),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertTrue(any(issue.code == "health_action_test_connection_failed" for issue in report.issues))

    def test_reports_api_key_issue_from_action(self) -> None:
        plugin_id = "llm.zai"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Z.ai",
                module="plugins.llm.zai",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection"]},
            results={(plugin_id, "test_connection"): ActionResult(status="error", message="zai_api_key_missing")},
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {}}),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=60.0)

        self.assertFalse(report.healthy)
        self.assertTrue(report.issues)
        self.assertIn("api key", report.issues[0].hint.lower())

    def test_settings_override_satisfies_required_secret_check(self) -> None:
        plugin_id = "llm.reference_openai"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="OpenAI Reference",
                module="plugins.reference.openai_summary",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        schema = PluginUiSchema(
            plugin_id=plugin_id,
            stage_id="llm_processing",
            settings=[PluginSetting(key="api_key", label="API key", value="")],
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {plugin_id: schema}),
            action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
            settings_service=_FakeSettingsService({plugin_id: {}}),
        )

        report = service.check_plugin(
            plugin_id,
            settings_override={"api_key": "live-token"},
            full_check=False,
            force=True,
            max_age_seconds=60.0,
        )

        self.assertTrue(report.healthy)
        self.assertFalse(any("required setting" in issue.summary.lower() for issue in report.issues))

    def test_explicit_empty_required_settings_disables_secret_fallback(self) -> None:
        plugin_id = "llm.llama_cli"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Llama.cpp",
                module="plugins.llm.llama_cli.llama_cli",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={"health": {"required_settings": []}},
            )
        }
        schema = PluginUiSchema(
            plugin_id=plugin_id,
            stage_id="llm_processing",
            settings=[PluginSetting(key="hf_token", label="Hugging Face Token", value="")],
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {plugin_id: schema}),
            action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
            settings_service=_FakeSettingsService({plugin_id: {}}),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=60.0)

        self.assertTrue(report.healthy)
        self.assertFalse(any(issue.code == "secret" for issue in report.issues))

    def test_uses_cache_for_repeat_preflight(self) -> None:
        plugin_id = "llm.zai"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Z.ai",
                module="plugins.llm.zai",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection"]},
            results={(plugin_id, "test_connection"): ActionResult(status="success", message="connection_ok")},
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {"api_key": "x"}}),
        )

        first = service.check_plugin(plugin_id, full_check=False, force=False, max_age_seconds=300.0)
        second = service.check_plugin(plugin_id, full_check=False, force=False, max_age_seconds=300.0)

        self.assertTrue(first.healthy)
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(action_service.calls.count((plugin_id, "test_connection")), 1)

    def test_quick_fix_is_exposed_for_ollama_connection_issue(self) -> None:
        plugin_id = "llm.ollama"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Ollama",
                module="plugins.llm.ollama",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={"health": {"server": {"auto_start_action": "start_server"}}},
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection", "start_server"]},
            results={
                (plugin_id, "test_connection"): ActionResult(status="error", message="connection_failed"),
                (plugin_id, "start_server"): ActionResult(status="success", message="server_started"),
            },
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {}}),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)
        self.assertFalse(report.healthy)
        fix = next((issue.quick_fix for issue in report.issues if issue.quick_fix), None)
        self.assertIsInstance(fix, PluginHealthQuickFix)
        self.assertEqual(fix.payload.get("timeout_seconds"), 12)
        ok, message = service.invoke_quick_fix(plugin_id, fix)
        self.assertTrue(ok)
        self.assertIn("server_started", message)

    def test_quick_fix_runtime_error_returns_failure_tuple(self) -> None:
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService({}, {}),
            action_service=_BrokenActionService(RuntimeError("quick fix exploded")),
            settings_service=_FakeSettingsService({}),
        )

        ok, message = service.invoke_quick_fix(
            "llm.demo",
            PluginHealthQuickFix(action_id="repair", label="Repair"),
        )

        self.assertFalse(ok)
        self.assertEqual(message, "quick fix exploded")

    def test_uses_enabled_model_for_preflight_action_checks(self) -> None:
        plugin_id = "llm.openrouter"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="OpenRouter",
                module="plugins.llm.openrouter",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection"]},
            results={(plugin_id, "test_connection"): ActionResult(status="success", message="connection_ok")},
        )
        settings = {
            plugin_id: {
                "api_key": "x",
                "timeout_seconds": 30,
                "models": [
                    {"model_id": "m-disabled", "enabled": False},
                    {"model_id": "m-enabled", "enabled": True},
                ]
            }
        }
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService(settings),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertTrue(report.healthy)
        self.assertTrue(action_service.call_details)
        _pid, _action, settings_override = action_service.call_details[-1]
        self.assertIsInstance(settings_override, dict)
        self.assertEqual(str(settings_override.get("model_id", "")), "m-enabled")

    def test_llama_default_paths_and_local_model_pass_without_credentials(self) -> None:
        plugin_id = "llm.llama_cli"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Llama CLI",
                module="plugins.llm.llama_cli",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={
                    "health": {
                        "local_model_cache": {
                            "cache_dir_key": "cache_dir",
                            "cache_dir_default": "models/llama",
                            "model_path_key": "model_path",
                            "model_id_key": "model_id",
                            "allow_download_key": "allow_download",
                            "file_globs": ["*.gguf"],
                            "model_label": "GGUF model",
                            "missing_code": "llama_model_missing",
                            "path_missing_code": "llama_model_path_missing",
                            "not_cached_code": "llama_model_not_cached",
                        }
                    },
                    "runtime": {
                        "local_binary": {
                            "setting_key": "binary_path",
                            "fallback": "bin/llama/llama-cli",
                            "label": "Llama CLI binary",
                        }
                    },
                },
            )
        }
        schema = PluginUiSchema(
            plugin_id=plugin_id,
            stage_id="llm_processing",
            settings=[
                PluginSetting(key="binary_path", label="Binary Path", value="bin/llama/llama-cli"),
                PluginSetting(key="cache_dir", label="Cache Dir", value="models/llama"),
                PluginSetting(key="max_tokens", label="Max Tokens", value="900"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            bin_dir = app_root / "bin" / "llama"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "llama-cli.exe").write_text("stub", encoding="utf-8")
            model_dir = app_root / "models" / "llama"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "tinyllama.gguf").write_text("stub", encoding="utf-8")

            service = PluginHealthService(
                app_root,
                catalog_service=_FakeCatalogService(plugins, {plugin_id: schema}),
                action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
                settings_service=_FakeSettingsService({plugin_id: {}}),
            )
            report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertTrue(report.healthy)
        self.assertFalse(any("required setting" in issue.summary.lower() for issue in report.issues))

    def test_generic_local_model_cache_capability_reports_not_cached(self) -> None:
        plugin_id = "llm.local_generic"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Local Generic",
                module="plugins.llm.local_generic",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={
                    "health": {
                        "local_model_cache": {
                            "cache_dir_key": "cache_dir",
                            "cache_dir_default": "models/local_generic",
                            "model_id_key": "model_id",
                            "allow_download_key": "allow_download",
                            "file_globs": ["*.gguf"],
                            "not_cached_code": "generic_model_not_cached",
                        }
                    }
                },
            )
        }
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            (app_root / "models" / "local_generic").mkdir(parents=True, exist_ok=True)
            service = PluginHealthService(
                app_root,
                catalog_service=_FakeCatalogService(plugins, {}),
                action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
                settings_service=_FakeSettingsService(
                    {plugin_id: {"model_id": "demo-model", "allow_download": False}}
                ),
            )
            report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertTrue(any(issue.code == "generic_model_not_cached" for issue in report.issues))

    def test_local_binary_capability_reports_missing_binary(self) -> None:
        plugin_id = "service.local_tool"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="service",
                name="Local Tool",
                module="plugins.service.local_tool",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={
                    "runtime": {
                        "local_binary": {
                            "setting_key": "binary_path",
                            "label": "Service binary",
                            "executable": False,
                        }
                    }
                },
            )
        }
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
            settings_service=_FakeSettingsService({plugin_id: {"binary_path": "missing/tool.bin"}}),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertIn("local_prerequisites", report.checks)
        self.assertTrue(any(issue.code == "local_binary_missing" for issue in report.issues))

    def test_local_binary_capability_passes_when_binary_exists(self) -> None:
        plugin_id = "service.local_tool"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="service",
                name="Local Tool",
                module="plugins.service.local_tool",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={
                    "runtime": {
                        "local_binary": {
                            "setting_key": "binary_path",
                            "label": "Service binary",
                            "executable": False,
                        }
                    }
                },
            )
        }
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            bin_dir = app_root / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "tool.bin").write_text("stub", encoding="utf-8")
            service = PluginHealthService(
                app_root,
                catalog_service=_FakeCatalogService(plugins, {}),
                action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
                settings_service=_FakeSettingsService({plugin_id: {"binary_path": "bin/tool.bin"}}),
            )
            report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertTrue(report.healthy)
        self.assertIn("local_prerequisites", report.checks)
        self.assertFalse(any(issue.code == "local_binary_missing" for issue in report.issues))

    def test_generic_local_model_cache_reports_missing_model_path(self) -> None:
        plugin_id = "llm.local_generic"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Local Generic",
                module="plugins.llm.local_generic",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={
                    "health": {
                        "local_model_cache": {
                            "model_path_key": "model_path",
                            "path_missing_code": "generic_model_path_missing",
                        }
                    }
                },
            )
        }
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
            settings_service=_FakeSettingsService({plugin_id: {"model_path": "models/missing.gguf"}}),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertTrue(any(issue.code == "generic_model_path_missing" for issue in report.issues))

    def test_generic_local_model_cache_passes_with_cached_model_file(self) -> None:
        plugin_id = "llm.local_generic"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Local Generic",
                module="plugins.llm.local_generic",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={
                    "health": {
                        "local_model_cache": {
                            "cache_dir_key": "cache_dir",
                            "cache_dir_default": "models/local_generic",
                            "model_id_key": "model_id",
                            "allow_download_key": "allow_download",
                            "file_globs": ["*.gguf"],
                            "not_cached_code": "generic_model_not_cached",
                        }
                    }
                },
            )
        }
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            cache_dir = app_root / "models" / "local_generic"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "demo.gguf").write_text("stub", encoding="utf-8")
            service = PluginHealthService(
                app_root,
                catalog_service=_FakeCatalogService(plugins, {}),
                action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
                settings_service=_FakeSettingsService(
                    {plugin_id: {"model_id": "demo-model", "allow_download": False}}
                ),
            )
            report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=30.0)

        self.assertTrue(report.healthy)
        self.assertFalse(any(issue.code == "generic_model_not_cached" for issue in report.issues))

    def test_stage_model_overrides_saved_model_in_action_settings(self) -> None:
        plugin_id = "llm.zai"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Z.ai",
                module="plugins.llm.zai",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection"]},
            results={(plugin_id, "test_connection"): ActionResult(status="success", message="connection_ok")},
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService(
                {
                    plugin_id: {
                        "api_key": "x",
                        "model_id": "glm-4-flash",
                        "timeout_seconds": 30,
                    }
                }
            ),
        )

        report = service.check_plugin(
            plugin_id,
            stage_id="llm_processing",
            stage_params={"model_id": "glm-4.5-air"},
            full_check=False,
            force=True,
            max_age_seconds=30.0,
        )

        self.assertTrue(report.healthy)
        _pid, _action, settings_override = action_service.call_details[-1]
        self.assertIsInstance(settings_override, dict)
        self.assertEqual(str(settings_override.get("model_id", "")), "glm-4.5-air")

    def test_stage_model_alias_overrides_saved_model_in_action_settings(self) -> None:
        plugin_id = "llm.ollama"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Ollama",
                module="plugins.llm.ollama",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection"]},
            results={(plugin_id, "test_connection"): ActionResult(status="success", message="connection_ok")},
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService(
                {
                    plugin_id: {
                        "model_id": "qwen2.5",
                    }
                }
            ),
        )

        report = service.check_plugin(
            plugin_id,
            stage_id="llm_processing",
            stage_params={"model": "tinyllama"},
            full_check=False,
            force=True,
            max_age_seconds=30.0,
        )

        self.assertTrue(report.healthy)
        _pid, _action, settings_override = action_service.call_details[-1]
        self.assertIsInstance(settings_override, dict)
        self.assertEqual(str(settings_override.get("model_id", "")), "tinyllama")

    def test_stage_model_path_does_not_force_settings_model_id(self) -> None:
        plugin_id = "llm.llama_cli"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Llama CLI",
                module="plugins.llm.llama_cli",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={"models": {"storage": "local"}},
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["list_models"]},
            results={
                (plugin_id, "list_models"): ActionResult(
                    status="success",
                    message="models_loaded",
                    data={"models": [{"model_id": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF", "installed": True}]},
                )
            },
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService(
                {
                    plugin_id: {
                        "model_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
                        "model_path": "",
                    }
                }
            ),
        )

        report = service.check_plugin(
            plugin_id,
            stage_id="llm_processing",
            stage_params={"model_path": "models/llama/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf", "model_id": ""},
            full_check=True,
            force=True,
            max_age_seconds=30.0,
        )

        self.assertTrue(report.healthy)
        self.assertTrue(action_service.call_details)
        _pid, action, settings_override = action_service.call_details[-1]
        self.assertEqual(action, "list_models")
        self.assertIsInstance(settings_override, dict)
        self.assertEqual(str(settings_override.get("model_path", "")), "models/llama/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf")
        self.assertEqual(str(settings_override.get("model_id", "")), "")

    def test_fallback_required_secret_check_without_actions(self) -> None:
        plugin_id = "llm.reference_openai"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="OpenAI Reference",
                module="plugins.reference.openai_summary",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        schema = PluginUiSchema(
            plugin_id=plugin_id,
            stage_id="llm_processing",
            settings=[PluginSetting(key="api_key", label="API key", value="")],
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {plugin_id: schema}),
            action_service=_FakeActionService(action_ids={plugin_id: []}, results={}),
            settings_service=_FakeSettingsService({plugin_id: {}}),
        )

        report = service.check_plugin(plugin_id, full_check=False, force=True, max_age_seconds=60.0)
        self.assertFalse(report.healthy)
        self.assertTrue(any("missing required setting" in issue.summary.lower() for issue in report.issues))

    def test_full_check_does_not_silently_replace_selected_model(self) -> None:
        plugin_id = "llm.local_provider"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Local Provider",
                module="plugins.llm.local_provider",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={"models": {"storage": "local"}},
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["list_models"]},
            results={
                (
                    plugin_id,
                    "list_models",
                ): ActionResult(
                    status="success",
                    message="models_loaded",
                    data={"models": [{"model_id": "other-model", "installed": True}]},
                )
            },
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {"model_id": "target-model"}}),
        )

        report = service.check_plugin(plugin_id, full_check=True, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertTrue(any(issue.code == "model_not_found" for issue in report.issues))
        self.assertEqual(action_service.calls.count((plugin_id, "list_models")), 1)

    def test_full_check_fails_local_provider_when_no_installed_models(self) -> None:
        plugin_id = "llm.local_provider"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Local Provider",
                module="plugins.llm.local_provider",
                class_name="Plugin",
                enabled=True,
                installed=True,
                capabilities={"models": {"storage": "local"}},
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["list_models"]},
            results={
                (
                    plugin_id,
                    "list_models",
                ): ActionResult(
                    status="success",
                    message="models_loaded",
                    data={"models": [{"model_id": "only-remote", "installed": False}]},
                )
            },
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {}}),
        )

        report = service.check_plugin(plugin_id, full_check=True, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertTrue(any(issue.code == "model_not_found" for issue in report.issues))
        self.assertTrue(any(issue.severity == "error" for issue in report.issues))

    def test_full_check_treats_test_model_warning_as_unhealthy(self) -> None:
        plugin_id = "llm.ollama"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="Ollama",
                module="plugins.llm.ollama",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_model"]},
            results={
                (plugin_id, "test_model"): ActionResult(
                    status="success",
                    message="model_available_no_output",
                    data={"model_id": "m1"},
                    warnings=["model_response_empty"],
                )
            },
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {"model_id": "m1"}}),
        )

        report = service.check_plugin(plugin_id, full_check=True, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertTrue(any(issue.code == "action_test_model_warning" for issue in report.issues))

    def test_full_check_treats_mock_fallback_warning_as_unhealthy(self) -> None:
        plugin_id = "llm.openrouter"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="OpenRouter",
                module="plugins.llm.openrouter",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection"]},
            results={
                (plugin_id, "test_connection"): ActionResult(
                    status="success",
                    message="connection_ok",
                    warnings=["mock_fallback"],
                )
            },
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {"api_key": "x"}}),
        )

        report = service.check_plugin(plugin_id, full_check=True, force=True, max_age_seconds=30.0)

        self.assertFalse(report.healthy)
        self.assertTrue(any(issue.code == "action_test_connection_warning" for issue in report.issues))

    def test_full_check_prefers_test_model_over_test_connection_when_model_selected(self) -> None:
        plugin_id = "llm.openrouter"
        plugins = {
            plugin_id: PluginDescriptor(
                plugin_id=plugin_id,
                stage_id="llm_processing",
                name="OpenRouter",
                module="plugins.llm.openrouter",
                class_name="Plugin",
                enabled=True,
                installed=True,
            )
        }
        action_service = _FakeActionService(
            action_ids={plugin_id: ["test_connection", "test_model"]},
            results={
                (plugin_id, "test_connection"): ActionResult(status="error", message="connection_failed"),
                (plugin_id, "test_model"): ActionResult(status="success", message="model_ok"),
            },
        )
        service = PluginHealthService(
            repo_root,
            catalog_service=_FakeCatalogService(plugins, {}),
            action_service=action_service,
            settings_service=_FakeSettingsService({plugin_id: {"model_id": "m1", "api_key": "x"}}),
        )

        report = service.check_plugin(plugin_id, full_check=True, force=True, max_age_seconds=30.0)

        self.assertTrue(report.healthy)
        self.assertIn((plugin_id, "test_model"), action_service.calls)
        self.assertNotIn((plugin_id, "test_connection"), action_service.calls)


if __name__ == "__main__":
    unittest.main()
