import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from plugins.service.task_dispatcher import task_dispatcher as dispatcher_mod  # noqa: E402


class _FakeLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, tuple[object, ...]]] = []

    def info(self, message: str, *args: object) -> None:
        self.messages.append((message, args))

    def exception(self, message: str, *args: object) -> None:
        self.messages.append((message, args))


class _FakeContext:
    def __init__(self) -> None:
        self.logger = _FakeLogger()

    def get_logger(self) -> _FakeLogger:
        return self.logger

    def register_hook_handler(self, *_args, **_kwargs) -> None:
        return None

    def register_actions(self, *_args, **_kwargs) -> None:
        return None

    def get_secret(self, _key: str) -> str:
        return ""


class _FakeStore:
    def __init__(self, tasks: list[dict[str, object]]) -> None:
        self._tasks = list(tasks)
        self.closed = False

    def list_tasks_for_meeting(self, _meeting_id: str) -> list[dict[str, object]]:
        return list(self._tasks)

    def close(self) -> None:
        self.closed = True


class TestTaskDispatcherPlugin(unittest.TestCase):
    def test_sync_action_rejects_removed_notion_target(self) -> None:
        plugin = dispatcher_mod.Plugin()
        plugin.register(_FakeContext())

        result = plugin.handle_sync_action(
            {"target_service": "notion", "notion_token": "x"},
            {"meeting_id": "m1"},
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "target_service_invalid:notion")

    def test_sync_action_exports_tasks_to_trello_only(self) -> None:
        plugin = dispatcher_mod.Plugin()
        plugin.register(_FakeContext())
        store = _FakeStore(tasks=[{"title": "Prepare deck"}, {"title": "Send memo"}])
        original = dispatcher_mod.open_management_store
        dispatcher_mod.open_management_store = lambda _ctx: store
        try:
            result = plugin.handle_sync_action(
                {"target_service": "trello", "trello_token": "secret"},
                {"meeting_id": "m1"},
            )
        finally:
            dispatcher_mod.open_management_store = original

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.message, "tasks_synced:trello")
        self.assertEqual(result.data["synced"], 2)
        self.assertTrue(store.closed)


if __name__ == "__main__":
    unittest.main()
