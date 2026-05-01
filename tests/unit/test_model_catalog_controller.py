import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.model_catalog_controller import ModelCatalogController  # noqa: E402


class _FakeSettingsStore:
    def __init__(self, data: dict[str, dict]) -> None:
        self._data = data

    def get_settings(self, plugin_id: str, *, include_secrets: bool = False) -> dict:
        payload = self._data.get(str(plugin_id), {})
        return dict(payload) if isinstance(payload, dict) else {}

    def set_settings(self, plugin_id: str, payload: dict, *, secret_fields: list, preserve_secrets: list) -> None:
        self._data[str(plugin_id)] = dict(payload)


class _FakeModelsService:
    def __init__(self, data: dict[str, list[dict]]) -> None:
        self._data = data

    def load_models_config(self, plugin_id: str) -> list[dict]:
        return list(self._data.get(str(plugin_id), []))


class _FakeActionService:
    def __init__(self, responses: dict[tuple[str, str], object] | None = None) -> None:
        self._responses = dict(responses or {})
        self.calls: list[tuple[str, str]] = []

    def invoke_action(self, plugin_id: str, action: str, _payload: dict):
        key = (str(plugin_id), str(action))
        self.calls.append(key)
        return self._responses.get(key, {"status": "success", "data": {"models": []}})


class _FakeCatalog:
    def __init__(self, models: dict[str, dict], capabilities: dict[str, dict] | None = None) -> None:
        self._models = models
        self._capabilities = dict(capabilities or {})

    def plugin_by_id(self, plugin_id: str):
        info = self._models.get(str(plugin_id), {})
        caps = self._capabilities.get(str(plugin_id), {})
        return SimpleNamespace(model_info=info, capabilities=caps)


