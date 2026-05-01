from __future__ import annotations

from dataclasses import dataclass

from aimn.ui.controllers.artifact_selection_controller import ArtifactSelectionController
from aimn.ui.controllers.main_text_panel_state_controller import MainTextPanelStateController


@dataclass(frozen=True)
class KindVersionSelectionState:
    active_kind: str
    versions: list[object]
    target_tab_index: int | None
    emit_selection: bool
    update_kind_rows_only: bool


class MainTextPanelSelectionController:
    @staticmethod
    def activate_kind_selection(
        *,
        kind: str,
        kinds: list[str],
        active_kind: str,
        artifacts_by_kind: dict[str, list[object]],
        version_index: int | None = None,
        global_results_visible: bool,
    ) -> KindVersionSelectionState:
        state = MainTextPanelStateController.activate_kind(
            selected_kind=kind,
            kinds=kinds,
            active_kind=active_kind,
            artifacts_by_kind=artifacts_by_kind,
        )
        if not state.active_kind:
            return KindVersionSelectionState(
                active_kind=str(active_kind or "").strip(),
                versions=list(artifacts_by_kind.get(str(active_kind or "").strip(), []) or []),
                target_tab_index=None,
                emit_selection=False,
                update_kind_rows_only=False,
            )
        if state.update_selection_only:
            target_tab_index = None
            if version_index is not None:
                target_tab_index = MainTextPanelStateController.kind_version_tab_index(
                    global_results_visible=global_results_visible,
                    version_index=int(version_index),
                )
            return KindVersionSelectionState(
                active_kind=state.active_kind,
                versions=list(state.versions),
                target_tab_index=target_tab_index,
                emit_selection=True,
                update_kind_rows_only=True,
            )
        return KindVersionSelectionState(
            active_kind=state.active_kind,
            versions=list(state.versions),
            target_tab_index=(
                MainTextPanelStateController.kind_version_tab_index(
                    global_results_visible=global_results_visible,
                    version_index=int(version_index),
                )
                if version_index is not None
                else None
            ),
            emit_selection=True,
            update_kind_rows_only=False,
        )

    @staticmethod
    def current_selection_payload(
        *,
        versions: list[object],
        tab_index: int,
        global_results_visible: bool,
    ) -> tuple[str, str, str]:
        return ArtifactSelectionController.selection_payload_for_tab(
            versions,
            tab_index=tab_index,
            global_results_visible=global_results_visible,
        )
