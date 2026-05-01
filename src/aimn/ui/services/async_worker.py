from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

_IN_FLIGHT_WORKERS: set[AsyncWorker] = set()


class WorkerSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, object)


class AsyncWorker(QRunnable):
    def __init__(self, request_id: int, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._request_id = int(request_id)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.finished.emit(self._request_id, result)
        except Exception as exc:
            self.signals.failed.emit(self._request_id, exc)


def run_async(
    *,
    request_id: int,
    fn: Callable[..., Any],
    on_finished: Callable[[int, Any], None],
    on_error: Callable[[int, Exception], None] | None = None,
    thread_pool: QThreadPool | None = None,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> AsyncWorker:
    worker = AsyncWorker(request_id, fn, *(args or ()), **(kwargs or {}))
    _IN_FLIGHT_WORKERS.add(worker)

    def _cleanup(_request_id: int, _payload: object) -> None:
        _IN_FLIGHT_WORKERS.discard(worker)

    worker.signals.finished.connect(_cleanup)
    worker.signals.failed.connect(_cleanup)
    worker.signals.finished.connect(on_finished)
    if on_error is not None:
        worker.signals.failed.connect(on_error)
    (thread_pool or QThreadPool.globalInstance()).start(worker)
    return worker
