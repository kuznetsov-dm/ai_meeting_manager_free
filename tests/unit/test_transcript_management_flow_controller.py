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

from aimn.ui.controllers.transcript_management_flow_controller import (
    TranscriptManagementFlowController,
)


class _StoreStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | str]] = []
        self.closed = False

    def create_task(self, **kwargs) -> None:
        self.calls.append(("create_task", dict(kwargs)))

    def create_project(self, **kwargs) -> None:
        self.calls.append(("create_project", dict(kwargs)))

    def create_agenda(self, **kwargs) -> None:
        self.calls.append(("create_agenda", dict(kwargs)))

    def approve_suggestion(self, suggestion_id: str) -> None:
        self.calls.append(("approve_suggestion", str(suggestion_id)))

    def set_suggestion_state(self, suggestion_id: str, *, state: str) -> None:
        self.calls.append(("set_suggestion_state", {"id": str(suggestion_id), "state": str(state)}))

    def close(self) -> None:
        self.closed = True


class _StoreFactory:
    def __init__(self) -> None:
        self.instances: list[_StoreStub] = []

    def __call__(self) -> _StoreStub:
        store = _StoreStub()
        self.instances.append(store)
        return store


class TestTranscriptManagementFlowController(unittest.TestCase):
    def _controller(self, factory: _StoreFactory) -> TranscriptManagementFlowController:
        return TranscriptManagementFlowController(
            store_factory=factory,
            tr=lambda _key, default: default,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

    def test_suggest_title_uses_first_non_empty_line_and_trims(self) -> None:
        self.assertEqual(
            TranscriptManagementFlowController.suggest_title("  \n- Prepare launch memo by Friday  \nextra"),
            "Prepare launch memo by Friday",
        )

    def test_run_create_request_warns_when_no_meeting_open(self) -> None:
        factory = _StoreFactory()
        controller = self._controller(factory)

        outcome = controller.run_create_request(
            entity_type="task",
            payload={"selected_text": "Prepare launch memo"},
            meeting_id="",
            prompt_text=lambda _title, _prompt, _default: ("Ignored", True),
        )

        self.assertFalse(outcome.created)
        self.assertIn("Open a meeting", outcome.warning_message)
        self.assertEqual(factory.instances, [])

    def test_run_create_request_creates_task_and_formats_log_message(self) -> None:
        factory = _StoreFactory()
        controller = self._controller(factory)

        outcome = controller.run_create_request(
            entity_type="task",
            payload={
                "stage_id": "transcription",
                "kind": "transcript",
                "alias": "T05",
                "selected_text": "Prepare launch memo by Friday",
                "evidence": {"start_ms": 1000, "end_ms": 2200},
            },
            meeting_id="meeting-1",
            prompt_text=lambda _title, _prompt, default: (default, True),
        )

        self.assertTrue(outcome.created)
        self.assertTrue(outcome.refresh_suggestions)
        self.assertIn("Created task from transcript", outcome.log_message)
        self.assertIn("alias=T05", outcome.log_message)
        self.assertIn("1000-2200ms", outcome.log_message)
        self.assertEqual(len(factory.instances), 1)
        self.assertEqual(factory.instances[0].calls[0][0], "create_task")
        self.assertTrue(factory.instances[0].closed)

    def test_run_suggestion_action_approves_and_refreshes(self) -> None:
        factory = _StoreFactory()
        controller = self._controller(factory)

        outcome = controller.run_suggestion_action(
            action="approve",
            payload={"suggestion_id": "s-1"},
            meeting_id="meeting-1",
            prompt_text=lambda _title, _prompt, _default: ("Ignored", True),
        )

        self.assertTrue(outcome.handled)
        self.assertTrue(outcome.refresh_suggestions)
        self.assertEqual(factory.instances[0].calls, [("approve_suggestion", "s-1")])
        self.assertTrue(factory.instances[0].closed)

    def test_run_suggestion_action_create_task_hides_suggestion_after_create(self) -> None:
        factory = _StoreFactory()
        controller = self._controller(factory)

        outcome = controller.run_suggestion_action(
            action="create_task",
            payload={
                "suggestion_id": "s-1",
                "stage_id": "transcription",
                "kind": "transcript",
                "alias": "T05",
                "selected_text": "Prepare launch memo by Friday",
                "evidence": {"start_ms": 1000, "end_ms": 2200},
            },
            meeting_id="meeting-1",
            prompt_text=lambda _title, _prompt, default: (default, True),
        )

        self.assertTrue(outcome.handled)
        self.assertIsNotNone(outcome.create_outcome)
        assert outcome.create_outcome is not None
        self.assertTrue(outcome.create_outcome.created)
        self.assertTrue(outcome.refresh_suggestions)
        self.assertEqual(factory.instances[0].calls[0][0], "create_task")
        self.assertEqual(
            factory.instances[1].calls,
            [("set_suggestion_state", {"id": "s-1", "state": "hidden"})],
        )
        self.assertTrue(factory.instances[0].closed)
        self.assertTrue(factory.instances[1].closed)


if __name__ == "__main__":
    unittest.main()
