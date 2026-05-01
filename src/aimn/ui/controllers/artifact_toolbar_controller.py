from __future__ import annotations

from aimn.ui.controllers.artifact_selection_controller import ArtifactSelectionController


class ArtifactToolbarController:
    @staticmethod
    def current_artifact_identity(
        versions: list[object],
        *,
        tab_index: int,
        global_results_visible: bool,
    ) -> tuple[str, str, str]:
        return ArtifactSelectionController.selection_payload_for_tab(
            versions,
            tab_index=tab_index,
            global_results_visible=global_results_visible,
        )

    @staticmethod
    def copyable_text(selected_text: str, full_text: str) -> str:
        selected = str(selected_text or "")
        if selected:
            return selected
        return str(full_text or "")

    @staticmethod
    def export_request_payload(
        *,
        plugin_id: str,
        action_id: str,
        stage_id: str,
        alias: str,
        kind: str,
        text: str,
    ) -> tuple[str, str, str, str, str, str] | None:
        pid = str(plugin_id or "").strip()
        aid = str(action_id or "").strip()
        sid = str(stage_id or "").strip()
        alias_value = str(alias or "").strip()
        kind_value = str(kind or "").strip()
        body = str(text or "")
        if not pid or not aid or not sid or not alias_value or not kind_value or not body.strip():
            return None
        return pid, aid, sid, alias_value, kind_value, body

    @staticmethod
    def export_request_payload_for_tab(
        *,
        versions: list[object],
        tab_index: int,
        global_results_visible: bool,
        plugin_id: str,
        action_id: str,
        text: str,
    ) -> tuple[str, str, str, str, str, str] | None:
        stage_id, alias, kind = ArtifactToolbarController.current_artifact_identity(
            versions,
            tab_index=tab_index,
            global_results_visible=global_results_visible,
        )
        return ArtifactToolbarController.export_request_payload(
            plugin_id=plugin_id,
            action_id=action_id,
            stage_id=stage_id,
            alias=alias,
            kind=kind,
            text=text,
        )

    @staticmethod
    def export_controls_state(
        *,
        has_targets: bool,
        stage_id: str,
        alias: str,
        kind: str,
        text: str,
    ) -> dict[str, bool]:
        has_artifact = bool(str(stage_id or "").strip() and str(alias or "").strip() and str(kind or "").strip())
        has_text = bool(str(text or "").strip())
        return {
            "copy_enabled": has_text,
            "host_visible": bool(has_targets),
            "export_enabled": bool(has_artifact and has_text),
        }

    @staticmethod
    def export_controls_state_for_tab(
        *,
        versions: list[object],
        tab_index: int,
        global_results_visible: bool,
        has_targets: bool,
        text: str,
    ) -> dict[str, bool]:
        stage_id, alias, kind = ArtifactToolbarController.current_artifact_identity(
            versions,
            tab_index=tab_index,
            global_results_visible=global_results_visible,
        )
        return ArtifactToolbarController.export_controls_state(
            has_targets=has_targets,
            stage_id=stage_id,
            alias=alias,
            kind=kind,
            text=text,
        )
