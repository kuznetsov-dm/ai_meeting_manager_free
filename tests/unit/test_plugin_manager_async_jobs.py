import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestPluginManagerAsyncJobs(unittest.TestCase):
    def test_unknown_plugin_defaults_to_isolated_actions(self) -> None:
        from aimn.core.plugin_manager import PluginManager
        from aimn.core.plugins_config import PluginsConfig

        with TemporaryDirectory() as tmp:
            manager = PluginManager(Path(tmp), PluginsConfig({}))
            self.assertTrue(manager.should_isolate_action("service.unknown"))

    def test_async_action_returns_job_and_completes(self) -> None:
        from aimn.core.contracts import ActionDescriptor, ActionResult
        from aimn.core.plugin_manager import PluginManager
        from aimn.core.plugins_config import PluginsConfig

        with TemporaryDirectory() as tmp:
            manager = PluginManager(Path(tmp), PluginsConfig({}))
            action = ActionDescriptor(
                action_id="sync_tasks",
                label="Sync tasks",
                run_mode="async",
                handler=lambda _settings, _params: ActionResult(
                    status="success",
                    message="done",
                    data={"count": 3},
                ),
            )
            manager.actions_for = lambda _pid: [action]  # type: ignore[method-assign]
            manager.get_settings = lambda _pid, include_secrets=False: {}  # type: ignore[method-assign]
            manager.should_isolate_action = lambda _pid: False  # type: ignore[method-assign]

            result = manager.invoke_action("service.dispatcher", "sync_tasks", {})
            self.assertEqual(result.status, "accepted")
            self.assertTrue(result.job_id)
            job_id = str(result.job_id)

            status = None
            for _ in range(40):
                status = manager.get_job_status("service.dispatcher", job_id)
                if status and status.status in {"success", "failed", "cancelled"}:
                    break
                time.sleep(0.02)

            self.assertIsNotNone(status)
            self.assertEqual(status.status, "success")
            self.assertEqual(status.data, {"count": 3})

    def test_cancel_async_action_marks_job_cancelled(self) -> None:
        from aimn.core.contracts import ActionDescriptor, ActionResult
        from aimn.core.plugin_manager import PluginManager
        from aimn.core.plugins_config import PluginsConfig

        with TemporaryDirectory() as tmp:
            manager = PluginManager(Path(tmp), PluginsConfig({}))

            def _slow(_settings, params):
                for _ in range(20):
                    if callable(params.get("_cancel_requested")) and params.get("_cancel_requested")():
                        return ActionResult(status="error", message="cancelled_by_plugin")
                    time.sleep(0.01)
                return ActionResult(status="success", message="done")

            action = ActionDescriptor(
                action_id="sync_slow",
                label="Sync slow",
                run_mode="async",
                handler=_slow,
            )
            manager.actions_for = lambda _pid: [action]  # type: ignore[method-assign]
            manager.get_settings = lambda _pid, include_secrets=False: {}  # type: ignore[method-assign]
            manager.should_isolate_action = lambda _pid: False  # type: ignore[method-assign]

            result = manager.invoke_action("service.dispatcher", "sync_slow", {})
            self.assertEqual(result.status, "accepted")
            job_id = str(result.job_id)
            self.assertTrue(manager.cancel_job("service.dispatcher", job_id))

            status = None
            for _ in range(40):
                status = manager.get_job_status("service.dispatcher", job_id)
                if status and status.status in {"cancelled", "success", "failed"}:
                    break
                time.sleep(0.02)

            self.assertIsNotNone(status)
            self.assertEqual(status.status, "cancelled")

    def test_async_isolated_action_uses_subprocess_runner(self) -> None:
        from aimn.core.contracts import ActionDescriptor, ActionResult
        from aimn.core.plugin_manager import PluginManager
        from aimn.core.plugins_config import PluginsConfig

        with TemporaryDirectory() as tmp:
            manager = PluginManager(Path(tmp), PluginsConfig({}))
            called = {"handler": 0, "subprocess": 0}

            def _handler(_settings, _params):
                called["handler"] += 1
                return ActionResult(status="success", message="in-process")

            action = ActionDescriptor(
                action_id="sync_tasks",
                label="Sync tasks",
                run_mode="async",
                handler=_handler,
            )
            manager.actions_for = lambda _pid: [action]  # type: ignore[method-assign]
            manager.get_settings = lambda _pid, include_secrets=False: {"token": "secret"}  # type: ignore[method-assign]
            manager.should_isolate_action = lambda _pid: True  # type: ignore[method-assign]

            def _fake_subprocess(repo_root, plugin_id, action_id, params, settings_override=None):
                called["subprocess"] += 1
                self.assertEqual(plugin_id, "service.dispatcher")
                self.assertEqual(action_id, "sync_tasks")
                self.assertEqual(settings_override, {"token": "secret"})
                return ActionResult(status="success", message="isolated")

            with patch("aimn.core.plugin_manager.run_action_subprocess", side_effect=_fake_subprocess):
                result = manager.invoke_action("service.dispatcher", "sync_tasks", {})

            self.assertEqual(result.status, "accepted")
            self.assertEqual(result.warnings, [])
            job_id = str(result.job_id)

            status = None
            for _ in range(40):
                status = manager.get_job_status("service.dispatcher", job_id)
                if status and status.status in {"success", "failed", "cancelled"}:
                    break
                time.sleep(0.02)

            self.assertIsNotNone(status)
            self.assertEqual(status.status, "success")
            self.assertEqual(called["handler"], 0)
            self.assertEqual(called["subprocess"], 1)


if __name__ == "__main__":
    unittest.main()
