from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QTextCursor

from aimn.ui.controllers.text_search_highlight_controller import TextSearchHighlightController


@dataclass(frozen=True)
class LocalSearchResetPlan:
    clear_query: bool
    matches_text: str
    prev_enabled: bool
    next_enabled: bool
    clear_search_layer: bool
    clear_focus_layer: bool


@dataclass(frozen=True)
class LocalSearchRunResult:
    match_cursors: list[QTextCursor]
    match_index: int
    matches_text: str
    prev_enabled: bool
    next_enabled: bool
    highlight_count: int


@dataclass(frozen=True)
class LocalSearchStepResult:
    match_index: int
    matches_text: str


class LocalSearchFlowController:
    @staticmethod
    def reset_plan(
        *,
        clear_query: bool,
        is_local_mode: bool,
        global_results_visible: bool,
        current_tab_index: int,
    ) -> LocalSearchResetPlan:
        preserve_global_results_highlights = (
            (not is_local_mode)
            and bool(global_results_visible)
            and int(current_tab_index) == 0
        )
        return LocalSearchResetPlan(
            clear_query=bool(clear_query),
            matches_text="" if is_local_mode else "",
            prev_enabled=False,
            next_enabled=False,
            clear_search_layer=not preserve_global_results_highlights,
            clear_focus_layer=not preserve_global_results_highlights,
        )

    @staticmethod
    def run_search(editor: object, query: str, *, no_matches_text: str = "0 matches") -> LocalSearchRunResult:
        text = str(getattr(editor, "toPlainText", lambda: "")() or "")
        if not text:
            return LocalSearchRunResult(
                match_cursors=[],
                match_index=-1,
                matches_text=str(no_matches_text or "0 matches"),
                prev_enabled=False,
                next_enabled=False,
                highlight_count=0,
            )
        match_cursors = TextSearchHighlightController.build_match_cursors(editor, str(query or "").strip())
        if not match_cursors:
            return LocalSearchRunResult(
                match_cursors=[],
                match_index=-1,
                matches_text=str(no_matches_text or "0 matches"),
                prev_enabled=False,
                next_enabled=False,
                highlight_count=0,
            )
        match_index = 0
        outcome = TextSearchHighlightController.apply_match_selection(
            editor,
            match_cursors,
            match_index,
        )
        matches_text = ""
        if outcome:
            current, total = outcome
            matches_text = f"{current}/{total}"
        selections = TextSearchHighlightController.build_search_highlight_selections(editor, match_cursors)
        return LocalSearchRunResult(
            match_cursors=match_cursors,
            match_index=match_index,
            matches_text=matches_text,
            prev_enabled=True,
            next_enabled=True,
            highlight_count=len(selections),
        )

    @staticmethod
    def step_match(editor: object, match_cursors: list[QTextCursor], match_index: int, delta: int) -> LocalSearchStepResult | None:
        if not match_cursors:
            return None
        next_index = TextSearchHighlightController.next_match_index(
            match_index,
            len(match_cursors),
            delta,
        )
        outcome = TextSearchHighlightController.apply_match_selection(
            editor,
            match_cursors,
            next_index,
        )
        if not outcome:
            return None
        current, total = outcome
        return LocalSearchStepResult(
            match_index=next_index,
            matches_text=f"{current}/{total}",
        )
