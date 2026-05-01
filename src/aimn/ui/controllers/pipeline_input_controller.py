from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineStartFilesResolution:
    files: list[str]
    missing_selected_source: bool = False


@dataclass(frozen=True)
class PipelineInputLoadFailure:
    path: str
    error: Exception


@dataclass(frozen=True)
class PipelineInputIngestResult:
    normalized_paths: list[str]
    added_base_names: list[str]
    reset_runtime_base_names: list[str]
    load_failures: list[PipelineInputLoadFailure]


class PipelineInputController:
    @staticmethod
    def normalize_input_paths(paths: Sequence[object] | None) -> list[str]:
        return [str(item or "").strip() for item in list(paths or []) if str(item or "").strip()]

    @staticmethod
    def existing_files(paths: Sequence[object] | None) -> list[str]:
        existing: list[str] = []
        for item in list(paths or []):
            value = str(item or "").strip()
            if not value:
                continue
            try:
                candidate = Path(value)
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate.exists():
                existing.append(str(candidate))
        return list(dict.fromkeys(existing))

    @staticmethod
    def resolve_start_files(
        *,
        explicit_files: Sequence[object] | None,
        pending_files: Sequence[object] | None,
        ad_hoc_files: Sequence[object] | None,
        active_meeting_base_name: str,
        active_meeting_path: str,
        active_meeting_status: str,
        base_name: str = "",
        force_run: bool | None = None,
        force_run_from: str | None = None,
    ) -> PipelineStartFilesResolution:
        explicit = PipelineInputController.existing_files(explicit_files)
        pending = PipelineInputController.existing_files(pending_files)
        ad_hoc = PipelineInputController.existing_files(ad_hoc_files)
        active_status = str(active_meeting_status or "").strip().lower()
        active_is_pending = active_status in {"raw", "pending", "queued", "cancelled"}

        files: list[str] = []
        if explicit:
            files = list(explicit)
        use_pending_batch = bool(pending) and not base_name and not force_run and not force_run_from
        use_ad_hoc_batch = bool(ad_hoc) and not pending and not base_name and not force_run and not force_run_from
        if files:
            pass
        elif use_pending_batch and (len(pending) > 1 or not active_is_pending):
            files = list(pending)
        elif use_ad_hoc_batch:
            files = list(ad_hoc)
        elif str(active_meeting_base_name or "").strip():
            active_path = str(active_meeting_path or "").strip()
            if not active_path:
                return PipelineStartFilesResolution(files=[], missing_selected_source=True)
            files = [active_path]
        if not files:
            files = list(pending or ad_hoc)
        return PipelineStartFilesResolution(files=list(dict.fromkeys(files)))

    @staticmethod
    def discover_monitored_files(
        monitored_root: Path,
        *,
        previous_signatures: set[str] | None,
        monitored_extensions: set[str],
    ) -> tuple[list[str], set[str]]:
        if not monitored_root.exists() or not monitored_root.is_dir():
            return [], set(previous_signatures or set())
        discovered: list[str] = []
        current_signatures: set[str] = set()
        for path in sorted(monitored_root.iterdir()):
            if not path.is_file():
                continue
            if str(path.suffix or "").strip().lower() not in set(monitored_extensions or set()):
                continue
            try:
                stat = path.stat()
                resolved = str(path.resolve())
            except OSError:
                continue
            signature = f"{resolved}|{int(stat.st_size)}|{int(stat.st_mtime_ns)}"
            current_signatures.add(signature)
            if signature not in set(previous_signatures or set()):
                discovered.append(resolved)
        return discovered, current_signatures

    @staticmethod
    def pending_monitored_files(
        meetings: Iterable[object] | None,
        *,
        monitored_root: Path,
        resolve_meeting_primary_path: Callable[[object], str],
    ) -> list[str]:
        try:
            expected_root = monitored_root.resolve()
        except (OSError, RuntimeError, ValueError):
            return []
        monitored_files: list[str] = []
        for meeting in list(meetings or []):
            status = str(getattr(meeting, "processing_status", "") or "").strip().lower()
            if status not in {"raw", "pending", "queued"}:
                continue
            source_path = str(resolve_meeting_primary_path(meeting) or "").strip()
            if not source_path:
                continue
            try:
                candidate = Path(source_path).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate.parent != expected_root:
                continue
            if not candidate.exists() or not candidate.is_file():
                continue
            monitored_files.append(str(candidate))
        return list(dict.fromkeys(monitored_files))

    @staticmethod
    def ingest_files(
        files: Sequence[object] | None,
        *,
        load_or_create_meeting: Callable[[Path], object],
        save_meeting: Callable[[object], None],
        set_meeting_status: Callable[[object, str], None],
    ) -> PipelineInputIngestResult:
        normalized_paths = PipelineInputController.normalize_input_paths(files)
        added_base_names: list[str] = []
        reset_runtime_base_names: list[str] = []
        load_failures: list[PipelineInputLoadFailure] = []
        for path in normalized_paths:
            media_path = Path(path)
            if not media_path.exists() or not media_path.is_file():
                continue
            try:
                meeting = load_or_create_meeting(media_path)
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                load_failures.append(PipelineInputLoadFailure(path=str(media_path), error=exc))
                continue
            current_status = str(getattr(meeting, "processing_status", "") or "").strip().lower()
            has_runs = bool(getattr(meeting, "pipeline_runs", []))
            if current_status in {"completed", "running"} or (has_runs and not current_status):
                save_meeting(meeting)
            else:
                set_meeting_status(meeting, "raw")
                save_meeting(meeting)
            base_name = str(getattr(meeting, "base_name", "") or "").strip()
            added_base_names.append(base_name)
            if PipelineInputController._needs_runtime_state_reset(meeting):
                reset_runtime_base_names.append(base_name)
        return PipelineInputIngestResult(
            normalized_paths=normalized_paths,
            added_base_names=added_base_names,
            reset_runtime_base_names=list(dict.fromkeys(reset_runtime_base_names)),
            load_failures=load_failures,
        )

    @staticmethod
    def _needs_runtime_state_reset(meeting: object) -> bool:
        runs = getattr(meeting, "pipeline_runs", None)
        if isinstance(runs, list) and runs:
            return False
        nodes = getattr(meeting, "nodes", None)
        if isinstance(nodes, dict) and nodes:
            return False
        status = str(getattr(meeting, "processing_status", "") or "").strip().lower()
        return status in {"", "raw", "pending", "queued", "cancelled"}
