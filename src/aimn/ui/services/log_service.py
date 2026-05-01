from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional

from PySide6.QtCore import QObject, Signal

from aimn.ui.tabs.contracts import PipelineEvent


@dataclass(frozen=True)
class LogEntry:
    message: str
    stage_id: str
    timestamp: str = ""


class LogService(QObject):
    log_appended = Signal(str, str)

    def __init__(self, *, max_entries: int = 2000) -> None:
        super().__init__()
        self._max_entries = max(100, int(max_entries))
        self._all: Deque[LogEntry] = deque(maxlen=self._max_entries)
        self._by_stage: Dict[str, Deque[LogEntry]] = defaultdict(
            lambda: deque(maxlen=self._max_entries)
        )

    def append_message(self, message: str, *, stage_id: str = "") -> None:
        entry = LogEntry(message=message, stage_id=stage_id, timestamp="")
        self._add_entry(entry)

    def append_event(self, event: PipelineEvent) -> None:
        message = event.message or event.event_type
        stage_id = event.stage_id or ""
        entry = LogEntry(message=message, stage_id=stage_id, timestamp=event.timestamp or "")
        self._add_entry(entry)

    def get_stage_logs(self, stage_id: str) -> List[LogEntry]:
        return list(self._by_stage.get(stage_id, []))

    def get_all_logs(self) -> List[LogEntry]:
        return list(self._all)

    def clear(self) -> None:
        self._all.clear()
        self._by_stage.clear()

    def _add_entry(self, entry: LogEntry) -> None:
        self._all.append(entry)
        self._by_stage[entry.stage_id].append(entry)
        self.log_appended.emit(entry.stage_id, entry.message)
