from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from aimn.ui.pipeline_worker import PipelineThread, PipelineWorker


class PipelineRunController(QObject):
    log = Signal(str)
    stageStatus = Signal(str, str, int, str, str, int, str)
    pipelineEvent = Signal(object)
    fileStarted = Signal(str, str)
    fileCompleted = Signal(str, str)
    fileFailed = Signal(str, str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, app_root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker = PipelineWorker(Path(app_root))
        self._thread: PipelineThread | None = None
        self._pending_terminal_events: list[tuple[str, str]] = []
        self._worker.log.connect(lambda message: self.log.emit(str(message)))
        self._worker.stage_status.connect(self.stageStatus.emit)
        self._worker.pipeline_event.connect(self.pipelineEvent.emit)
        self._worker.file_started.connect(self.fileStarted.emit)
        self._worker.file_completed.connect(self.fileCompleted.emit)
        self._worker.file_failed.connect(self.fileFailed.emit)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.isRunning())

    def start(
        self,
        *,
        files: list[str],
        config_data: dict[str, object],
        force_run: bool,
        force_run_from: str | None,
    ) -> bool:
        if self.is_running():
            return False
        self._pending_terminal_events = []
        self._thread = PipelineThread(
            self._worker,
            files,
            config_data,
            force_run=bool(force_run),
            force_run_from=force_run_from,
        )
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        return True

    def request_pause(self, paused: bool) -> None:
        thread = self._active_thread()
        if thread is None:
            return
        if paused:
            thread.request_pause()
        else:
            thread.request_resume()

    def request_cancel(self) -> None:
        thread = self._active_thread()
        if thread is None:
            return
        thread.request_cancel()

    def shutdown(self) -> None:
        thread = self._active_thread()
        if thread is not None:
            thread.request_cancel()
            thread.wait()

    def _active_thread(self) -> PipelineThread | None:
        thread = self._thread
        if thread is None:
            return None
        if thread.isRunning():
            return thread
        self._thread = None
        return None

    def _on_worker_finished(self, base_name: str) -> None:
        self._queue_or_emit_terminal("finished", str(base_name or ""))

    def _on_worker_failed(self, message: str) -> None:
        self._queue_or_emit_terminal("failed", str(message or ""))

    def _queue_or_emit_terminal(self, event_name: str, payload: str) -> None:
        thread = self._thread
        if thread is not None and thread.isRunning():
            self._pending_terminal_events.append((event_name, payload))
            return
        self._emit_terminal(event_name, payload)

    def _on_thread_finished(self) -> None:
        self._thread = None
        pending = list(self._pending_terminal_events)
        self._pending_terminal_events = []
        for event_name, payload in pending:
            self._emit_terminal(event_name, payload)

    def _emit_terminal(self, event_name: str, payload: str) -> None:
        if event_name == "failed":
            self.failed.emit(payload)
            return
        self.finished.emit(payload)
