from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptManagementCreateOutcome:
    created: bool
    warning_title: str = ""
    warning_message: str = ""
    log_message: str = ""
    refresh_suggestions: bool = False


@dataclass(frozen=True)
class TranscriptManagementSuggestionOutcome:
    handled: bool
    create_outcome: TranscriptManagementCreateOutcome | None = None
    refresh_suggestions: bool = False


class TranscriptManagementFlowController:
    def __init__(
        self,
        *,
        store_factory: Callable[[], object],
        tr: Callable[[str, str], str],
        fmt: Callable[..., str],
    ) -> None:
        self._store_factory = store_factory
        self._tr = tr
        self._fmt = fmt

    @staticmethod
    def suggest_title(text: str, *, limit: int = 72) -> str:
        raw = str(text or "").replace("\u2029", "\n").strip()
        if not raw:
            return ""
        first = next((line.strip(" -*\t") for line in raw.splitlines() if line.strip()), raw)
        compact = " ".join(first.split())
        if len(compact) <= int(limit):
            return compact
        return compact[: max(12, int(limit) - 1)].rstrip() + "…"

    def run_create_request(
        self,
        *,
        entity_type: str,
        payload: dict,
        meeting_id: str,
        prompt_text: Callable[[str, str, str], tuple[str, bool]],
    ) -> TranscriptManagementCreateOutcome:
        etype = str(entity_type or "").strip().lower()
        if etype not in {"task", "project", "agenda"}:
            return TranscriptManagementCreateOutcome(created=False)

        active_meeting_id = str(meeting_id or "").strip()
        if not active_meeting_id:
            return TranscriptManagementCreateOutcome(
                created=False,
                warning_title=self._tr("management_create.no_meeting.title", "Management create failed"),
                warning_message=self._tr(
                    "management_create.no_meeting.message",
                    "Open a meeting before creating management entities.",
                ),
            )

        data = dict(payload or {})
        selected_text = str(data.get("selected_text", "") or "").replace("\u2029", "\n").strip()
        if not selected_text:
            return TranscriptManagementCreateOutcome(created=False)

        title_default = self.suggest_title(selected_text)
        dialog_title, dialog_prompt = self._prompt_copy(etype)
        entered_text, ok = prompt_text(dialog_title, dialog_prompt, title_default)
        value = str(entered_text or "").strip()
        if not ok or not value:
            return TranscriptManagementCreateOutcome(created=False)

        source_alias = str(data.get("alias", "") or "").strip()
        evidence = dict(data.get("evidence", {}) or {})
        source_kind = "transcript_selection"
        store = self._store_factory()
        try:
            if etype == "task":
                store.create_task(
                    title=value,
                    meeting_id=active_meeting_id,
                    source_kind=source_kind,
                    source_alias=source_alias,
                    original_text=selected_text,
                )
            elif etype == "project":
                store.create_project(
                    name=value,
                    description=selected_text,
                    meeting_id=active_meeting_id,
                    source_kind=source_kind,
                    source_alias=source_alias,
                    original_text=selected_text,
                )
            else:
                store.create_agenda(
                    title=value,
                    text=selected_text,
                    meeting_id=active_meeting_id,
                    source_kind=source_kind,
                    source_alias=source_alias,
                    original_text=selected_text,
                )
        finally:
            self._close_store(store)

        stage_id = str(data.get("stage_id", "") or "").strip()
        kind = str(data.get("kind", "") or "").strip()
        extra: list[str] = []
        if source_alias:
            extra.append(f"alias={source_alias}")
        if evidence:
            start_ms = int(evidence.get("start_ms") or 0)
            end_ms = int(evidence.get("end_ms") or start_ms)
            extra.append(f"{start_ms}-{end_ms}ms")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return TranscriptManagementCreateOutcome(
            created=True,
            log_message=self._fmt(
                "management_create.log.created",
                "Created {entity_type} from {kind}{suffix}",
                entity_type=etype,
                kind=kind or stage_id or "transcript",
                suffix=suffix,
            ),
            refresh_suggestions=True,
        )

    def run_suggestion_action(
        self,
        *,
        action: str,
        payload: dict,
        meeting_id: str,
        prompt_text: Callable[[str, str, str], tuple[str, bool]],
    ) -> TranscriptManagementSuggestionOutcome:
        action_value = str(action or "").strip().lower()
        data = dict(payload or {})
        suggestion_id = str(data.get("suggestion_id", "") or "").strip()

        if action_value in {"create_task", "create_project", "create_agenda"}:
            create_outcome = self.run_create_request(
                entity_type=action_value.split("_", 1)[1],
                payload={
                    "stage_id": str(data.get("stage_id", "") or "").strip(),
                    "alias": str(data.get("alias", "") or "").strip(),
                    "kind": str(data.get("kind", "") or "").strip(),
                    "selected_text": str(data.get("selected_text", "") or "").strip(),
                    "evidence": dict(data.get("evidence", {}) or {}),
                },
                meeting_id=meeting_id,
                prompt_text=prompt_text,
            )
            refresh_suggestions = False
            if create_outcome.created and suggestion_id:
                store = self._store_factory()
                try:
                    store.set_suggestion_state(suggestion_id, state="hidden")
                finally:
                    self._close_store(store)
                refresh_suggestions = True
            return TranscriptManagementSuggestionOutcome(
                handled=bool(create_outcome.created),
                create_outcome=create_outcome,
                refresh_suggestions=refresh_suggestions,
            )

        if not suggestion_id or action_value not in {"approve", "hide"}:
            return TranscriptManagementSuggestionOutcome(handled=False)

        store = self._store_factory()
        try:
            if action_value == "approve":
                store.approve_suggestion(suggestion_id)
            else:
                store.set_suggestion_state(suggestion_id, state="hidden")
        finally:
            self._close_store(store)
        return TranscriptManagementSuggestionOutcome(
            handled=True,
            refresh_suggestions=True,
        )

    def _prompt_copy(self, entity_type: str) -> tuple[str, str]:
        etype = str(entity_type or "").strip().lower()
        if etype == "task":
            return (
                self._tr("management_create.task_title", "Create task"),
                self._tr("management_create.task_prompt", "Task title:"),
            )
        if etype == "project":
            return (
                self._tr("management_create.project_title", "Create project"),
                self._tr("management_create.project_prompt", "Project name:"),
            )
        return (
            self._tr("management_create.agenda_title", "Create agenda"),
            self._tr("management_create.agenda_prompt", "Agenda title:"),
        )

    @staticmethod
    def _close_store(store: object) -> None:
        close = getattr(store, "close", None)
        if callable(close):
            close()
