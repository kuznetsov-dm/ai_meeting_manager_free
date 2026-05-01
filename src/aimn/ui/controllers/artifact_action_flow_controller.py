from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactRerunPlan:
    should_start: bool
    force_run_from: str = ""
    base_name: str | None = None
    runtime_config_override: dict[str, object] | None = None
    log_message: str = ""
    log_stage_id: str = "ui"


@dataclass(frozen=True)
class ArtifactCleanupPlan:
    should_log: bool
    log_message: str = ""
    log_stage_id: str = "management"


class ArtifactActionFlowController:
    @staticmethod
    def rerun_stage_with_current_settings(
        stage_id: str,
        *,
        active_meeting_base_name: str,
        runtime_config_with_stage_enabled: Callable[[str], dict[str, object]],
        runtime_stage_id_for_ui: Callable[[str], str],
    ) -> ArtifactRerunPlan:
        sid = str(stage_id or "").strip()
        if not sid:
            return ArtifactRerunPlan(should_start=False)
        return ArtifactRerunPlan(
            should_start=True,
            force_run_from=str(runtime_stage_id_for_ui(sid) or "").strip(),
            base_name=str(active_meeting_base_name or "").strip() or None,
            runtime_config_override=dict(runtime_config_with_stage_enabled(sid) or {}),
        )

    @staticmethod
    def rerun_artifact_same_settings(
        stage_id: str,
        alias: str,
        *,
        active_meeting_base_name: str,
        runtime_config_for_artifact_alias: Callable[[str, str], dict[str, object] | None],
        fmt: Callable[..., str],
    ) -> ArtifactRerunPlan:
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        if not sid or not al:
            return ArtifactRerunPlan(should_start=False)
        runtime_config = runtime_config_for_artifact_alias(sid, al)
        if runtime_config is None:
            return ArtifactRerunPlan(
                should_start=False,
                log_message=fmt(
                    "log.artifact_lineage_not_found",
                    "Cannot rerun artifact {alias}: lineage settings not found",
                    alias=al,
                ),
                log_stage_id="ui",
            )
        return ArtifactRerunPlan(
            should_start=True,
            force_run_from=sid,
            base_name=str(active_meeting_base_name or "").strip() or None,
            runtime_config_override=dict(runtime_config or {}),
        )

    @staticmethod
    def cleanup_management_for_artifact(
        artifact_kind: str,
        source_alias: str,
        *,
        meeting_id: str,
        run_artifact_alias_cleanup: Callable[[str, str, str], dict[str, int] | None],
        fmt: Callable[..., str],
    ) -> ArtifactCleanupPlan:
        mid = str(meeting_id or "").strip()
        kind = str(artifact_kind or "").strip()
        alias = str(source_alias or "").strip()
        if not mid or not alias:
            return ArtifactCleanupPlan(should_log=False)
        result = run_artifact_alias_cleanup(mid, kind, alias)
        if result is None:
            return ArtifactCleanupPlan(should_log=False)
        return ArtifactCleanupPlan(
            should_log=True,
            log_message=fmt(
                "artifact_cleanup.log",
                "Management cleanup for artifact {alias}: removed suggestions={suggestions}, task mentions={tasks}, project mentions={projects}, agenda mentions={agendas}.",
                alias=alias,
                suggestions=int(result.get("suggestions", 0) or 0),
                tasks=int(result.get("task_mentions", 0) or 0),
                projects=int(result.get("project_mentions", 0) or 0),
                agendas=int(result.get("agenda_mentions", 0) or 0),
            ),
            log_stage_id="management",
        )