class TestModelCatalogController(unittest.TestCase):
    @staticmethod
    def _host_id() -> str:
        return ModelCatalogController._current_host_id()

    def _workspace_root(self, name: str) -> Path:
        root = repo_root / "logs" / "_test_tmp" / name
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _make_controller(
        self,
        *,
        app_root: Path,
        settings: dict[str, dict] | None = None,
        models: dict[str, list[dict]] | None = None,
        plugin_model_info: dict[str, dict] | None = None,
        capabilities: dict[str, dict] | None = None,
        action_responses: dict[tuple[str, str], object] | None = None,
    ) -> ModelCatalogController:
        settings_store = _FakeSettingsStore(settings or {})
        models_service = _FakeModelsService(models or {})
        catalog = _FakeCatalog(plugin_model_info or {}, capabilities=capabilities or {})
        action_service = _FakeActionService(action_responses)
        return ModelCatalogController(
            app_root=app_root,
            config_data_provider=lambda: {},
            settings_store=settings_store,
            models_service=models_service,
            action_service=action_service,
            get_catalog=lambda: catalog,
            plugin_capabilities=lambda _pid: {},
            is_transcription_local_plugin=lambda _pid: True,
            first_transcription_local_plugin_id=lambda: "",
            is_secret_field_name=lambda _key: False,
        )

    def test_models_from_action_result_normalizes_fields(self) -> None:
        result = {
            "data": {
                "models": [
                    {"id": "m1", "name": "Model 1", "enabled": True},
                    {"model_path": "models/a.gguf", "label": "A", "enabled": False},
                ]
            }
        }
        models = ModelCatalogController.models_from_action_result(result)
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["model_id"], "m1")
        self.assertEqual(models[0]["product_name"], "Model 1")
        self.assertEqual(models[0]["availability_status"], "unknown")
        self.assertEqual(models[1]["model_path"], "models/a.gguf")
        self.assertNotIn("favorite", models[0])
        self.assertNotIn("favorite", models[1])

    def test_models_from_action_result_preserves_explicit_enabled_without_favorite_projection(self) -> None:
        result = {
            "models": [
                {"model_id": "m1", "enabled": True, "favorite": False},
                {"model_id": "m2", "enabled": False, "favorite": True},
            ]
        }

        models = ModelCatalogController.models_from_action_result(result)

        self.assertTrue(models[0]["enabled"])
        self.assertFalse(models[1]["enabled"])
        self.assertNotIn("favorite", models[0])
        self.assertNotIn("favorite", models[1])

    def test_models_from_action_result_normalizes_availability_statuses(self) -> None:
        result = {
            "models": [
                {"model_id": "ready-model", "status": "ready"},
                {"model_id": "setup-model", "status": "not_installed"},
                {"model_id": "limited-model", "status": "rate_limited"},
                {"model_id": "down-model", "status": "request_failed"},
                {"model_id": "installed-model", "installed": True},
            ]
        }

        models = ModelCatalogController.models_from_action_result(result)
        availability_by_id = {str(item["model_id"]): str(item["availability_status"]) for item in models}

        self.assertEqual(availability_by_id["ready-model"], "ready")
        self.assertEqual(availability_by_id["setup-model"], "needs_setup")
        self.assertEqual(availability_by_id["limited-model"], "limited")
        self.assertEqual(availability_by_id["down-model"], "unavailable")
        self.assertEqual(availability_by_id["installed-model"], "ready")

    def test_models_from_action_result_does_not_apply_default_favorites(self) -> None:
        result = {
            "models": [
                {"model_id": "m1", "favorite_by_default": True},
                {"model_id": "m2", "recommended": True},
            ]
        }

        models = ModelCatalogController.models_from_action_result(result)
        by_id = {str(item["model_id"]): item for item in models}
        self.assertNotIn("favorite", by_id["m1"])
        self.assertNotIn("favorite", by_id["m2"])
        self.assertNotIn("recommended", by_id["m2"])
        self.assertNotIn("recommended_by_team", by_id["m2"])

    def test_models_from_action_result_marks_observed_success_from_runtime_fields(self) -> None:
        result = {
            "models": [
                {"model_id": "m1", "last_pipeline_quality": "usable"},
                {"model_id": "m2", "last_ok_at": 12345},
                {"model_id": "m3", "last_pipeline_quality": "failed"},
            ]
        }

        models = ModelCatalogController.models_from_action_result(result)
        observed = {str(item["model_id"]): bool(item.get("observed_success")) for item in models}

        self.assertTrue(observed["m1"])
        self.assertTrue(observed["m2"])
        self.assertFalse(observed["m3"])

    def test_load_plugin_models_config_uses_passport_models_without_auto_favorites(self) -> None:
        catalog = _FakeCatalog(
            {
                "llm.remote": {
                    "m1": {"model_name": "Model 1", "recommended": True, "favorite_by_default": True},
                    "m2": {"model_name": "Model 2"},
                }
            }
        )
        controller = ModelCatalogController(
            app_root=repo_root,
            config_data_provider=lambda: {},
            settings_store=_FakeSettingsStore({}),
            models_service=_FakeModelsService({}),
            action_service=_FakeActionService(),
            get_catalog=lambda: catalog,
            plugin_capabilities=lambda _pid: {},
            is_transcription_local_plugin=lambda _pid: True,
            first_transcription_local_plugin_id=lambda: "",
            is_secret_field_name=lambda _key: False,
        )

        rows = controller.load_plugin_models_config("llm.remote")
        by_id = {str(item["model_id"]): item for item in rows}
        self.assertIn("m1", by_id)
        self.assertIn("m2", by_id)
        self.assertNotIn("favorite", by_id["m1"])
        self.assertNotIn("recommended", by_id["m1"])
        self.assertNotIn("recommended_by_team", by_id["m1"])

    def test_load_plugin_models_config_merges_passport_models_with_existing_settings_rows(self) -> None:
        catalog = _FakeCatalog(
            {
                "llm.remote": {
                    "m1": {"model_name": "Model 1"},
                    "xiaomi/mi-mo-thinking-preview": {
                        "model_name": "Xiaomi MiMo Thinking Preview",
                        "recommended": True,
                        "favorite_by_default": True,
                    },
                }
            }
        )
        settings_store = _FakeSettingsStore(
            {
                "llm.remote": {
                    "models": [
                        {"model_id": "m1", "product_name": "Model 1", "favorite": True},
                    ]
                }
            }
        )
        controller = ModelCatalogController(
            app_root=repo_root,
            config_data_provider=lambda: {},
            settings_store=settings_store,
            models_service=_FakeModelsService({}),
            action_service=_FakeActionService(),
            get_catalog=lambda: catalog,
            plugin_capabilities=lambda _pid: {},
            is_transcription_local_plugin=lambda _pid: True,
            first_transcription_local_plugin_id=lambda: "",
            is_secret_field_name=lambda _key: False,
        )

        rows = controller.load_plugin_models_config("llm.remote")
        by_id = {str(item["model_id"]): item for item in rows}

        self.assertIn("m1", by_id)
        self.assertIn("xiaomi/mi-mo-thinking-preview", by_id)
        self.assertNotIn("recommended", by_id["xiaomi/mi-mo-thinking-preview"])
        self.assertNotIn("recommended_by_team", by_id["xiaomi/mi-mo-thinking-preview"])

    def test_load_plugin_models_config_normalizes_local_model_ids_and_removes_passport_duplicates(self) -> None:
        catalog = _FakeCatalog(
            {
                "llm.local": {
                    "unsloth/Qwen3-0.6B-GGUF": {"model_name": "Qwen3 0.6B (GGUF)"},
                    "Qwen/Qwen3-1.7B-GGUF": {"model_name": "Qwen3 1.7B (GGUF)"},
                }
            },
            capabilities={
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "root_setting": "cache_dir",
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        }
                    }
                }
            },
        )
        settings_store = _FakeSettingsStore(
            {
                "llm.local": {
                    "_models_catalog_meta": {"host_id": self._host_id(), "updated_at": 1},
                    "models": [
                        {
                            "model_id": "unsloth/Qwen3-0.6B-GGUF",
                            "product_name": "Qwen3 0.6B (GGUF)",
                            "file": "Qwen3-0.6B-Q4_K_M.gguf",
                            "model_path": "models/llama/Qwen3-0.6B-Q4_K_M.gguf",
                            "installed": True,
                            "status": "installed",
                        },
                        {
                            "model_id": "Qwen3-1.7B-GGUF",
                            "product_name": "Qwen3-1.7B-GGUF",
                            "availability_status": "ready",
                        },
                        {
                            "model_id": "Qwen/Qwen3-1.7B-GGUF",
                            "product_name": "Qwen3 1.7B (GGUF)",
                            "availability_status": "unknown",
                        },
                    ],
                }
            }
        )
        controller = ModelCatalogController(
            app_root=repo_root,
            config_data_provider=lambda: {},
            settings_store=settings_store,
            models_service=_FakeModelsService({}),
            action_service=_FakeActionService(),
            get_catalog=lambda: catalog,
            plugin_capabilities=lambda _pid: {},
            is_transcription_local_plugin=lambda _pid: True,
            first_transcription_local_plugin_id=lambda: "",
            is_secret_field_name=lambda _key: False,
        )

        rows = controller.load_plugin_models_config("llm.local")
        ids = [str(item.get("model_id", "")) for item in rows]

        self.assertEqual(ids.count("unsloth/Qwen3-0.6B-GGUF"), 1)
        self.assertEqual(ids.count("Qwen/Qwen3-1.7B-GGUF"), 1)
        self.assertNotIn("Qwen3-1.7B-GGUF", ids)

    def test_load_plugin_models_config_migrates_legacy_enabled_to_availability_only(self) -> None:
        settings_store = _FakeSettingsStore(
            {
                "llm.remote": {
                    "models": [
                        {"model_id": "m1", "product_name": "Model 1", "enabled": True, "status": "ready"},
                        {"model_id": "m2", "product_name": "Model 2", "enabled": False, "status": "request_failed"},
                    ]
                }
            }
        )
        controller = ModelCatalogController(
            app_root=repo_root,
            config_data_provider=lambda: {},
            settings_store=settings_store,
            models_service=_FakeModelsService({}),
            action_service=_FakeActionService(),
            get_catalog=lambda: _FakeCatalog({}),
            plugin_capabilities=lambda _pid: {},
            is_transcription_local_plugin=lambda _pid: True,
            first_transcription_local_plugin_id=lambda: "",
            is_secret_field_name=lambda _key: False,
        )

        rows = controller.load_plugin_models_config("llm.remote")

        self.assertTrue(rows[0]["enabled"])
        self.assertEqual(rows[0]["availability_status"], "ready")
        self.assertFalse(rows[1]["enabled"])
        self.assertEqual(rows[1]["availability_status"], "unavailable")
        persisted = settings_store.get_settings("llm.remote", include_secrets=False)
        persisted_rows = persisted.get("models", [])
        self.assertNotIn("favorite", persisted_rows[0])
        self.assertEqual(persisted_rows[1]["availability_status"], "unavailable")

    def test_llm_installed_models_payload_keeps_runtime_limited_models_visible_with_policy_fields(self) -> None:
        controller = self._make_controller(
            app_root=repo_root,
            settings={
                "llm.remote": {
                    "models": [
                        {
                            "model_id": "m1",
                            "product_name": "Model 1",
                            "favorite": True,
                            "availability_status": "limited",
                            "failure_code": "rate_limited",
                            "selectable": False,
                            "cooldown_until": int(2**31),
                            "last_pipeline_quality": "failed",
                            "blocked_for_account": False,
                        }
                    ]
                }
            },
        )

        payload = controller.llm_installed_models_payload("llm.remote")

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["model_id"], "m1")
        self.assertEqual(payload[0]["availability_status"], "limited")
        self.assertEqual(payload[0]["failure_code"], "rate_limited")
        self.assertEqual(payload[0]["selectable"], False)
        self.assertGreater(int(payload[0]["cooldown_until"]), 0)

    def test_load_plugin_models_config_marks_blocked_for_account_as_unavailable(self) -> None:
        settings_store = _FakeSettingsStore(
            {
                "llm.remote": {
                    "models": [
                        {
                            "model_id": "m1",
                            "product_name": "Model 1",
                            "favorite": True,
                            "blocked_for_account": True,
                            "availability_status": "unknown",
                        }
                    ]
                }
            }
        )
        controller = ModelCatalogController(
            app_root=repo_root,
            config_data_provider=lambda: {},
            settings_store=settings_store,
            models_service=_FakeModelsService({}),
            action_service=_FakeActionService(),
            get_catalog=lambda: _FakeCatalog({}),
            plugin_capabilities=lambda _pid: {},
            is_transcription_local_plugin=lambda _pid: True,
            first_transcription_local_plugin_id=lambda: "",
            is_secret_field_name=lambda _key: False,
        )

        rows = controller.load_plugin_models_config("llm.remote")

        self.assertEqual(rows[0]["availability_status"], "unavailable")

    def test_llm_enabled_models_from_stage_collects_variant_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = self._make_controller(app_root=Path(temp_dir))
            enabled, selected = controller.llm_enabled_models_from_stage(
                plugin_id="llm.main",
                stage_params={},
                variants=[
                    {"plugin_id": "llm.a", "params": {"model_id": "m-a"}},
                    {"plugin_id": "llm.b", "params": {"model_path": "models/b.gguf"}},
                ],
                providers=["llm.a", "llm.b"],
            )
            self.assertEqual(selected, "llm.a")
            self.assertIn("id:m-a", enabled.get("llm.a", []))
            self.assertIn("path:models/b.gguf", enabled.get("llm.b", []))

    def test_llm_enabled_models_from_stage_drops_missing_local_model_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.local", "list_models"): {
                    "status": "success",
                    "data": {"models": [{"model_id": "installed", "installed": True}]},
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                capabilities=capabilities,
                action_responses=action_responses,
            )
            controller.refresh_models_from_provider("llm.local")
            enabled, _selected = controller.llm_enabled_models_from_stage(
                plugin_id="",
                stage_params={},
                variants=[
                    {"plugin_id": "llm.local", "params": {"model_id": "installed"}},
                    {"plugin_id": "llm.local", "params": {"model_id": "missing"}},
                ],
                providers=["llm.local"],
            )
            self.assertEqual(enabled.get("llm.local", []), ["id:installed"])

    def test_llm_enabled_models_from_stage_keeps_available_variant_when_same_provider_has_missing_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.local", "list_models"): {
                    "status": "success",
                    "data": {"models": [{"model_id": "installed", "installed": True}]},
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                capabilities=capabilities,
                action_responses=action_responses,
            )
            controller.refresh_models_from_provider("llm.local")

            enabled, selected = controller.llm_enabled_models_from_stage(
                plugin_id="",
                stage_params={},
                variants=[
                    {"plugin_id": "llm.local", "params": {"model_id": "missing"}},
                    {"plugin_id": "llm.local", "params": {"model_id": "installed"}},
                ],
                providers=["llm.local"],
            )

            self.assertEqual(selected, "llm.local")
            self.assertEqual(enabled.get("llm.local", []), ["id:installed"])

    def test_local_models_from_capabilities_reads_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            model_dir = app_root / "models" / "llama"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "alpha.gguf").write_text("x", encoding="utf-8")

            settings_store = _FakeSettingsStore({})
            models_service = _FakeModelsService({})
            caps = {
                "models": {
                    "local_files": {
                        "default_root": "models/llama",
                        "glob": "*.gguf",
                    }
                }
            }
            plugin = SimpleNamespace(model_info={}, capabilities=caps)
            catalog = SimpleNamespace(plugin_by_id=lambda _pid: plugin)
            controller = ModelCatalogController(
                app_root=app_root,
                config_data_provider=lambda: {},
                settings_store=settings_store,
                models_service=models_service,
                action_service=_FakeActionService(),
                get_catalog=lambda: catalog,
                plugin_capabilities=lambda _pid: caps,
                is_transcription_local_plugin=lambda _pid: True,
                first_transcription_local_plugin_id=lambda: "",
                is_secret_field_name=lambda _key: False,
            )

            models = controller.local_models_from_capabilities("llm.local")
            self.assertEqual(len(models), 1)
            self.assertIn("alpha.gguf", models[0]["label"])
            self.assertTrue(models[0]["installed"])
            self.assertEqual(models[0]["status"], "installed")

    def test_llm_installed_models_payload_discovers_files_even_when_settings_only_has_recommended_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            model_dir = app_root / "models" / "llama"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "alpha.gguf").write_text("x", encoding="utf-8")
            (model_dir / "beta.gguf").write_text("x", encoding="utf-8")

            capabilities = {
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        },
                    }
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.local": {
                        "models": [
                            {"model_id": "recommended/a", "product_name": "Recommended A", "installed": False},
                            {"model_id": "recommended/b", "product_name": "Recommended B", "installed": False},
                        ]
                    }
                },
                capabilities=capabilities,
            )

            payload = controller.llm_installed_models_payload("llm.local")

            self.assertEqual(
                {str(item.get("model_path", "")) for item in payload},
                {"models/llama/alpha.gguf", "models/llama/beta.gguf"},
            )

    def test_llm_installed_models_payload_merges_settings_cache_with_filesystem_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            model_dir = app_root / "models" / "llama"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "alpha.gguf").write_text("x", encoding="utf-8")
            (model_dir / "beta.gguf").write_text("x", encoding="utf-8")

            capabilities = {
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        },
                    }
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.local": {
                        "models": [
                            {"model_id": "catalog/alpha", "product_name": "Alpha Catalog", "installed": True, "file": "alpha.gguf"},
                        ]
                    }
                },
                capabilities=capabilities,
            )

            payload = controller.llm_installed_models_payload("llm.local")

            self.assertEqual(len(payload), 2)
            self.assertIn("catalog/alpha", {str(item.get("model_id", "")) for item in payload})
            self.assertIn("models/llama/beta.gguf", {str(item.get("model_path", "")) for item in payload})

    def test_local_models_from_capabilities_maps_discovered_file_to_canonical_model_id(self) -> None:
        app_root = self._workspace_root("model_catalog_canonical_discovery")
        model_dir = app_root / "models" / "llama"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "Qwen3-1.7B-Q8_0.gguf").write_text("x", encoding="utf-8")

        controller = self._make_controller(
            app_root=app_root,
            settings={
                "llm.local": {
                    "_models_catalog_meta": {"host_id": "foreign-host"},
                    "models": [
                        {
                            "model_id": "Qwen/Qwen3-1.7B-GGUF",
                            "product_name": "Qwen3 1.7B (GGUF)",
                            "file": "Qwen3-1.7B-Q8_0.gguf",
                            "installed": True,
                        }
                    ],
                }
            },
            plugin_model_info={
                "llm.local": {
                    "Qwen/Qwen3-1.7B-GGUF": {
                        "model_name": "Qwen3 1.7B (GGUF)",
                        "file": "Qwen3-1.7B-Q8_0.gguf",
                    }
                }
            },
            capabilities={
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        },
                    }
                }
            },
        )

        models = controller.local_models_from_capabilities("llm.local")

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["model_id"], "Qwen/Qwen3-1.7B-GGUF")
        self.assertEqual(models[0]["file"], "Qwen3-1.7B-Q8_0.gguf")

    def test_is_model_selection_available_accepts_canonical_model_id_from_discovered_file_when_host_cache_is_foreign(self) -> None:
        app_root = self._workspace_root("model_catalog_foreign_host_selection")
        model_dir = app_root / "models" / "llama"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "Qwen3-1.7B-Q8_0.gguf").write_text("x", encoding="utf-8")

        controller = self._make_controller(
            app_root=app_root,
            settings={
                "llm.local": {
                    "_models_catalog_meta": {"host_id": "foreign-host"},
                    "models": [
                        {
                            "model_id": "Qwen/Qwen3-1.7B-GGUF",
                            "product_name": "Qwen3 1.7B (GGUF)",
                            "file": "Qwen3-1.7B-Q8_0.gguf",
                            "installed": True,
                        }
                    ],
                }
            },
            plugin_model_info={
                "llm.local": {
                    "Qwen/Qwen3-1.7B-GGUF": {
                        "model_name": "Qwen3 1.7B (GGUF)",
                        "file": "Qwen3-1.7B-Q8_0.gguf",
                    }
                }
            },
            capabilities={
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        },
                    }
                }
            },
        )

        self.assertTrue(
            controller.is_model_selection_available(
                "llm.local",
                {"model_id": "Qwen/Qwen3-1.7B-GGUF"},
            )
        )

    def test_model_options_for_local_plugin_uses_settings_without_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.ollama": {
                    "models": {
                        "storage": "local",
                        "selection_requires_installed": True,
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.ollama": {
                        "models": [
                            {"model_id": "phi3:mini", "product_name": "phi3:mini", "installed": True},
                            {"model_id": "qwen3-vl:235b-cloud", "product_name": "qwen3-vl:235b-cloud", "installed": False},
                        ]
                    }
                },
                capabilities=capabilities,
            )

            options = controller.model_options_for("llm.ollama")
            values = [str(item.value) for item in options]
            self.assertEqual(values, ["phi3:mini", "qwen3-vl:235b-cloud"])
            self.assertEqual(controller._action_service.calls, [])  # type: ignore[attr-defined]

    def test_model_options_for_local_plugin_ignores_foreign_host_settings_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.ollama": {
                    "models": {
                        "storage": "local",
                        "selection_requires_installed": True,
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.ollama": {
                        "_models_catalog_meta": {"host_id": "foreign-host"},
                        "models": [
                            {"model_id": "phi3:mini", "product_name": "phi3:mini", "installed": True},
                            {"model_id": "deepseek-v3.1:671b-cloud", "product_name": "deepseek-v3.1:671b-cloud", "installed": False},
                        ],
                    }
                },
                capabilities=capabilities,
            )
            options = controller.model_options_for("llm.ollama")
            self.assertEqual(options, [])

    def test_refresh_models_from_provider_populates_installed_cache_and_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.ollama": {
                    "models": {
                        "storage": "local",
                        "selection_requires_installed": True,
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.ollama", "list_models"): {
                    "status": "success",
                    "data": {
                        "models": [
                            {"model_id": "phi3:mini", "product_name": "phi3:mini", "installed": True},
                            {"model_id": "llama3.2", "product_name": "llama3.2", "installed": False},
                        ]
                    },
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={"llm.ollama": {"models": []}},
                capabilities=capabilities,
                action_responses=action_responses,
            )

            ok, status = controller.refresh_models_from_provider("llm.ollama")
            self.assertTrue(ok)
            self.assertEqual(status, "ok")
            options = controller.model_options_for("llm.ollama")
            values = [str(item.value) for item in options]
            self.assertIn("phi3:mini", values)
            self.assertNotIn("llama3.2", values)
            rows = controller.load_plugin_models_config("llm.ollama")
            self.assertEqual(len(rows), 2)
            settings_payload = controller._settings_store.get_settings("llm.ollama", include_secrets=False)  # type: ignore[attr-defined]
            meta = settings_payload.get("_models_catalog_meta", {})
            self.assertEqual(str(meta.get("host_id", "")), self._host_id())

    def test_ollama_selection_availability_requires_installed_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.ollama": {
                    "models": {
                        "storage": "local",
                        "selection_requires_installed": True,
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.ollama": {
                        "models": [
                            {"model_id": "phi3:mini", "product_name": "phi3:mini", "installed": True},
                            {"model_id": "llama3.2", "product_name": "llama3.2", "installed": False},
                        ]
                    }
                },
                capabilities=capabilities,
            )

            self.assertTrue(controller.is_model_selection_available("llm.ollama", {"model_id": "phi3:mini"}))
            self.assertFalse(controller.is_model_selection_available("llm.ollama", {"model_id": "llama3.2"}))

    def test_refresh_models_from_provider_persists_card_metadata_for_local_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.ollama": {
                    "models": {
                        "storage": "local",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.ollama", "list_models"): {
                    "status": "success",
                    "data": {
                        "models": [
                            {
                                "model_id": "llama3.2",
                                "product_name": "Llama 3.2",
                                "installed": True,
                                "source_url": "https://ollama.com/library/llama3.2",
                                "size_hint": "~2GB",
                            },
                        ]
                    },
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={"llm.ollama": {"models": []}},
                capabilities=capabilities,
                action_responses=action_responses,
            )

            ok, status = controller.refresh_models_from_provider("llm.ollama")

            self.assertTrue(ok)
            self.assertEqual(status, "ok")
            rows = controller.load_plugin_models_config("llm.ollama")
            self.assertEqual(rows[0]["source_url"], "https://ollama.com/library/llama3.2")
            self.assertEqual(rows[0]["size_hint"], "~2GB")

    def test_is_model_selection_available_checks_local_model_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.local", "list_models"): {
                    "status": "success",
                    "data": {"models": [{"model_id": "m1", "installed": True}]},
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                capabilities=capabilities,
                action_responses=action_responses,
            )
            controller.refresh_models_from_provider("llm.local")
            self.assertTrue(controller.is_model_selection_available("llm.local", {"model_id": "m1"}))
            self.assertFalse(controller.is_model_selection_available("llm.local", {"model_id": "missing"}))

    def test_is_model_selection_available_accepts_local_installed_model_by_id_when_payload_has_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.local", "list_models"): {
                    "status": "success",
                    "data": {
                        "models": [
                            {
                                "model_id": "m1",
                                "model_path": "models/llama/m1.gguf",
                                "installed": True,
                            }
                        ]
                    },
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                capabilities=capabilities,
                action_responses=action_responses,
            )
            controller.refresh_models_from_provider("llm.local")

            self.assertTrue(controller.is_model_selection_available("llm.local", {"model_id": "m1"}))

    def test_refresh_models_from_provider_falls_back_to_saved_remote_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.remote": {
                    "models": {
                        "storage": "online",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.remote", "list_models"): {
                    "status": "error",
                    "message": "auth_required",
                    "data": {"models": []},
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.remote": {
                        "models": [
                            {"model_id": "m1", "enabled": True, "product_name": "Model 1"},
                        ]
                    }
                },
                capabilities=capabilities,
                action_responses=action_responses,
            )

            ok, status = controller.refresh_models_from_provider("llm.remote")
            self.assertTrue(ok)
            self.assertEqual(status, "ok")
            payload = controller.llm_provider_models_payload(["llm.remote"])
            self.assertEqual(payload["llm.remote"][0]["model_id"], "m1")

    def test_refresh_models_from_provider_preserves_explicit_unfavorite_for_default_favorite_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.remote": {
                    "models": {
                        "storage": "online",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            action_responses = {
                ("llm.remote", "list_models"): {
                    "status": "success",
                    "data": {
                        "models": [
                            {
                                "model_id": "m1",
                                "product_name": "Model 1",
                                "recommended": True,
                                "favorite_by_default": True,
                            },
                            {
                                "model_id": "m2",
                                "product_name": "Model 2",
                            },
                        ]
                    },
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.remote": {
                        "models": [
                            {
                                "model_id": "m1",
                                "product_name": "Model 1",
                                "favorite": False,
                                "enabled": False,
                            }
                        ]
                    }
                },
                capabilities=capabilities,
                action_responses=action_responses,
            )

            ok, status = controller.refresh_models_from_provider("llm.remote")

            self.assertTrue(ok)
            self.assertEqual(status, "ok")
            rows = controller.load_plugin_models_config("llm.remote")
            favorite_by_id = {str(item.get("model_id", "")): bool(item.get("favorite")) for item in rows}
            self.assertFalse(favorite_by_id["m1"])

            payload = controller.llm_provider_models_payload(["llm.remote"], favorites_only=True)
            self.assertEqual(payload["llm.remote"], [])

    def test_is_model_selection_available_rejects_cloud_model_marked_not_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            capabilities = {
                "llm.remote": {
                    "models": {
                        "storage": "online",
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.remote": {
                        "models": [
                            {"model_id": "good-model", "product_name": "Good", "selectable": True},
                            {"model_id": "bad-model", "product_name": "Bad", "selectable": False},
                        ]
                    }
                },
                capabilities=capabilities,
            )
            self.assertTrue(controller.is_model_selection_available("llm.remote", {"model_id": "good-model"}))
            self.assertFalse(controller.is_model_selection_available("llm.remote", {"model_id": "bad-model"}))

    def test_is_model_selection_available_allows_cloud_model_after_rate_limit_cooldown_expires(self) -> None:
        app_root = self._workspace_root("cloud_model_after_rate_limit_cooldown")
        capabilities = {
            "llm.remote": {
                "models": {
                    "storage": "online",
                    "managed_actions": {"list": "list_models"},
                }
            }
        }
        controller = self._make_controller(
            app_root=app_root,
            settings={
                "llm.remote": {
                    "models": [
                        {
                            "model_id": "cooldown-model",
                            "product_name": "Cooldown",
                            "selectable": False,
                            "status": "rate_limited",
                            "failure_code": "rate_limited",
                            "availability_status": "limited",
                            "cooldown_until": 1,
                        }
                    ]
                }
            },
            capabilities=capabilities,
        )

        self.assertTrue(controller.is_model_selection_available("llm.remote", {"model_id": "cooldown-model"}))

    def test_is_model_selection_available_allows_cloud_model_during_rate_limit_cooldown(self) -> None:
        app_root = self._workspace_root("cloud_model_during_rate_limit_cooldown")
        capabilities = {
            "llm.remote": {
                "models": {
                    "storage": "online",
                    "managed_actions": {"list": "list_models"},
                }
            }
        }
        controller = self._make_controller(
            app_root=app_root,
            settings={
                "llm.remote": {
                    "models": [
                        {
                            "model_id": "cooldown-model",
                            "product_name": "Cooldown",
                            "selectable": False,
                            "status": "rate_limited",
                            "failure_code": "rate_limited",
                            "availability_status": "limited",
                            "cooldown_until": 2**31,
                        }
                    ]
                }
            },
            capabilities=capabilities,
        )

        self.assertTrue(controller.is_model_selection_available("llm.remote", {"model_id": "cooldown-model"}))

    def test_model_options_for_remote_plugin_returns_only_favorites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.zai": {
                        "models": [
                            {"model_id": "glm-4.5-flash", "enabled": True, "product_name": "Z.ai 4.5 Flash"},
                            {"model_id": "glm-4.7-flash", "enabled": False, "product_name": "Z.ai 4.7 Flash"},
                        ]
                    }
                },
            )

            options = controller.model_options_for("llm.zai")
            values = [str(item.value) for item in options]

            self.assertEqual(values, ["glm-4.5-flash"])

    def test_llm_provider_models_payload_keeps_remote_models_even_if_not_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.zai": {
                        "models": [
                            {"model_id": "glm-4.5-flash", "enabled": True, "product_name": "Z.ai 4.5 Flash"},
                            {"model_id": "glm-4.7-flash", "enabled": False, "product_name": "Z.ai 4.7 Flash"},
                        ]
                    }
                },
            )

            payload = controller.llm_provider_models_payload(["llm.zai"])
            values = [str(item.get("model_id", "")) for item in payload.get("llm.zai", [])]

            self.assertEqual(values, ["glm-4.5-flash", "glm-4.7-flash"])

    def test_favorite_models_payload_returns_available_models_for_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.remote": {
                        "models": [
                            {"model_id": "m1", "product_name": "M1", "favorite": True},
                            {"model_id": "m2", "product_name": "M2", "enabled": True},
                            {"model_id": "m3", "product_name": "M3", "favorite": False, "enabled": True},
                            {"model_id": "m4", "product_name": "M4", "enabled": False},
                        ]
                    }
                },
            )

            payload = controller.favorite_models_payload("llm.remote")
            model_ids = [str(item.get("model_id", "")) for item in payload]

            self.assertEqual(model_ids, ["m1", "m2", "m3", "m4"])

    def test_llm_provider_models_payload_available_only_keeps_available_and_enabled_selection(self) -> None:
        controller = self._make_controller(
            app_root=repo_root,
            settings={
                "llm.remote": {
                    "models": [
                        {"model_id": "m1", "product_name": "M1", "availability_status": "ready"},
                        {"model_id": "m2", "product_name": "M2", "availability_status": "needs_setup"},
                        {"model_id": "m3", "product_name": "M3", "availability_status": "unavailable"},
                    ]
                }
            },
        )

        payload = controller.llm_provider_models_payload(
            ["llm.remote"],
            enabled_models={"llm.remote": ["id:m3"]},
            available_only=True,
        )
        model_ids = [str(item.get("model_id", "")) for item in payload.get("llm.remote", [])]

        self.assertEqual(model_ids, ["m1", "m2", "m3"])

    def test_refresh_models_from_provider_falls_back_to_local_files_for_stage_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            model_dir = app_root / "models" / "llama"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "tiny.gguf").write_text("x", encoding="utf-8")
            capabilities = {
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        },
                        "managed_actions": {"list": "list_models"},
                    }
                }
            }
            controller = self._make_controller(
                app_root=app_root,
                capabilities=capabilities,
            )

            ok, status = controller.refresh_models_from_provider("llm.local")
            self.assertTrue(ok)
            self.assertEqual(status, "ok")
            payload = controller.llm_provider_models_payload(["llm.local"])
            self.assertEqual(len(payload["llm.local"]), 1)
            self.assertEqual(payload["llm.local"][0]["label"], "tiny.gguf")
            self.assertEqual(payload["llm.local"][0]["model_path"], "models/llama/tiny.gguf")

    def test_llm_provider_models_payload_does_not_add_missing_enabled_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            controller = self._make_controller(
                app_root=app_root,
                settings={
                    "llm.remote": {
                        "models": [
                            {"model_id": "m1", "enabled": True, "product_name": "M1"},
                        ]
                    }
                },
            )
            payload = controller.llm_provider_models_payload(
                ["llm.remote"],
                enabled_models={"llm.remote": ["id:missing"]},
            )
            rows = payload.get("llm.remote", [])
            model_ids = [str(item.get("model_id", "")) for item in rows if isinstance(item, dict)]
            self.assertIn("m1", model_ids)
            self.assertNotIn("missing", model_ids)

    def test_load_plugin_models_config_keeps_ollama_rows_without_confirmed_runtime(self) -> None:
        controller = self._make_controller(
            app_root=repo_root,
            settings={
                "llm.ollama": {
                    "_ollama_runtime_state": {
                        "ollama_installed": False,
                        "server_running": False,
                        "total": 0,
                    },
                    "models": [
                        {
                            "model_id": "llama3.2",
                            "product_name": "Llama 3.2",
                            "installed": True,
                            "status": "installed",
                        }
                    ],
                }
            },
            capabilities={
                "llm.ollama": {
                    "models": {
                        "storage": "local",
                        "selection_requires_installed": True,
                        "managed_actions": {"list": "list_models"},
                    }
                }
            },
            plugin_model_info={
                "llm.ollama": {
                    "llama3.2": {"model_name": "Llama 3.2"},
                    "qwen2.5": {"model_name": "Qwen 2.5"},
                }
            },
        )

        rows = controller.load_plugin_models_config("llm.ollama")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model_id"], "llama3.2")

    def test_llm_provider_models_payload_drops_removed_local_files_from_stage_payload(self) -> None:
        app_root = self._workspace_root("local_stage_payload_removed")
        model_dir = app_root / "models" / "llama"
        model_dir.mkdir(parents=True, exist_ok=True)
        controller = self._make_controller(
            app_root=app_root,
            settings={
                "llm.local": {
                    "_models_catalog_meta": {"host_id": self._host_id(), "updated_at": 1},
                    "models": [
                        {
                            "model_id": "Qwen/Qwen3-4B-GGUF",
                            "product_name": "Qwen3 4B",
                            "file": "Qwen3-4B-Q4_K_M.gguf",
                            "model_path": "models/llama/Qwen3-4B-Q4_K_M.gguf",
                            "installed": True,
                            "status": "installed",
                        }
                    ],
                }
            },
            capabilities={
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        },
                    }
                }
            },
            plugin_model_info={
                "llm.local": {
                    "Qwen/Qwen3-4B-GGUF": {
                        "model_name": "Qwen3 4B",
                        "file": "Qwen3-4B-Q4_K_M.gguf",
                    }
                }
            },
        )

        payload = controller.llm_provider_models_payload(["llm.local"])

        self.assertEqual(payload.get("llm.local", []), [])

    def test_load_plugin_models_config_prunes_filename_only_local_rows(self) -> None:
        app_root = self._workspace_root("local_invalid_filename_rows")
        controller = self._make_controller(
            app_root=app_root,
            settings={
                "llm.local": {
                    "_models_catalog_meta": {"host_id": self._host_id(), "updated_at": 1},
                    "models": [
                        {
                            "model_id": "Qwen/Qwen3-0.6B-GGUF",
                            "product_name": "Qwen3 0.6B (GGUF)",
                            "file": "Qwen3-0.6B-Q4_K_M.gguf",
                            "model_path": "models/llama/Qwen3-0.6B-Q4_K_M.gguf",
                            "installed": True,
                            "status": "installed",
                        },
                        {
                            "model_id": "Qwen3-0.6B-Q4_K_M.gguf",
                            "product_name": "Qwen3-0.6B-Q4_K_M.gguf",
                            "installed": False,
                            "status": "",
                        },
                    ],
                }
            },
            capabilities={
                "llm.local": {
                    "models": {
                        "storage": "local",
                        "local_files": {
                            "default_root": "models/llama",
                            "glob": "*.gguf",
                        },
                    }
                }
            },
            plugin_model_info={
                "llm.local": {
                    "Qwen/Qwen3-0.6B-GGUF": {
                        "model_name": "Qwen3 0.6B (GGUF)",
                        "file": "Qwen3-0.6B-Q4_K_M.gguf",
                    }
                }
            },
        )

        rows = controller.load_plugin_models_config("llm.local")

        model_ids = [str(item.get("model_id", "")) for item in rows if isinstance(item, dict)]
        self.assertIn("Qwen/Qwen3-0.6B-GGUF", model_ids)
        self.assertNotIn("Qwen3-0.6B-Q4_K_M.gguf", model_ids)


if __name__ == "__main__":
    unittest.main()
