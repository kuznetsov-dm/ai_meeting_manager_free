# ruff: noqa: E402, I001

import sys
import time
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

from aimn.core.api import PluginHealthQuickFix
from aimn.ui.controllers.plugin_health_interaction_controller import PluginHealthInteractionController
from aimn.ui.controllers.pipeline_runtime_config_controller import PipelineRuntimeConfigController


class _FakeHealthService:
    def __init__(self, *, delay_seconds: float = 0.0) -> None:
        self.check_calls: list[dict] = []
        self._delay_seconds = float(delay_seconds)

    def invoke_quick_fix(self, _plugin_id: str, _quick_fix: PluginHealthQuickFix):
        return True, "ok"

    def check_plugin(self, plugin_id: str, **kwargs):
        if self._delay_seconds > 0:
            time.sleep(self._delay_seconds)
        self.check_calls.append({"plugin_id": plugin_id, **dict(kwargs)})
        return SimpleNamespace(healthy=True, issues=())


class TestPluginHealthInteractionController(unittest.TestCase):
    def _make_controller(
        self,
        *,
        available_plugin_ids: set[str] | None = None,
        delay_seconds: float = 0.0,
    ) -> PluginHealthInteractionController:
        logs: list[tuple[str, str]] = []
        self._logs = logs
        self._progress: list[dict[str, object]] = []
        available = set(available_plugin_ids or set())
        self._health_service = _FakeHealthService(delay_seconds=delay_seconds)
        return PluginHealthInteractionController(
            parent=None,
            stage_order=["media_convert", "transcription", "llm_processing", "management", "service"],
            stage_display_name=lambda stage_id: stage_id,
            plugin_display_name=lambda plugin_id: plugin_id,
            plugin_available=lambda plugin_id: plugin_id in available if available else True,
            plugin_capabilities=lambda _pid: {},
            health_service=self._health_service,
            log_message=lambda message, stage_id="ui": logs.append((stage_id, message)),
            open_stage_settings=lambda _stage_id: None,
            apply_skip_once=lambda _runtime, _check: None,
            apply_disable_preset=lambda _check: None,
            offline_mode=lambda: False,
            report_progress=lambda payload: self._progress.append(dict(payload or {})),
        )

    def test_health_checks_for_runtime_respects_start_stage_and_variants(self) -> None:
        controller = self._make_controller()
        runtime = {
            "pipeline": {"disabled_stages": ["management"]},
            "stages": {
                "transcription": {"plugin_id": "transcription.mock"},
                "llm_processing": {
                    "variants": [
                        {"plugin_id": "llm.a", "params": {"model_id": "a"}},
                        {"plugin_id": "llm.b", "params": {"model_id": "b"}},
                    ]
                },
                "management": {"plugin_id": "management.unified"},
                "service": {"plugin_id": "service.management_index"},
            },
        }

        checks = controller.health_checks_for_runtime(runtime, force_run_from="transcription")
        ids = [(str(c.get("stage_id", "")), str(c.get("plugin_id", ""))) for c in checks]
        self.assertIn(("transcription", "transcription.mock"), ids)
        self.assertIn(("llm_processing", "llm.a"), ids)
        self.assertIn(("llm_processing", "llm.b"), ids)
        self.assertNotIn(("management", "management.unified"), ids)
        self.assertIn(("service", "service.management_index"), ids)

    def test_health_checks_for_runtime_skips_unavailable_plugins(self) -> None:
        controller = self._make_controller(available_plugin_ids={"transcription.mock", "service.management_index"})
        runtime = {
            "stages": {
                "transcription": {"plugin_id": "transcription.mock"},
                "llm_processing": {
                    "plugin_id": "llm.missing",
                    "variants": [
                        {"plugin_id": "llm.a", "params": {"model_id": "a"}},
                        {"plugin_id": "llm.b", "params": {"model_id": "b"}},
                    ],
                },
                "service": {"plugin_id": "service.management_index"},
            },
        }

        checks = controller.health_checks_for_runtime(runtime)
        ids = {(str(c.get("stage_id", "")), str(c.get("plugin_id", ""))) for c in checks}
        self.assertIn(("transcription", "transcription.mock"), ids)
        self.assertIn(("service", "service.management_index"), ids)
        self.assertNotIn(("llm_processing", "llm.missing"), ids)
        self.assertNotIn(("llm_processing", "llm.a"), ids)
        self.assertNotIn(("llm_processing", "llm.b"), ids)

    def test_stage_params_for_plugin_reads_variants_and_params(self) -> None:
        config = {
            "stages": {
                "llm_processing": {
                    "plugin_id": "llm.main",
                    "params": {"model_id": "default"},
                    "variants": [
                        {"plugin_id": "llm.a", "params": {"model_id": "a"}},
                        {"plugin_id": "llm.b", "params": {"model_id": "b"}},
                    ],
                }
            }
        }
        params_a = PluginHealthInteractionController.stage_params_for_plugin(config, "llm_processing", "llm.a")
        params_main = PluginHealthInteractionController.stage_params_for_plugin(
            config, "llm_processing", "llm.main"
        )
        self.assertEqual(params_a.get("model_id"), "a")
        self.assertEqual(params_main.get("model_id"), "default")

    def test_health_issues_text_formats_errors_only(self) -> None:
        issues = (
            SimpleNamespace(severity="error", summary="A", detail="d1", hint="h1"),
            SimpleNamespace(severity="warning", summary="B", detail="", hint=""),
            SimpleNamespace(severity="error", summary="C", detail="", hint="h2"),
        )
        text = PluginHealthInteractionController.health_issues_text(issues)
        self.assertIn("- A", text)
        self.assertIn("detail: d1", text)
        self.assertIn("hint: h2", text)
        self.assertNotIn("- B", text)

    def test_run_plugin_quick_fix_logs_success(self) -> None:
        controller = self._make_controller()
        fix = PluginHealthQuickFix(action_id="start_server", label="Start server", payload={})
        controller.run_plugin_quick_fix("llm.ollama", fix)
        self.assertTrue(self._logs)
        self.assertIn("quick-fix ok", self._logs[-1][1])

    def test_preflight_uses_strict_live_health_check_options(self) -> None:
        controller = self._make_controller()
        runtime = {
            "stages": {
                "transcription": {"plugin_id": "transcription.mock", "params": {"model_id": "small"}},
            },
        }

        proceed, _updated = controller.preflight_plugin_health_checks(runtime)

        self.assertTrue(proceed)
        self.assertTrue(self._health_service.check_calls)
        call = self._health_service.check_calls[0]
        self.assertEqual(call["plugin_id"], "transcription.mock")
        self.assertTrue(bool(call.get("full_check")))
        self.assertTrue(bool(call.get("force")))
        self.assertEqual(call.get("max_age_seconds"), 30.0)
        self.assertFalse(bool(call.get("allow_stale_on_error", True)))

    def test_check_still_present_uses_plugin_and_params_after_variant_shift(self) -> None:
        runtime = {
            "stages": {
                "llm_processing": {
                    "variants": [
                        {"plugin_id": "llm.a", "params": {"model_id": "a"}},
                        {"plugin_id": "llm.b", "params": {"model_id": "b"}},
                    ]
                }
            },
            "pipeline": {"disabled_stages": []},
        }
        check_a = {"stage_id": "llm_processing", "plugin_id": "llm.a", "params": {"model_id": "a"}, "variant_index": 0}
        check_b = {"stage_id": "llm_processing", "plugin_id": "llm.b", "params": {"model_id": "b"}, "variant_index": 1}
        PipelineRuntimeConfigController.apply_skip_once(runtime, check_a)

        self.assertFalse(PluginHealthInteractionController._check_still_present(runtime, check_a))
        self.assertTrue(PluginHealthInteractionController._check_still_present(runtime, check_b))

    def test_preflight_reports_progress(self) -> None:
        controller = self._make_controller()
        runtime = {
            "stages": {
                "transcription": {"plugin_id": "transcription.mock"},
                "llm_processing": {"plugin_id": "llm.a"},
            },
        }

        proceed, _updated = controller.preflight_plugin_health_checks(runtime)

        self.assertTrue(proceed)
        self.assertTrue(self._progress)
        self.assertEqual(str(self._progress[0].get("state", "")), "running")
        self.assertEqual(str(self._progress[-1].get("state", "")), "finished")
        self.assertEqual(int(self._progress[-1].get("total", 0)), 2)

    def test_preflight_progress_contains_elapsed_seconds_while_check_runs(self) -> None:
        controller = self._make_controller(delay_seconds=0.35)
        runtime = {
            "stages": {
                "transcription": {"plugin_id": "transcription.mock"},
            },
        }

        proceed, _updated = controller.preflight_plugin_health_checks(runtime)

        self.assertTrue(proceed)
        running_payloads = [item for item in self._progress if str(item.get("state", "")) == "running"]
        self.assertTrue(any("elapsed_seconds" in item for item in running_payloads))


if __name__ == "__main__":
    unittest.main()
