from __future__ import annotations

from dataclasses import dataclass

from aimn.ui.controllers.transcript_interaction_controller import TranscriptInteractionController


@dataclass(frozen=True)
class TranscriptMenuActionSpec:
    action_name: str
    label_key: str
    default_label: str


@dataclass(frozen=True)
class TranscriptMenuBundle:
    payload: dict[str, object]
    action_specs: tuple[TranscriptMenuActionSpec, ...]
    separator_indexes: tuple[int, ...] = ()


class TranscriptMenuController:
    @staticmethod
    def selection_action_specs() -> list[TranscriptMenuActionSpec]:
        return [
            TranscriptMenuActionSpec("task", "transcript.menu.create_task", "Create task from selection"),
            TranscriptMenuActionSpec("project", "transcript.menu.create_project", "Create project from selection"),
            TranscriptMenuActionSpec("agenda", "transcript.menu.create_agenda", "Create agenda from selection"),
        ]

    @staticmethod
    def suggestion_action_specs() -> list[TranscriptMenuActionSpec]:
        return [
            TranscriptMenuActionSpec(
                "approve",
                "transcript.menu.approve_suggestion",
                "Approve highlighted suggestion",
            ),
            TranscriptMenuActionSpec(
                "hide",
                "transcript.menu.hide_suggestion",
                "Hide highlighted suggestion",
            ),
            TranscriptMenuActionSpec(
                "create_task",
                "transcript.menu.create_task_highlight",
                "Create task from highlight",
            ),
            TranscriptMenuActionSpec(
                "create_project",
                "transcript.menu.create_project_highlight",
                "Create project from highlight",
            ),
            TranscriptMenuActionSpec(
                "create_agenda",
                "transcript.menu.create_agenda_highlight",
                "Create agenda from highlight",
            ),
        ]

    @staticmethod
    def selection_menu_bundle(
        *,
        stage_id: str,
        alias: str,
        kind: str,
        selected_text: str,
        evidence: dict[str, object] | None,
    ) -> TranscriptMenuBundle | None:
        text = str(selected_text or "").strip()
        if not text:
            return None
        return TranscriptMenuBundle(
            payload=TranscriptInteractionController.transcript_selection_payload(
                stage_id=stage_id,
                alias=alias,
                kind=kind,
                selected_text=text,
                evidence=evidence,
            ),
            action_specs=tuple(TranscriptMenuController.selection_action_specs()),
        )

    @staticmethod
    def suggestion_menu_bundle(
        *,
        suggestion_id: str,
        suggestion_kind: str,
        selected_text: str,
        stage_id: str,
        alias: str,
        kind: str,
        evidence: dict[str, object] | None,
    ) -> TranscriptMenuBundle | None:
        sid = str(suggestion_id or "").strip()
        skind = str(suggestion_kind or "").strip()
        text = str(selected_text or "").strip()
        if not sid or not skind or not text:
            return None
        return TranscriptMenuBundle(
            payload=TranscriptInteractionController.transcript_suggestion_payload(
                suggestion_id=sid,
                suggestion_kind=skind,
                selected_text=text,
                stage_id=stage_id,
                alias=alias,
                kind=kind,
                evidence=evidence,
            ),
            action_specs=tuple(TranscriptMenuController.suggestion_action_specs()),
            separator_indexes=(2,),
        )
