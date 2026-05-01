from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineRefreshViewState:
    meta: str
    stages: list[object]
    run_enabled: bool
    pause_enabled: bool
    stop_enabled: bool
    paused: bool


class PipelineUiStateController:
    @staticmethod
    def pipeline_meta(
        *,
        selected_stage_id: str,
        config_source: str,
        config_path: str,
        overrides: list[str],
        pipeline_preset: str,
        plugin_registry: dict,
        active_meeting_base_name: str,
        active_meeting_source_path: str,
        active_meeting_status: str,
        input_files: list[str],
        default_rerun_stage: str,
    ) -> str:
        lines: list[str] = []

        source = str(config_source or "")
        path = str(config_path or "")
        lines.append(f"Pipeline preset: {pipeline_preset} ({source})")
        if path:
            lines.append(f"Pipeline path: {path}")
        if overrides:
            lines.append(f"Pipeline overrides: {', '.join(overrides[:8])}" + (" …" if len(overrides) > 8 else ""))

        registry_source = str((plugin_registry or {}).get("source", "") or "")
        registry_path = str((plugin_registry or {}).get("path", "") or "")
        if registry_source:
            lines.append(
                f"Plugin registry: {registry_source}" + (f" ({registry_path})" if registry_path else "")
            )

        stage_id = str(selected_stage_id or "").strip()
        if active_meeting_base_name and active_meeting_source_path:
            if input_files and (len(input_files) > 1 or active_meeting_status not in {"raw", "pending", "queued", "cancelled"}):
                lines.append(f"Run pending files: {len(input_files)}")
            else:
                if not stage_id:
                    stage_id = str(default_rerun_stage or "").strip()
                if stage_id:
                    lines.append(f"Run from stage '{stage_id}' for meeting {active_meeting_base_name}")
        elif input_files:
            lines.append(f"Run pending files: {len(input_files)}")

        return "\n".join([line for line in lines if str(line or "").strip()])

    @staticmethod
    def can_run_pipeline(
        *,
        stages: list[object],
        pipeline_running: bool,
        selected_stage_id: str,
        active_meeting_base_name: str,
        active_meeting_source_path: str,
        input_files: list[str],
    ) -> bool:
        if pipeline_running:
            return False
        stage_index = {str(getattr(stage, "stage_id", "") or ""): stage for stage in stages}
        stage_id = str(selected_stage_id or "").strip()
        if stage_id and active_meeting_base_name:
            stage = stage_index.get(stage_id)
            if not stage or str(getattr(stage, "status", "") or "").strip() == "disabled":
                return False
            return bool(active_meeting_source_path)
        if active_meeting_base_name and active_meeting_source_path:
            return True
        if not input_files:
            return False
        transcription = stage_index.get("transcription")
        transcription_status = str(getattr(transcription, "status", "") or "").strip()
        if transcription and transcription_status in {"idle", "failed", "disabled"}:
            return False
        return True

    @staticmethod
    def build_refresh_state(
        *,
        stages: list[object],
        pipeline_running: bool,
        pipeline_paused: bool,
        selected_stage_id: str,
        config_source: str,
        config_path: str,
        overrides: list[str],
        pipeline_preset: str,
        plugin_registry: dict,
        active_meeting_base_name: str,
        active_meeting_source_path: str,
        active_meeting_status: str,
        input_files: list[str],
        default_rerun_stage: str,
    ) -> PipelineRefreshViewState:
        stage_list = list(stages or [])
        return PipelineRefreshViewState(
            meta=PipelineUiStateController.pipeline_meta(
                selected_stage_id=selected_stage_id,
                config_source=config_source,
                config_path=config_path,
                overrides=list(overrides or []),
                pipeline_preset=pipeline_preset,
                plugin_registry=dict(plugin_registry or {}),
                active_meeting_base_name=active_meeting_base_name,
                active_meeting_source_path=active_meeting_source_path,
                active_meeting_status=active_meeting_status,
                input_files=list(input_files or []),
                default_rerun_stage=default_rerun_stage,
            ),
            stages=stage_list,
            run_enabled=PipelineUiStateController.can_run_pipeline(
                stages=stage_list,
                pipeline_running=bool(pipeline_running),
                selected_stage_id=selected_stage_id,
                active_meeting_base_name=active_meeting_base_name,
                active_meeting_source_path=active_meeting_source_path,
                input_files=list(input_files or []),
            ),
            pause_enabled=bool(pipeline_running),
            stop_enabled=bool(pipeline_running),
            paused=bool(pipeline_paused),
        )
