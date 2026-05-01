# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.stage_action_flow_controller import (  # noqa: E402
    StageActionFlowController,
)


class TestStageActionFlowController(unittest.TestCase):
    def test_resolve_request_handles_refresh_models_only(self) -> None:
        refresh = StageActionFlowController.resolve_request(
            "llm_processing",
            {"type": "refresh_models", "provider_id": "llm.demo"},
        )
        self.assertIsNotNone(refresh)
        assert refresh is not None
        self.assertEqual((refresh.action, refresh.provider_id), ("refresh_models", "llm.demo"))

        self.assertIsNone(
            StageActionFlowController.resolve_request(
                "llm_processing",
                {"type": "plugin_health_check"},
            )
        )

    def test_refresh_provider_models_returns_success_outcome(self) -> None:
        invalidated: list[str] = []
        outcome = StageActionFlowController.refresh_provider_models(
            "llm_processing",
            "llm.demo",
            invalidate_provider_cache=lambda pid: invalidated.append(pid),
            refresh_models_from_provider=lambda _pid: (True, "ok"),
            is_settings_open_for_stage=lambda stage_id: stage_id == "llm_processing",
            tr=lambda _key, default: default,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
            log_failure=lambda _sid, _pid, _exc: None,
        )

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.level, "info")
        self.assertEqual(outcome.title, "Available models refreshed")
        self.assertIn("llm.demo", outcome.message)
        self.assertIn("Updated available models", outcome.message)
        self.assertTrue(outcome.rerender_drawer)
        self.assertTrue(outcome.refresh_pipeline_ui)
        self.assertEqual(invalidated, ["llm.demo"])

    def test_refresh_provider_models_returns_warning_outcome_on_failure(self) -> None:
        failures: list[tuple[str, str, str]] = []
        outcome = StageActionFlowController.refresh_provider_models(
            "llm_processing",
            "llm.demo",
            invalidate_provider_cache=lambda _pid: None,
            refresh_models_from_provider=lambda _pid: (False, "provider_failed"),
            is_settings_open_for_stage=lambda _stage_id: False,
            tr=lambda _key, default: default,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
            log_failure=lambda sid, pid, exc: failures.append((sid, pid, str(exc))),
        )

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertTrue(outcome.handled)
        self.assertEqual(outcome.level, "warning")
        self.assertEqual(outcome.title, "Available model refresh failed")
        self.assertIn("provider_failed", outcome.message)
        self.assertFalse(outcome.rerender_drawer)
        self.assertTrue(outcome.refresh_pipeline_ui)
        self.assertEqual(failures, [("llm_processing", "llm.demo", "provider_failed")])


if __name__ == "__main__":
    unittest.main()
