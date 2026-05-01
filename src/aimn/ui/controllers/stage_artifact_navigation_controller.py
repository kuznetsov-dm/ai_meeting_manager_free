from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class StageArtifactNavigationPlan:
    select_kind: str = ""
    log_message: str = ""


class StageArtifactNavigationController:
    @staticmethod
    def artifact_kind_for_stage(stage_id: str) -> str:
        value = str(stage_id or "").strip()
        mapping = {
            "transcription": "transcript",
            "text_processing": "edited",
            "llm_processing": "summary",
        }
        return str(mapping.get(value, "") or "")

    @staticmethod
    def stage_id_for_artifact_kind(kind: str) -> str:
        value = str(kind or "").strip().lower()
        mapping = {
            "transcript": "transcription",
            "edited": "text_processing",
            "summary": "llm_processing",
            "agendas": "management",
        }
        return str(mapping.get(value, "") or "")

    @staticmethod
    def ui_stage_id(stage_id: str) -> str:
        return str(stage_id or "").strip()

    @staticmethod
    def runtime_stage_id_for_ui(stage_id: str) -> str:
        return str(stage_id or "").strip()

    @staticmethod
    def open_stage_artifact_plan(
        *,
        stage_id: str,
        active_meeting_base_name: str,
        active_artifacts: Sequence[object],
        fmt,
    ) -> StageArtifactNavigationPlan:
        kind = StageArtifactNavigationController.artifact_kind_for_stage(stage_id)
        if not kind:
            return StageArtifactNavigationPlan()
        if not str(active_meeting_base_name or "").strip():
            return StageArtifactNavigationPlan()
        if any(str(getattr(item, "kind", "") or "").strip() == kind for item in list(active_artifacts or [])):
            return StageArtifactNavigationPlan(select_kind=kind)
        return StageArtifactNavigationPlan(
            log_message=fmt(
                "log.no_artifacts_for_kind",
                "No '{kind}' artifacts for this meeting",
                kind=kind,
            )
        )
