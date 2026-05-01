# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.management_cleanup_controller import ManagementCleanupController


class _FakeStore:
    def __init__(self, *, policy: dict | None = None, result: dict | None = None) -> None:
        self.policy = dict(policy or {})
        self.result = dict(result or {})
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def prepare_meeting_cleanup(self, meeting_id: str) -> dict:
        self.calls.append(("prepare_meeting_cleanup", {"meeting_id": meeting_id}))
        return dict(self.policy)

    def cleanup_meeting(self, meeting_id: str, *, delete_orphan_entities: bool = False) -> dict:
        self.calls.append(
            (
                "cleanup_meeting",
                {"meeting_id": meeting_id, "delete_orphan_entities": delete_orphan_entities},
            )
        )
        return dict(self.result)

    def prepare_artifact_source_cleanup(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
    ) -> dict:
        self.calls.append(
            (
                "prepare_artifact_source_cleanup",
                {
                    "meeting_id": meeting_id,
                    "source_kind": source_kind,
                    "source_alias": source_alias,
                },
            )
        )
        return dict(self.policy)

    def cleanup_artifact_source(
        self,
        *,
        meeting_id: str,
        source_kind: str,
        source_alias: str,
        delete_orphan_entities: bool = False,
    ) -> dict:
        self.calls.append(
            (
                "cleanup_artifact_source",
                {
                    "meeting_id": meeting_id,
                    "source_kind": source_kind,
                    "source_alias": source_alias,
                    "delete_orphan_entities": delete_orphan_entities,
                },
            )
        )
        return dict(self.result)

    def set_suggestion_state(self, suggestion_id: str, state: str) -> None:
        self.calls.append(
            ("set_suggestion_state", {"suggestion_id": suggestion_id, "state": state})
        )


class TestManagementCleanupController(unittest.TestCase):
    def test_run_meeting_cleanup_shows_empty_info_without_apply(self) -> None:
        stores = [_FakeStore(policy={"has_changes": False})]
        infos: list[tuple[str, str]] = []

        controller = ManagementCleanupController(
            app_root=Path("."),
            parent=None,
            tr=lambda _key, default: default,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs) if kwargs else default,
            store_factory=lambda: stores.pop(0),
            question=lambda *_args, **_kwargs: QMessageBox.Yes,
            information=lambda _parent, title, message: infos.append((title, message)),
        )

        result = controller.run_meeting_cleanup("m1")

        self.assertIsNone(result)
        self.assertEqual(
            infos,
            [
                (
                    "Nothing to clean",
                    "No Management suggestions, meeting mentions, or links were found for the focused meeting.",
                )
            ],
        )

    def test_run_artifact_source_cleanup_hides_seed_suggestion_after_apply(self) -> None:
        preview_store = _FakeStore(
                policy={
                    "has_changes": True,
                    "has_orphans": True,
                    "suggestions": 2,
                    "task_mentions": 1,
                    "project_mentions": 0,
                    "agenda_mentions": 0,
                    "orphan_tasks": 1,
                    "orphan_projects": 0,
                    "orphan_agendas": 0,
                }
            )
        apply_store = _FakeStore(
            result={
                "suggestions": 2,
                "task_mentions": 1,
                "project_mentions": 0,
                "agenda_mentions": 0,
                "deleted_orphan_tasks": 1,
                "deleted_orphan_projects": 0,
                "deleted_orphan_agendas": 0,
            }
        )
        stores = [preview_store, apply_store]
        questions: list[str] = []
        infos: list[tuple[str, str]] = []
        replies = iter((QMessageBox.Yes, QMessageBox.Yes))

        controller = ManagementCleanupController(
            app_root=Path("."),
            parent=None,
            tr=lambda _key, default: default,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs) if kwargs else default,
            store_factory=lambda: stores.pop(0),
            question=lambda _parent, _title, message, _buttons, _default: (
                questions.append(message) or next(replies)
            ),
            information=lambda _parent, title, message: infos.append((title, message)),
        )

        result = controller.run_artifact_source_cleanup(
            meeting_id="m1",
            source_kind="summary",
            source_alias="A12",
            suggestion_id="s7",
        )

        self.assertEqual(result["deleted_orphan_tasks"], 1)
        self.assertIn("Source kind: summary", questions[0])
        self.assertIn("Source alias: A12", questions[0])
        self.assertEqual(
            infos[-1][0],
            "Source cleanup completed",
        )
        self.assertEqual(stores, [])
        self.assertEqual(
            apply_store.calls,
            [
                (
                    "cleanup_artifact_source",
                    {
                        "meeting_id": "m1",
                        "source_kind": "summary",
                        "source_alias": "A12",
                        "delete_orphan_entities": True,
                    },
                ),
                ("set_suggestion_state", {"suggestion_id": "s7", "state": "hidden"}),
            ],
        )

    def test_cleanup_meeting_for_delete_returns_false_on_orphan_prompt_cancel(self) -> None:
        stores = [
            _FakeStore(
                policy={
                    "has_changes": True,
                    "has_orphans": True,
                    "orphan_tasks": 1,
                    "orphan_projects": 0,
                    "orphan_agendas": 0,
                }
            )
        ]

        controller = ManagementCleanupController(
            app_root=Path("."),
            parent=None,
            tr=lambda _key, default: default,
            fmt=lambda _key, default, **kwargs: default.format(**kwargs) if kwargs else default,
            store_factory=lambda: stores.pop(0),
            question=lambda *_args, **_kwargs: QMessageBox.Cancel,
            information=lambda *_args, **_kwargs: None,
        )

        allowed = controller.cleanup_meeting_for_delete("m1")

        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
