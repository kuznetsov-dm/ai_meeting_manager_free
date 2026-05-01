from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MeetingContextMenuActionSpec:
    action: str
    label: str
    enabled: bool


class MeetingContextMenuController:
    @staticmethod
    def build_stage_actions(
        *,
        rerun_label: str,
        pipeline_running: bool,
        has_active_meeting: bool,
    ) -> list[MeetingContextMenuActionSpec]:
        return [
            MeetingContextMenuActionSpec(
                action="rerun_stage",
                label=str(rerun_label or "").strip(),
                enabled=(not pipeline_running and has_active_meeting),
            )
        ]

    @staticmethod
    def build_artifact_actions(
        *,
        rerun_same_label: str,
        rerun_stage_label: str,
        cleanup_management_label: str,
        pipeline_running: bool,
        has_active_meeting: bool,
        has_meeting_id: bool,
    ) -> list[MeetingContextMenuActionSpec]:
        return [
            MeetingContextMenuActionSpec(
                action="rerun_same",
                label=str(rerun_same_label or "").strip(),
                enabled=(not pipeline_running and has_active_meeting),
            ),
            MeetingContextMenuActionSpec(
                action="rerun_stage",
                label=str(rerun_stage_label or "").strip(),
                enabled=(not pipeline_running and has_active_meeting),
            ),
            MeetingContextMenuActionSpec(
                action="cleanup_management",
                label=str(cleanup_management_label or "").strip(),
                enabled=has_meeting_id,
            ),
        ]
