from __future__ import annotations

from datetime import datetime, timezone
import uuid

from aimn.core.pipeline import PipelineResult
from aimn.domain.meeting import MeetingManifest, PipelineRun, PipelineStageResult


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("run_%Y%m%d_%H%M%S")
    millis = int(now.microsecond / 1000)
    suffix = uuid.uuid4().hex[:6]
    return f"{stamp}_{millis:03d}_{suffix}"


def pipeline_result_to_run(result: PipelineResult) -> PipelineRun:
    stage_results = [
        PipelineStageResult(
            stage_id=stage.stage_id,
            status=stage.status,
            duration_ms=stage.duration_ms,
            cache_hit=stage.cache_hit,
            error=stage.error,
            skip_reason=stage.skip_reason,
        )
        for stage in result.stage_results
    ]
    error = None
    if result.result == "partial_success":
        failed = [
            f"{stage.stage_id}:{stage.error or 'failed'}"
            for stage in result.stage_results
            if stage.status == "failed"
        ]
        if failed:
            error = "partial_failure: " + "; ".join(failed)
    return PipelineRun(
        run_id=result.run_id,
        started_at=result.started_at,
        finished_at=result.finished_at,
        force_run=result.force_run,
        result=result.result,
        stages=stage_results,
        error=error,
    )


def append_run(meeting: MeetingManifest, run: PipelineRun) -> None:
    meeting.pipeline_runs.append(run)
    meeting.updated_at = run.finished_at or _utc_now_iso()


def failed_run(error: str, *, started_at: str | None = None) -> PipelineRun:
    started = started_at or _utc_now_iso()
    finished = _utc_now_iso()
    return PipelineRun(
        run_id=_run_id(),
        started_at=started,
        finished_at=finished,
        force_run=False,
        result="failed",
        stages=[],
        warnings=[],
        error=error,
    )
