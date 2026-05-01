# ruff: noqa: E402

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

from aimn.ui.controllers.meeting_export_controller import MeetingExportController


class _ActionServiceStub:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str, dict]] = []

    def invoke_action(self, plugin_id: str, action_id: str, payload: dict):
        self.calls.append((plugin_id, action_id, dict(payload)))
        if self.error is not None:
            raise self.error
        return self.result


class TestMeetingExportController(unittest.TestCase):
    def _controller(self, *, action_service, meeting_service) -> MeetingExportController:
        return MeetingExportController(
            action_service=action_service,
            meeting_service=meeting_service,
            plugin_display_name=lambda pid: f"Plugin<{pid}>",
            plugin_capabilities=lambda _pid: {"artifact_export": {"manual_text_max_chars": 5}},
            tr=lambda _key, default: default,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

    def test_resolve_export_identifiers_prefers_loaded_meeting_data(self) -> None:
        controller = self._controller(
            action_service=_ActionServiceStub(),
            meeting_service=SimpleNamespace(
                load_by_base_name=lambda _base: SimpleNamespace(
                    meeting_id="250305-1010_demo",
                    base_name="250305-1010_demo",
                )
            ),
        )

        base, meeting_id = controller.resolve_export_identifiers(
            base="250305-1010_demo",
            meeting_key="250305-1010_demo",
        )

        self.assertEqual(base, "250305-1010_demo")
        self.assertEqual(meeting_id, "250305-1010_demo")

    def test_resolve_export_identifiers_falls_back_to_meeting_key(self) -> None:
        controller = self._controller(
            action_service=_ActionServiceStub(),
            meeting_service=SimpleNamespace(load_by_base_name=lambda _base: None),
        )

        base, meeting_id = controller.resolve_export_identifiers(
            base="250305-1010_demo",
            meeting_key="250305-1010_demo",
        )

        self.assertEqual(base, "250305-1010_demo")
        self.assertEqual(meeting_id, "250305-1010_demo")

    def test_manual_export_text_limit_reads_capabilities(self) -> None:
        controller = self._controller(
            action_service=_ActionServiceStub(),
            meeting_service=SimpleNamespace(load_by_base_name=lambda _base: None),
        )

        self.assertEqual(controller.manual_export_text_limit("integration.demo"), 5)

    def test_export_error_text_returns_raw_message(self) -> None:
        self.assertEqual(
            MeetingExportController.export_error_text("provider_failed_401:token invalid"),
            "provider_failed_401:token invalid",
        )

    def test_manual_export_returns_success_dialog_and_trims_text(self) -> None:
        action_service = _ActionServiceStub(result=SimpleNamespace(status="ok", message="sent"))
        controller = self._controller(
            action_service=action_service,
            meeting_service=SimpleNamespace(load_by_base_name=lambda _base: None),
        )

        outcome = controller.run_manual_artifact_export(
            plugin_id="integration.demo",
            action_id="export_text",
            stage_id="llm_processing",
            alias="a1",
            artifact_kind="summary",
            text="0123456789",
            active_meeting_base_name="meeting-base",
            active_meeting_id="meeting-id",
        )

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.level, "info")
        self.assertIn("sent truncated text, 5 chars", outcome.message)
        self.assertTrue(action_service.calls)
        payload = action_service.calls[0][2]
        self.assertIn("[truncated by UI]", payload["text"])

    def test_meeting_export_returns_warning_on_action_error(self) -> None:
        controller = self._controller(
            action_service=_ActionServiceStub(error=RuntimeError("boom")),
            meeting_service=SimpleNamespace(load_by_base_name=lambda _base: None),
        )

        outcome = controller.run_meeting_export(
            plugin_id="integration.demo",
            action_id="export_meeting",
            base_name="meeting-base",
            meeting_key="meeting-base",
            mode="full",
        )

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.level, "warning")
        self.assertIn("Plugin<integration.demo>: boom", outcome.message)


if __name__ == "__main__":
    unittest.main()
