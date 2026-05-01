from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from aimn.ui.controllers.artifact_tab_navigation_controller import ArtifactTabNavigationController


@dataclass(frozen=True)
class ArtifactPinMenuAction:
    action: str
    label: str
    stage_id: str
    alias: str = ""


class ArtifactSelectionController:
    @staticmethod
    def selected_artifact(
        versions: Sequence[object],
        *,
        version_index: int | None,
    ) -> object | None:
        if version_index is None:
            return None
        idx = int(version_index)
        if idx < 0 or idx >= len(list(versions or [])):
            return None
        return list(versions or [])[idx]

    @staticmethod
    def selection_payload(artifact: object | None) -> tuple[str, str, str]:
        if artifact is None:
            return "", "", ""
        stage_id = str(getattr(artifact, "stage_id", "") or "").strip()
        alias = str(getattr(artifact, "alias", "") or "").strip()
        kind = str(getattr(artifact, "kind", "") or "").strip()
        return stage_id, alias, kind

    @staticmethod
    def selected_artifact_for_tab(
        versions: Sequence[object],
        *,
        tab_index: int,
        global_results_visible: bool,
    ) -> object | None:
        return ArtifactSelectionController.selected_artifact(
            versions,
            version_index=ArtifactTabNavigationController.tab_to_version_index(
                int(tab_index),
                global_results_visible=global_results_visible,
                versions_count=len(list(versions or [])),
            ),
        )

    @staticmethod
    def selection_payload_for_tab(
        versions: Sequence[object],
        *,
        tab_index: int,
        global_results_visible: bool,
    ) -> tuple[str, str, str]:
        artifact = ArtifactSelectionController.selected_artifact_for_tab(
            versions,
            tab_index=tab_index,
            global_results_visible=global_results_visible,
        )
        return ArtifactSelectionController.selection_payload(artifact)

    @staticmethod
    def pin_menu_actions(
        artifact: object | None,
        *,
        pinned_aliases: Mapping[str, str] | None = None,
    ) -> list[ArtifactPinMenuAction]:
        stage_id, alias, _kind = ArtifactSelectionController.selection_payload(artifact)
        if not stage_id or not alias:
            return []
        pinned_alias = str(dict(pinned_aliases or {}).get(stage_id, "") or "")
        if pinned_alias == alias:
            return [ArtifactPinMenuAction(action="unpin", label=f"Unpin {stage_id}", stage_id=stage_id)]
        actions = [
            ArtifactPinMenuAction(
                action="pin",
                label=f"Pin this version for {stage_id}",
                stage_id=stage_id,
                alias=alias,
            )
        ]
        if pinned_alias:
            actions.append(
                ArtifactPinMenuAction(
                    action="unpin",
                    label=f"Unpin {stage_id} (current)",
                    stage_id=stage_id,
                )
            )
        return actions

    @staticmethod
    def pin_menu_actions_for_tab(
        versions: Sequence[object],
        *,
        tab_index: int,
        global_results_visible: bool,
        pinned_aliases: Mapping[str, str] | None = None,
    ) -> list[ArtifactPinMenuAction]:
        artifact = ArtifactSelectionController.selected_artifact_for_tab(
            versions,
            tab_index=tab_index,
            global_results_visible=global_results_visible,
        )
        return ArtifactSelectionController.pin_menu_actions(
            artifact,
            pinned_aliases=pinned_aliases,
        )

    @staticmethod
    def kind_version_context_payload(
        artifacts_by_kind: Mapping[str, Sequence[object]] | None,
        *,
        kind: str,
        version_index: int,
    ) -> tuple[str, str, str]:
        selected_kind = str(kind or "").strip()
        if not selected_kind:
            return "", "", ""
        versions = list(dict(artifacts_by_kind or {}).get(selected_kind, []) or [])
        idx = int(version_index)
        if idx < 0 or idx >= len(versions):
            return "", "", ""
        stage_id, alias, kind_value = ArtifactSelectionController.selection_payload(versions[idx])
        if not stage_id or not alias:
            return "", "", ""
        return stage_id, alias, kind_value or selected_kind
