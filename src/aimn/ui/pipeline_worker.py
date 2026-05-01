from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import QObject, QThread, Signal

from aimn.core.api import PipelineService
from aimn.core.contracts import StageEvent
from aimn.ui.tabs.contracts import PipelineEvent


def _should_emit_stage_progress_status(event: StageEvent) -> bool:
    if str(event.stage_id or "").strip() != "llm_processing":
        return True
    return bool(str(event.message or "").strip())


def _stage_terminal_ui_state(
    *,
    event_type: str,
    prior_state: str,
    artifact_count: int,
) -> str:
    kind = str(event_type or "").strip()
    state = str(prior_state or "").strip().lower()
    if kind == "stage_skipped" and int(artifact_count or 0) > 0:
        return "finished"
    if kind == "stage_finished" and state not in {"failed", "skipped"}:
        return "finished"
    return kind


class PipelineWorker(QObject):
    log = Signal(str)
    progress = Signal(int)
    stage_status = Signal(str, str, int, str, str, int, str)
    pipeline_event = Signal(object)
    file_started = Signal(str, str)
    file_completed = Signal(str, str)
    file_failed = Signal(str, str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, repo_root: Path) -> None:
        super().__init__()
        self._repo_root = repo_root
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()

    def run(
        self,
        files: List[str],
        config_data: Dict[str, object],
        *,
        force_run: bool = False,
        force_run_from: str | None = None,
    ) -> None:
        if not files:
            self.log.emit("No files selected")
            self.failed.emit("No files selected")
            return

        self._cancel_event.clear()
        self._pause_event.clear()
        service = PipelineService(self._repo_root, config_data)
        try:
            last_base_name = ""
            for file_path in files:
                self._wait_if_paused()
                if self._cancel_event.is_set():
                    break
                meeting = None
                try:
                    media_path = Path(file_path)
                    meeting = service.load_meeting(media_path)
                    _set_processing_status(meeting, "running")
                    try:
                        service.save_meeting(meeting)
                    except Exception as exc:
                        self.log.emit(f"Meeting save failed (start): {exc}")
                    self.file_started.emit(str(file_path), meeting.base_name)

                    log_path = self._init_log_path(meeting.base_name)
                    stage_states: Dict[str, str] = {}
                    stage_artifact_counts: Dict[str, int] = {}
                    current_stage_id = ""
                    for warning in service.dependency_warnings():
                        self.log.emit(warning)

                    def save_snapshot(reason: str) -> None:
                        try:
                            service.save_meeting(meeting)
                        except Exception as exc:
                            self.log.emit(f"Meeting save failed ({reason}): {exc}")

                    def emit_event(event: StageEvent) -> None:
                        nonlocal current_stage_id
                        self.pipeline_event.emit(
                            PipelineEvent(
                                event_type=event.event_type,
                                stage_id=event.stage_id,
                                message=event.message,
                                progress=event.progress,
                                timestamp=event.timestamp,
                                base_name=meeting.base_name,
                                meeting_id=meeting.meeting_id,
                            )
                        )
                        self._append_log(log_path, meeting.base_name, meeting.meeting_id, event)
                        if event.event_type == "stage_started":
                            current_stage_id = event.stage_id or ""
                            progress = -1 if current_stage_id == "llm_processing" else 0
                            self.stage_status.emit(
                                current_stage_id,
                                "running",
                                0,
                                "",
                                "",
                                progress,
                                meeting.base_name,
                            )
                            if current_stage_id == "llm_processing":
                                self.log.emit(
                                    "AI processing started. Provider latency may vary; progress may stay idle."
                                )
                        elif event.event_type == "stage_finished":
                            stage_id = event.stage_id or ""
                            terminal_state = _stage_terminal_ui_state(
                                event_type=event.event_type,
                                prior_state=stage_states.get(stage_id, ""),
                                artifact_count=stage_artifact_counts.get(stage_id, 0),
                            )
                            if terminal_state == "finished":
                                self.stage_status.emit(
                                    stage_id,
                                    "finished",
                                    0,
                                    "",
                                    "",
                                    100,
                                    meeting.base_name,
                                )
                                self.log.emit(f"Stage {event.stage_id} finished")
                            save_snapshot("stage_finished")
                            current_stage_id = ""
                        elif event.event_type == "stage_failed":
                            stage_id = event.stage_id or ""
                            formatted_error = _format_stage_error(stage_id, str(event.message or ""))
                            stage_states[stage_id] = "failed"
                            self.stage_status.emit(
                                stage_id,
                                "failed",
                                0,
                                formatted_error,
                                "",
                                0,
                                meeting.base_name,
                            )
                            self.log.emit(f"Stage {event.stage_id} failed: {formatted_error or event.message}")
                            save_snapshot("stage_failed")
                            current_stage_id = ""
                        elif event.event_type == "stage_skipped":
                            stage_id = event.stage_id or ""
                            terminal_state = _stage_terminal_ui_state(
                                event_type=event.event_type,
                                prior_state=stage_states.get(stage_id, ""),
                                artifact_count=stage_artifact_counts.get(stage_id, 0),
                            )
                            if terminal_state == "finished":
                                stage_states[stage_id] = "finished"
                                self.stage_status.emit(
                                    stage_id,
                                    "finished",
                                    0,
                                    "",
                                    "",
                                    100,
                                    meeting.base_name,
                                )
                                self.log.emit(
                                    f"Stage {event.stage_id} produced artifacts; treating skipped event as finished."
                                )
                            else:
                                stage_states[stage_id] = "skipped"
                                self.stage_status.emit(
                                    stage_id,
                                    "skipped",
                                    0,
                                    "",
                                    str(event.message or ""),
                                    0,
                                    meeting.base_name,
                                )
                                self.log.emit(f"Stage {event.stage_id} skipped: {event.message}")
                            current_stage_id = ""
                        elif event.event_type == "stage_retry":
                            self.log.emit(f"Stage {event.stage_id} retrying: {event.message}")
                        elif event.event_type == "artifact_written":
                            stage_id = str(event.stage_id or "").strip()
                            if stage_id:
                                stage_artifact_counts[stage_id] = int(stage_artifact_counts.get(stage_id, 0)) + 1
                            self.log.emit(f"Artifact written: {event.message}")
                        elif event.event_type == "stage_progress":
                            if event.stage_id and event.progress is not None:
                                if not _should_emit_stage_progress_status(event):
                                    return
                                self.stage_status.emit(
                                    event.stage_id,
                                    "running",
                                    0,
                                    "",
                                    "",
                                    int(event.progress),
                                    meeting.base_name,
                                )
                            return
                        elif event.event_type == "cache_hit":
                            self.log.emit(f"Cache hit: {event.message}")
                        elif event.event_type == "plugin_notice":
                            self.log.emit(f"Plugin: {event.message}")
                        elif event.event_type == "execution_plan":
                            self.log.emit(f"Execution plan: {event.message}")
                        else:
                            self.log.emit(f"{event.event_type}: {event.message}")

                    def on_progress(value: int) -> None:
                        self.progress.emit(value)

                    outcome = service.run_meeting(
                        meeting,
                        force_run=force_run,
                        force_run_from=force_run_from,
                        progress_callback=on_progress,
                        event_callback=emit_event,
                        cancel_requested=self._cancel_event.is_set,
                    )
                    if outcome.error:
                        error = outcome.error
                        cancelled = self._cancel_event.is_set() or "cancelled_by_user" in error
                        if cancelled:
                            self.log.emit(f"Pipeline cancelled for {file_path}")
                            _set_processing_status(meeting, "cancelled", error="cancelled_by_user")
                            save_snapshot("pipeline_cancelled")
                            self.file_failed.emit(str(file_path), "cancelled_by_user")
                            break
                        self.log.emit(f"Pipeline crashed for {file_path}: {error}")
                        _set_processing_status(meeting, "failed", error=error)
                        save_snapshot("pipeline_exception")
                        self.file_failed.emit(str(file_path), error)
                        continue

                    if self._cancel_event.is_set():
                        _set_processing_status(meeting, "cancelled", error="cancelled_by_user")
                        save_snapshot("pipeline_cancelled")
                        self.file_failed.emit(str(file_path), "cancelled_by_user")
                        break

                    latest_meeting = _reload_meeting_for_status(service, file_path, fallback=meeting)
                    _set_processing_status(latest_meeting, "completed")
                    try:
                        service.save_meeting(latest_meeting)
                    except Exception as exc:
                        self.log.emit(f"Meeting save failed (complete): {exc}")
                    else:
                        meeting = latest_meeting

                    self.file_completed.emit(str(file_path), meeting.base_name)
                    last_base_name = meeting.base_name
                    self.progress.emit(100)
                except Exception as exc:
                    error = str(exc)
                    self.log.emit(f"Pipeline crashed for {file_path}: {error}")
                    cancelled = self._cancel_event.is_set() or "cancelled_by_user" in error
                    if meeting is not None:
                        try:
                            _set_processing_status(
                                meeting,
                                "cancelled" if cancelled else "failed",
                                error="cancelled_by_user" if cancelled else error,
                            )
                            service.save_meeting(meeting)
                        except Exception as save_exc:
                            self.log.emit(f"Meeting save failed (unexpected_error): {save_exc}")
                    self.file_failed.emit(str(file_path), "cancelled_by_user" if cancelled else error)
                    if cancelled:
                        break
                    continue
            self.finished.emit(last_base_name)
        finally:
            service.shutdown()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def request_pause(self) -> None:
        self._pause_event.set()

    def request_resume(self) -> None:
        self._pause_event.clear()

    def _wait_if_paused(self) -> None:
        while self._pause_event.is_set() and not self._cancel_event.is_set():
            time.sleep(0.15)

    def _init_log_path(self, base_name: str) -> Path:
        logs_dir = self._repo_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return logs_dir / f"pipeline_{base_name}_{stamp}.log"

    @staticmethod
    def _append_log(path: Path, base_name: str, meeting_id: str, event: StageEvent) -> None:
        stage = event.stage_id or "-"
        message = event.message or ""
        line = f"{event.event_type}\t{base_name}\t{meeting_id}\t{stage}\t{message}\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


