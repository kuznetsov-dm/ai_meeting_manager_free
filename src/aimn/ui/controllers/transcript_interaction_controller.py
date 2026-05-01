from __future__ import annotations

from aimn.ui.controllers.transcript_evidence_controller import safe_int


class TranscriptInteractionController:
    @staticmethod
    def global_search_open_args(payload: dict) -> tuple[str, str, str, str, int, int] | None:
        if not isinstance(payload, dict):
            return None
        meeting_id = str(payload.get("meeting_id", "") or "").strip()
        stage_id = str(payload.get("stage_id", "") or "").strip()
        alias = str(payload.get("alias", "") or "").strip()
        kind = str(payload.get("kind", "") or "").strip()
        if not meeting_id or not kind:
            return None
        return (
            meeting_id,
            stage_id,
            alias,
            kind,
            safe_int(payload.get("segment_index"), -1),
            safe_int(payload.get("start_ms"), -1),
        )

    @staticmethod
    def transcript_selection_payload(
        *,
        stage_id: str,
        alias: str,
        kind: str,
        selected_text: str,
        evidence: dict[str, object] | None,
    ) -> dict[str, object]:
        return {
            "stage_id": str(stage_id or "").strip(),
            "alias": str(alias or "").strip(),
            "kind": str(kind or "").strip(),
            "selected_text": str(selected_text or "").strip(),
            "evidence": dict(evidence or {}),
        }

    @staticmethod
    def transcript_suggestion_payload(
        *,
        suggestion_id: str,
        suggestion_kind: str,
        selected_text: str,
        stage_id: str,
        alias: str,
        kind: str,
        evidence: dict[str, object] | None,
    ) -> dict[str, object]:
        return {
            "suggestion_id": str(suggestion_id or "").strip(),
            "suggestion_kind": str(suggestion_kind or "").strip(),
            "selected_text": str(selected_text or "").strip(),
            "stage_id": str(stage_id or "").strip(),
            "alias": str(alias or "").strip(),
            "kind": str(kind or "").strip(),
            "evidence": dict(evidence or {}),
        }
