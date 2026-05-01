import sys
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QObject, Signal


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers import pipeline_run_controller as controller_module  # noqa: E402


class _FakeWorker(QObject):
    log = Signal(str)
    stage_status = Signal(str, str, int, str, str, int, str)
    pipeline_event = Signal(object)
    file_started = Signal(str, str)
    file_completed = Signal(str, str)
    file_failed = Signal(str, str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, app_root: Path) -> None:
        super().__init__()
        self.app_root = Path(app_root)


class _FakeThread(QObject):
    finished = Signal()
    instances: list["_FakeThread"] = []

    def __init__(
        self,
        worker: _FakeWorker,
        files: list[str],
        config_data: dict[str, object],
        *,
        force_run: bool = False,
        force_run_from: str | None = None,
    ) -> None:
        super().__init__()
        self.worker = worker
        self.files = list(files)
        self.config_data = dict(config_data)
        self.force_run = bool(force_run)
        self.force_run_from = force_run_from
        self.running = False
        self.start_calls = 0
        self.cancel_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.wait_calls = 0
        self.__class__.instances.append(self)

    def isRunning(self) -> bool:
        return bool(self.running)

    def start(self) -> None:
        self.start_calls += 1
        self.running = True

    def request_cancel(self) -> None:
        self.cancel_calls += 1

    def request_pause(self) -> None:
        self.pause_calls += 1

    def request_resume(self) -> None:
        self.resume_calls += 1

    def wait(self) -> None:
        self.wait_calls += 1
        self.running = False
        self.finished.emit()


class TestPipelineRunController(unittest.TestCase):
    def setUp(self) -> None:
        _FakeThread.instances.clear()

    def test_start_blocks_parallel_run_but_allows_restart_after_thread_finishes(self) -> None:
        with (
            mock.patch.object(controller_module, "PipelineWorker", _FakeWorker),
            mock.patch.object(controller_module, "PipelineThread", _FakeThread),
        ):
            controller = controller_module.PipelineRunController(Path(repo_root))

            started = controller.start(
                files=["first.wav"],
                config_data={"stages": {}},
                force_run=False,
                force_run_from=None,
            )
            self.assertTrue(started)
            self.assertEqual(len(_FakeThread.instances), 1)
            first_thread = _FakeThread.instances[0]
            self.assertEqual(first_thread.files, ["first.wav"])
            self.assertFalse(first_thread.force_run)
            self.assertIsNone(first_thread.force_run_from)

            blocked = controller.start(
                files=["second.wav"],
                config_data={"stages": {"llm_processing": {}}},
                force_run=True,
                force_run_from="llm_processing",
            )
            self.assertFalse(blocked)
            self.assertEqual(len(_FakeThread.instances), 1)

            first_thread.running = False
            restarted = controller.start(
                files=["second.wav"],
                config_data={"stages": {"llm_processing": {}}},
                force_run=True,
                force_run_from="llm_processing",
            )
            self.assertTrue(restarted)
            self.assertEqual(len(_FakeThread.instances), 2)
            second_thread = _FakeThread.instances[1]
            self.assertEqual(second_thread.files, ["second.wav"])
            self.assertTrue(second_thread.force_run)
            self.assertEqual(second_thread.force_run_from, "llm_processing")

    def test_pause_cancel_and_shutdown_are_forwarded_only_while_running(self) -> None:
        with (
            mock.patch.object(controller_module, "PipelineWorker", _FakeWorker),
            mock.patch.object(controller_module, "PipelineThread", _FakeThread),
        ):
            controller = controller_module.PipelineRunController(Path(repo_root))

            controller.request_pause(True)
            controller.request_pause(False)
            controller.request_cancel()
            controller.shutdown()

            controller.start(
                files=["demo.wav"],
                config_data={"stages": {}},
                force_run=False,
                force_run_from=None,
            )
            thread = _FakeThread.instances[0]

            controller.request_pause(True)
            controller.request_pause(False)
            controller.request_cancel()
            controller.shutdown()

            self.assertEqual(thread.pause_calls, 1)
            self.assertEqual(thread.resume_calls, 1)
            self.assertEqual(thread.cancel_calls, 2)
            self.assertEqual(thread.wait_calls, 1)

    def test_terminal_signals_are_flushed_after_thread_finish(self) -> None:
        finished_payloads: list[str] = []
        failed_payloads: list[str] = []

        with (
            mock.patch.object(controller_module, "PipelineWorker", _FakeWorker),
            mock.patch.object(controller_module, "PipelineThread", _FakeThread),
        ):
            controller = controller_module.PipelineRunController(Path(repo_root))
            controller.finished.connect(finished_payloads.append)
            controller.failed.connect(failed_payloads.append)

            controller.start(
                files=["demo.wav"],
                config_data={"stages": {}},
                force_run=False,
                force_run_from=None,
            )
            thread = _FakeThread.instances[0]

            controller._worker.failed.emit("boom")
            controller._worker.finished.emit("meeting-base")

            self.assertEqual(finished_payloads, [])
            self.assertEqual(failed_payloads, [])
            self.assertTrue(controller.is_running())

            thread.running = False
            thread.finished.emit()

            self.assertEqual(failed_payloads, ["boom"])
            self.assertEqual(finished_payloads, ["meeting-base"])
            self.assertFalse(controller.is_running())


if __name__ == "__main__":
    unittest.main()
