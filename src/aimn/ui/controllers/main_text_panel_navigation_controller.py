from __future__ import annotations

from collections.abc import Sequence

from aimn.ui.controllers.artifact_tab_navigation_controller import ArtifactTabNavigationController
from aimn.ui.controllers.transcript_navigation_controller import TranscriptNavigationController


class MainTextPanelNavigationController:
    @staticmethod
    def alias_tab_index(
        *,
        versions: Sequence[object],
        global_results_visible: bool,
        alias: str,
    ) -> int | None:
        return ArtifactTabNavigationController.select_alias_tab_index(
            versions,
            global_results_visible=global_results_visible,
            alias=alias,
        )

    @staticmethod
    def version_tab_index(
        *,
        versions: Sequence[object],
        global_results_visible: bool,
        stage_id: str = "",
        alias: str = "",
        kind: str = "",
    ) -> int | None:
        return ArtifactTabNavigationController.select_version_tab_index(
            versions,
            global_results_visible=global_results_visible,
            stage_id=stage_id,
            alias=alias,
            kind=kind,
        )

    @staticmethod
    def transcript_row_index(
        *,
        payloads: Sequence[dict],
        segment_index: int,
        start_ms: int,
    ) -> int:
        return TranscriptNavigationController.row_for_transcript_target(
            payloads,
            segment_index=int(segment_index),
            start_ms=int(start_ms),
        )
