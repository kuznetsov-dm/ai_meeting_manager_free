from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

from aimn.core.contracts import StageEvent
from aimn.domain.meeting import MeetingManifest


StageEventHandler = Callable[[StageEvent], None]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("run_%Y%m%d_%H%M%S")
    millis = int(now.microsecond / 1000)
    suffix = uuid.uuid4().hex[:6]
    return f"{stamp}_{millis:03d}_{suffix}"


@dataclass(frozen=True)
class StagePolicy:
    stage_id: str
    required: bool = True
    continue_on_error: bool = True
    depends_on: List[str] = field(default_factory=list)
    max_retries: int = 0


@dataclass
class StageContext:
    meeting: MeetingManifest
    force_run: bool = False
    force_run_from: Optional[str] = None
    selected_plugins: Dict[str, str] = field(default_factory=dict)
    output_dir: Optional[str] = None
    ffmpeg_path: Optional[str] = None
    progress_callback: Optional[Callable[[int], None]] = None
    event_callback: Optional[Callable[[StageEvent], None]] = None
    plugin_manager: Optional[object] = None
    cancel_requested: Optional[Callable[[], bool]] = None


@dataclass
class StageResult:
    stage_id: str
    status: str
    cache_hit: bool = False
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    skip_reason: Optional[str] = None


@dataclass
class PipelineResult:
    run_id: str
    started_at: str
    finished_at: Optional[str]
    force_run: bool
    result: str
    stage_results: List[StageResult] = field(default_factory=list)


class StageAdapter:
    def __init__(self, stage_id: str, policy: StagePolicy) -> None:
        self.stage_id = stage_id
        self.policy = policy

    def run(self, context: StageContext) -> StageResult:
        raise NotImplementedError


