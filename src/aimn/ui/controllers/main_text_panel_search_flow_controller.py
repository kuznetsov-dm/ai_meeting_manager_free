from __future__ import annotations

from aimn.ui.controllers.search_action_controller import SearchActionController
from aimn.ui.controllers.search_mode_controller import SearchModeController


class MainTextPanelSearchFlowController:
    @staticmethod
    def highlight_request(query: str) -> tuple[bool, str, str]:
        should_highlight, normalized_query = SearchActionController.highlight_decision(query)
        return should_highlight, normalized_query, "local"

    @staticmethod
    def mode_ui_state(*, mode: str, has_matches: bool, global_results_visible: bool) -> dict[str, object]:
        return SearchModeController.ui_state(
            mode=mode,
            has_matches=has_matches,
            global_results_visible=global_results_visible,
        )

    @staticmethod
    def submit_request(*, mode: str, query: str) -> tuple[str, str]:
        return SearchActionController.submit_decision(mode=mode, query=query)

    @staticmethod
    def clear_request(*, mode: str, query: str) -> tuple[str, bool]:
        return SearchActionController.clear_decision(mode=mode, query=query)
