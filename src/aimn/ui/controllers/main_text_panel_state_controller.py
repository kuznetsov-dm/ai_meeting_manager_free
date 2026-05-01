from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalResultsState:
    query: str
    hits: list[dict]
    answer: str
    visible: bool
    rows: list[dict]


@dataclass(frozen=True)
class KindActivationState:
    active_kind: str
    versions: list[object]
    changed: bool
    update_selection_only: bool


class MainTextPanelStateController:
    @staticmethod
    def build_global_results_state(
        *,
        query: str,
        hits: Sequence[dict] | None,
        answer: str = "",
        build_rows: Callable[[str, list[dict]], list[dict]],
    ) -> GlobalResultsState:
        normalized_query = str(query or "").strip()
        normalized_hits = [dict(item) for item in list(hits or []) if isinstance(item, dict)]
        normalized_answer = str(answer or "")
        if not normalized_query:
            return GlobalResultsState(
                query="",
                hits=[],
                answer="",
                visible=False,
                rows=[],
            )
        return GlobalResultsState(
            query=normalized_query,
            hits=normalized_hits,
            answer=normalized_answer,
            visible=True,
            rows=list(build_rows(normalized_query, normalized_hits)),
        )

    @staticmethod
    def should_clear_global_results(
        *,
        visible: bool,
        query: str,
        hits: Sequence[dict] | None,
        answer: str,
    ) -> bool:
        return bool(visible or str(query or "").strip() or list(hits or []) or str(answer or "").strip())

    @staticmethod
    def activate_kind(
        *,
        selected_kind: str,
        kinds: Sequence[str],
        active_kind: str,
        artifacts_by_kind: Mapping[str, Sequence[object]] | None,
    ) -> KindActivationState:
        selected = str(selected_kind or "").strip()
        available = [str(kind or "").strip() for kind in (kinds or []) if str(kind or "").strip()]
        current_active = str(active_kind or "").strip()
        if not selected or selected not in available:
            return KindActivationState(
                active_kind=current_active,
                versions=list((artifacts_by_kind or {}).get(current_active, []) or []),
                changed=False,
                update_selection_only=False,
            )
        versions = list((artifacts_by_kind or {}).get(selected, []) or [])
        if selected == current_active and versions:
            return KindActivationState(
                active_kind=selected,
                versions=versions,
                changed=False,
                update_selection_only=True,
            )
        return KindActivationState(
            active_kind=selected,
            versions=versions,
            changed=True,
            update_selection_only=False,
        )

    @staticmethod
    def kind_version_tab_index(*, global_results_visible: bool, version_index: int) -> int:
        base = 1 if bool(global_results_visible) else 0
        return base + int(version_index)