class PipelineEngine:
    def __init__(self, stages: Iterable[StageAdapter]) -> None:
        self._stages = list(stages)

    def run(
        self,
        context: StageContext,
        emit: Optional[StageEventHandler] = None,
    ) -> PipelineResult:
        emit = emit or (lambda event: None)
        base_force_run = bool(context.force_run)
        force_run_flag = bool(context.force_run)
        start_index = None
        if context.force_run_from:
            for idx, adapter in enumerate(self._stages):
                if adapter.stage_id == context.force_run_from:
                    start_index = idx
                    break
        run_id = _run_id()
        started_at = _utc_now_iso()
        emit(StageEvent(event_type="pipeline_started"))
        stage_results: List[StageResult] = []
        total_stages = max(1, len(self._stages))
        base_progress = context.progress_callback

        results_by_stage: Dict[str, StageResult] = {}
        for index, adapter in enumerate(self._stages):
            if start_index is not None and index < start_index:
                skipped = StageResult(
                    stage_id=adapter.stage_id,
                    status="skipped",
                    cache_hit=False,
                    skip_reason=f"rerun_from:{context.force_run_from}",
                )
                stage_results.append(skipped)
                results_by_stage[skipped.stage_id] = skipped
                emit(
                    StageEvent(
                        event_type="stage_skipped",
                        stage_id=adapter.stage_id,
                        message=skipped.skip_reason,
                    )
                )
                emit(StageEvent(event_type="stage_finished", stage_id=adapter.stage_id))
                continue
            context.force_run = base_force_run or (start_index is not None and index == start_index)
            start_percent = int((index / total_stages) * 100)
            end_percent = int(((index + 1) / total_stages) * 100)
            stage_id = adapter.stage_id

            def _stage_progress(
                value: int,
                start=start_percent,
                end=end_percent,
                stage_id=stage_id,
            ) -> None:
                if not base_progress:
                    return
                clamped = max(0, min(100, int(value)))
                overall = start + int((end - start) * (clamped / 100))
                base_progress(overall)
                emit(
                    StageEvent(
                        event_type="stage_progress",
                        stage_id=stage_id,
                        progress=clamped,
                    )
                )

            context.progress_callback = _stage_progress if base_progress else None
            if base_progress:
                base_progress(start_percent)

            if _is_cancelled(context):
                emit(StageEvent(event_type="pipeline_cancelled"))
                finished_at = _utc_now_iso()
                context.progress_callback = base_progress
                context.force_run = base_force_run
                return PipelineResult(
                    run_id=run_id,
                    started_at=started_at,
                    finished_at=finished_at,
                    force_run=force_run_flag,
                    result="cancelled",
                    stage_results=stage_results,
                )

            emit(StageEvent(event_type="stage_started", stage_id=adapter.stage_id))
            blocked = _dependency_block(adapter.policy, results_by_stage)
            if blocked is not None:
                stage_results.append(blocked)
                results_by_stage[blocked.stage_id] = blocked
                if blocked.status == "failed":
                    emit(StageEvent(event_type="stage_failed", stage_id=adapter.stage_id, message=blocked.error))
                elif blocked.status == "skipped":
                    message = blocked.skip_reason or blocked.status
                    emit(StageEvent(event_type="stage_skipped", stage_id=adapter.stage_id, message=message))
                emit(StageEvent(event_type="stage_finished", stage_id=adapter.stage_id))
                if base_progress:
                    base_progress(end_percent)
                continue
            attempts = 0
            max_attempts = 1
            if not adapter.policy.required:
                max_attempts += max(adapter.policy.max_retries, 0)
            total_duration = 0
            result = None
            while attempts < max_attempts:
                attempts += 1
                start_time = time.monotonic()
                try:
                    result = adapter.run(context)
                except Exception as exc:
                    result = StageResult(
                        stage_id=adapter.stage_id,
                        status="failed",
                        cache_hit=False,
                        error=str(exc),
                    )
                total_duration += int((time.monotonic() - start_time) * 1000)
                if result.status == "failed" and attempts < max_attempts:
                    emit(
                        StageEvent(
                            event_type="stage_retry",
                            stage_id=adapter.stage_id,
                            message=f"attempt {attempts} failed: {result.error}",
                        )
                    )
                    continue
                break

            if result is None:
                result = StageResult(stage_id=adapter.stage_id, status="failed", cache_hit=False)

            result.duration_ms = total_duration
            stage_results.append(result)
            results_by_stage[result.stage_id] = result

            if result.status == "failed":
                emit(StageEvent(event_type="stage_failed", stage_id=adapter.stage_id, message=result.error))
                if adapter.policy.required and not adapter.policy.continue_on_error:
                    if base_progress:
                        base_progress(end_percent)
                    emit(StageEvent(event_type="pipeline_failed"))
                    finished_at = _utc_now_iso()
                    context.progress_callback = base_progress
                    context.force_run = base_force_run
                    return PipelineResult(
                        run_id=run_id,
                        started_at=started_at,
                        finished_at=finished_at,
                        force_run=force_run_flag,
                        result="failed",
                        stage_results=stage_results,
                    )

            if result.status == "skipped":
                message = result.skip_reason or result.status
                emit(StageEvent(event_type="stage_skipped", stage_id=adapter.stage_id, message=message))

            emit(StageEvent(event_type="stage_finished", stage_id=adapter.stage_id))
            if base_progress:
                base_progress(end_percent)

        emit(StageEvent(event_type="pipeline_finished"))
        finished_at = _utc_now_iso()
        final_status = "success"
        if any(result.status == "failed" for result in stage_results):
            final_status = "partial_success"

        context.progress_callback = base_progress
        context.force_run = base_force_run
        return PipelineResult(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            force_run=force_run_flag,
            result=final_status,
            stage_results=stage_results,
        )


def _dependency_block(policy: StagePolicy, results: Dict[str, StageResult]) -> StageResult | None:
    if not policy.depends_on:
        return None
    missing = []
    failed = []
    skipped = []
    for dep in policy.depends_on:
        dep_result = results.get(dep)
        if not dep_result:
            missing.append(dep)
            continue
        if dep_result.status == "failed":
            failed.append(dep)
        elif dep_result.status == "skipped":
            if str(dep_result.skip_reason or "").strip().startswith("rerun_from:"):
                continue
            skipped.append(dep)
    if not (missing or failed or skipped):
        return None
    if policy.required:
        reason = failed[0] if failed else skipped[0] if skipped else missing[0]
        error_kind = "dependency_failed" if failed else "dependency_skipped" if skipped else "dependency_missing"
        return StageResult(stage_id=policy.stage_id, status="failed", cache_hit=False, error=f"{error_kind}:{reason}")
    reason = failed[0] if failed else skipped[0] if skipped else missing[0]
    skip_kind = "dependency_failed" if failed else "dependency_skipped" if skipped else "dependency_missing"
    return StageResult(
        stage_id=policy.stage_id,
        status="skipped",
        cache_hit=False,
        skip_reason=f"{skip_kind}:{reason}",
    )


def _is_cancelled(context: StageContext) -> bool:
    if context.cancel_requested is None:
        return False
    try:
        return bool(context.cancel_requested())
    except Exception:
        return False
