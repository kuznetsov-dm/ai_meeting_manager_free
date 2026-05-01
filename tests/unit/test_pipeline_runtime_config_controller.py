# ruff: noqa: E402, I001

import sys
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

from aimn.ui.controllers.pipeline_runtime_config_controller import PipelineRuntimeConfigController


class TestPipelineRuntimeConfigController(unittest.TestCase):
    def test_restore_required_stage_plugins_recovers_management_and_service(self) -> None:
        config = {"stages": {}}

        defaults = {
            "management": SimpleNamespace(plugin_id="management.active"),
            "service": SimpleNamespace(
                plugin_id="service.active",
                module="plugins.service.active",
                class_name="Plugin",
            ),
        }

        changed = PipelineRuntimeConfigController.restore_required_stage_plugins(
            config,
            default_plugin_for_stage=lambda stage_id: defaults.get(stage_id),
        )

        self.assertTrue(changed)
        self.assertEqual(config["stages"]["management"]["plugin_ids"], ["management.active"])
        self.assertEqual(config["stages"]["management"]["params"], {})
        self.assertEqual(config["stages"]["service"]["plugin_id"], "service.active")
        self.assertEqual(config["stages"]["service"]["module"], "plugins.service.active")
        self.assertEqual(config["stages"]["service"]["class"], "Plugin")
        self.assertEqual(config["stages"]["service"]["params"], {})

    def test_restore_required_stage_plugins_does_not_override_existing_assignments(self) -> None:
        config = {
            "stages": {
                "management": {"plugin_ids": ["management.custom"], "params": {"keep": True}},
                "service": {
                    "plugin_id": "service.custom",
                    "module": "plugins.service.custom",
                    "class": "CustomPlugin",
                    "params": {"keep": True},
                },
            }
        }

        changed = PipelineRuntimeConfigController.restore_required_stage_plugins(
            config,
            default_plugin_for_stage=lambda stage_id: SimpleNamespace(
                plugin_id=f"{stage_id}.default",
                module=f"plugins.{stage_id}.default",
                class_name="Plugin",
            ),
        )

        self.assertFalse(changed)
        self.assertEqual(config["stages"]["management"]["plugin_ids"], ["management.custom"])
        self.assertEqual(config["stages"]["service"]["plugin_id"], "service.custom")

    def test_prune_unavailable_plugins_removes_plugin_ids_and_variants(self) -> None:
        config = {
            "stages": {
                "transcription": {
                    "plugin_id": "transcription.old",
                    "module": "legacy.module",
                    "class": "LegacyClass",
                    "variants": [
                        {"plugin_id": "transcription.ok", "params": {"model_id": "small"}},
                        {"plugin_id": "transcription.gone", "params": {"model_id": "base"}},
                    ],
                },
                "llm_processing": {
                    "plugin_id": "llm.gone",
                    "variants": [
                        {"plugin_id": "llm.ok", "params": {"model_id": "m1"}},
                        {"plugin_id": "llm.gone2", "params": {"model_id": "m2"}},
                    ],
                },
                "management": {
                    "plugin_ids": ["management.ok", "management.gone", ""],
                },
            }
        }

        changed = PipelineRuntimeConfigController.prune_unavailable_plugins(
            config,
            plugin_available=lambda pid: pid in {"transcription.ok", "llm.ok", "management.ok"},
        )

        self.assertTrue(changed)
        transcription = config["stages"]["transcription"]
        self.assertEqual(transcription.get("plugin_id"), "transcription.ok")
        self.assertNotIn("module", transcription)
        self.assertNotIn("class", transcription)
        self.assertEqual(len(transcription.get("variants", [])), 1)
        self.assertEqual(transcription["variants"][0].get("plugin_id"), "transcription.ok")
        llm = config["stages"]["llm_processing"]
        self.assertNotIn("plugin_id", llm)
        self.assertEqual(len(llm.get("variants", [])), 1)
        self.assertEqual(llm["variants"][0].get("plugin_id"), "llm.ok")
        management = config["stages"]["management"]
        self.assertEqual(management.get("plugin_ids"), ["management.ok"])

    def test_prune_unavailable_plugins_returns_false_when_nothing_changes(self) -> None:
        config = {
            "stages": {
                "service": {"plugin_id": "service.ok"},
                "llm_processing": {"variants": [{"plugin_id": "llm.ok", "params": {}}]},
                "management": {"plugin_ids": ["management.ok"]},
            }
        }

        changed = PipelineRuntimeConfigController.prune_unavailable_plugins(
            config,
            plugin_available=lambda pid: pid in {"service.ok", "llm.ok", "management.ok"},
        )

        self.assertFalse(changed)

    def test_prune_unavailable_plugins_removes_empty_plugin_ids_list(self) -> None:
        config = {
            "stages": {
                "management": {
                    "plugin_ids": ["management.gone"],
                }
            }
        }

        changed = PipelineRuntimeConfigController.prune_unavailable_plugins(
            config,
            plugin_available=lambda _pid: False,
        )

        self.assertTrue(changed)
        management = config["stages"]["management"]
        self.assertNotIn("plugin_ids", management)

    def test_build_runtime_config_sets_preset_and_sanitizes(self) -> None:
        config = {
            "stages": {
                "llm_processing": {
                    "plugin_id": "llm.one",
                    "params": {"a": 1},
                    "variants": [{"plugin_id": "llm.two", "params": {"b": 2}}],
                },
                "management": {
                    "plugin_id": "management.unified",
                    "params": {"prompt_agenda_id": "agenda-1"},
                }
            }
        }

        payload = PipelineRuntimeConfigController.build_runtime_config(
            config,
            pipeline_preset="offline",
            sanitize_params_for_plugin=lambda plugin_id, params: {"pid": plugin_id, **dict(params)},
        )

        self.assertEqual(payload.get("pipeline", {}).get("preset"), "offline")
        stage = payload["stages"]["llm_processing"]
        self.assertEqual(stage["params"].get("pid"), "llm.one")
        self.assertEqual(stage["variants"][0]["params"].get("pid"), "llm.two")
        management = payload["stages"]["management"]
        self.assertEqual(management["params"].get("prompt_agenda_id"), "agenda-1")

    def test_build_runtime_config_drops_unavailable_local_model_variants(self) -> None:
        config = {
            "stages": {
                "llm_processing": {
                    "variants": [
                        {"plugin_id": "llm.local", "params": {"model_id": "ok"}},
                        {"plugin_id": "llm.local", "params": {"model_id": "missing"}},
                    ]
                }
            }
        }

        payload = PipelineRuntimeConfigController.build_runtime_config(
            config,
            pipeline_preset="offline",
            sanitize_params_for_plugin=lambda _plugin_id, params: dict(params),
            model_available_for_plugin=lambda _plugin_id, params: str(params.get("model_id", "")) != "missing",
        )
        variants = payload["stages"]["llm_processing"].get("variants", [])
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["params"].get("model_id"), "ok")

    def test_build_runtime_config_sanitizes_variants_independently_for_same_provider(self) -> None:
        config = {
            "stages": {
                "llm_processing": {
                    "variants": [
                        {"plugin_id": "llm.local", "params": {"model_id": "one"}},
                        {"plugin_id": "llm.local", "params": {"model_id": "two"}},
                    ]
                }
            }
        }

        payload = PipelineRuntimeConfigController.build_runtime_config(
            config,
            pipeline_preset="offline",
            sanitize_params_for_plugin=lambda pid, params: {"plugin": pid, **dict(params)},
        )

        self.assertEqual(
            payload["stages"]["llm_processing"]["variants"],
            [
                {"plugin_id": "llm.local", "params": {"plugin": "llm.local", "model_id": "one"}},
                {"plugin_id": "llm.local", "params": {"plugin": "llm.local", "model_id": "two"}},
            ],
        )

    def test_build_runtime_config_keeps_transcription_plugin_when_local_model_missing(self) -> None:
        config = {
            "stages": {
                "transcription": {
                    "plugin_id": "transcription.local",
                    "params": {"model": "missing"},
                }
            }
        }

        payload = PipelineRuntimeConfigController.build_runtime_config(
            config,
            pipeline_preset="offline",
            sanitize_params_for_plugin=lambda _plugin_id, params: dict(params),
            model_available_for_plugin=lambda _plugin_id, params: str(
                params.get("model", "") or params.get("model_id", "")
            )
            != "missing",
        )
        stage = payload["stages"]["transcription"]
        self.assertEqual(stage.get("plugin_id"), "transcription.local")

    def test_build_runtime_config_recomputes_llm_prompt_signature(self) -> None:
        config = {
            "stages": {
                "llm_processing": {
                    "params": {
                        "prompt_profile": "standard",
                        "prompt_custom": "",
                        "prompt_signature": "stale",
                    },
                    "variants": [{"plugin_id": "llm.openrouter", "params": {"model_id": "m1"}}],
                }
            }
        }

        payload = PipelineRuntimeConfigController.build_runtime_config(
            config,
            pipeline_preset="offline",
            sanitize_params_for_plugin=lambda _plugin_id, params: dict(params),
            compute_llm_prompt_signature=lambda profile, custom: f"recomputed:{profile}:{len(custom)}",
        )
        params = payload["stages"]["llm_processing"]["params"]
        self.assertEqual(params.get("prompt_signature"), "recomputed:standard:0")

    def test_apply_skip_once_drops_variant_and_disables_when_needed(self) -> None:
        runtime = {
            "stages": {
                "llm_processing": {
                    "variants": [
                        {"plugin_id": "a", "params": {}},
                        {"plugin_id": "b", "params": {}},
                    ]
                }
            },
            "pipeline": {"disabled_stages": []},
        }
        PipelineRuntimeConfigController.apply_skip_once(
            runtime,
            {"stage_id": "llm_processing", "plugin_id": "a", "variant_index": 0},
        )
        self.assertEqual(len(runtime["stages"]["llm_processing"]["variants"]), 1)

        runtime2 = {"stages": {"llm_processing": {"variants": [{"plugin_id": "a", "params": {}}]}}, "pipeline": {}}
        PipelineRuntimeConfigController.apply_skip_once(
            runtime2,
            {"stage_id": "llm_processing", "plugin_id": "a"},
        )
        self.assertIn("llm_processing", runtime2["pipeline"]["disabled_stages"])

    def test_apply_skip_once_removes_matching_variant_when_indexes_shift(self) -> None:
        runtime = {
            "stages": {
                "llm_processing": {
                    "variants": [
                        {"plugin_id": "a", "params": {"model_id": "a"}},
                        {"plugin_id": "b", "params": {"model_id": "b"}},
                        {"plugin_id": "c", "params": {"model_id": "c"}},
                    ]
                }
            },
            "pipeline": {"disabled_stages": []},
        }
        PipelineRuntimeConfigController.apply_skip_once(
            runtime,
            {
                "stage_id": "llm_processing",
                "plugin_id": "a",
                "params": {"model_id": "a"},
                "variant_index": 0,
            },
        )
        PipelineRuntimeConfigController.apply_skip_once(
            runtime,
            {
                "stage_id": "llm_processing",
                "plugin_id": "b",
                "params": {"model_id": "b"},
                "variant_index": 1,
            },
        )
        variants = runtime["stages"]["llm_processing"]["variants"]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["plugin_id"], "c")

    def test_apply_disable_preset_filters_or_disables(self) -> None:
        config = {"stages": {"llm_processing": {"variants": [{"plugin_id": "a"}, {"plugin_id": "b"}]}}}
        stage_id = PipelineRuntimeConfigController.apply_disable_preset(
            config,
            {"stage_id": "llm_processing", "plugin_id": "a"},
        )
        self.assertEqual(stage_id, "llm_processing")
        self.assertEqual(len(config["stages"]["llm_processing"]["variants"]), 1)

        config2 = {"stages": {"llm_processing": {"variants": [{"plugin_id": "a"}]}}, "pipeline": {}}
        stage_id2 = PipelineRuntimeConfigController.apply_disable_preset(
            config2,
            {"stage_id": "llm_processing", "plugin_id": "a"},
        )
        self.assertEqual(stage_id2, "llm_processing")
        self.assertIn("llm_processing", config2["pipeline"]["disabled_stages"])


if __name__ == "__main__":
    unittest.main()