class PipelineThread(QThread):
    def __init__(
        self,
        worker: PipelineWorker,
        files: List[str],
        config_data: Dict[str, object],
        *,
        force_run: bool = False,
        force_run_from: str | None = None,
    ) -> None:
        super().__init__()
        self._worker = worker
        self._files = files
        self._config_data = config_data
        self._force_run = force_run
        self._force_run_from = force_run_from

    def run(self) -> None:
        self._worker.run(
            self._files,
            self._config_data,
            force_run=self._force_run,
            force_run_from=self._force_run_from,
        )

    def request_cancel(self) -> None:
        self._worker.request_cancel()
        self.requestInterruption()

    def request_pause(self) -> None:
        self._worker.request_pause()

    def request_resume(self) -> None:
        self._worker.request_resume()


def _set_processing_status(meeting, status: str, *, error: str = "") -> None:
    setattr(meeting, "processing_status", str(status or "").strip().lower() or "raw")
    setattr(meeting, "processing_error", str(error or "").strip())
    meeting.updated_at = _utc_now_iso()


def _reload_meeting_for_status(service: PipelineService, file_path: str, *, fallback):
    try:
        return service.load_meeting(Path(file_path))
    except Exception:
        return fallback


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _format_stage_error(stage_id: str, error: str) -> str:
    raw = str(error or "").strip()
    if not raw:
        return ""
    if str(stage_id or "").strip() != "llm_processing":
        return raw
    if raw.startswith("no_real_llm_artifacts:"):
        detail = raw.split(":", 1)[1].strip()
        if detail:
            return f"All LLM variants fell back or failed: {detail}"
        return "All LLM variants fell back or failed."
    return raw




def _infer_artifact_info(meeting, relpath: str) -> tuple[str | None, str | None]:
    normalized = relpath.strip()
    if not normalized:
        return None, None
    base = f"{meeting.base_name}"
    if normalized.startswith(f"{base}__"):
        rest = normalized[len(base) + 2 :]
        parts = rest.split(".")
        if len(parts) >= 2:
            return parts[0] or None, parts[1] or None
        return None, None
    if normalized.startswith(f"{base}."):
        rest = normalized[len(base) + 1 :]
        parts = rest.split(".")
        if parts:
            return None, parts[0] or None
    return None, None
