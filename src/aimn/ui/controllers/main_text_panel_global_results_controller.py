from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from aimn.ui.controllers.main_text_panel_state_controller import MainTextPanelStateController


@dataclass(frozen=True)
class AppliedGlobalResultsState:
    query: str
    hits: list[dict]
    answer: str
    visible: bool
    rows: list[dict]
    changed: bool


class MainTextPanelGlobalResultsController:
    @staticmethod
    def apply_results(
        *,
        query: str,
        hits: list[dict],
        answer: str,
        build_rows: Callable[[str, list[dict]], list[dict]],
    ) -> AppliedGlobalResultsState:
        state = MainTextPanelStateController.build_global_results_state(
            query=query,
            hits=hits,
            answer=answer,
            build_rows=build_rows,
        )
        return AppliedGlobalResultsState(
            query=state.query,
            hits=list(state.hits),
            answer=state.answer,
            visible=bool(state.visible),
            rows=list(state.rows),
            changed=bool(state.query),
        )

    @staticmethod
    def clear_results(
        *,
        visible: bool,
        query: str,
        hits: list[dict],
        answer: str,
    ) -> AppliedGlobalResultsState:
        should_clear = MainTextPanelStateController.should_clear_global_results(
            visible=visible,
            query=query,
            hits=hits,
            answer=answer,
        )
        return AppliedGlobalResultsState(
            query="",
            hits=[],
            answer="",
            visible=False,
            rows=[],
            changed=bool(should_clear),
        )
