# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.main_text_panel_state_controller import (
    GlobalResultsState,
    KindActivationState,
    MainTextPanelStateController,
)


class TestMainTextPanelStateController(unittest.TestCase):
    def test_build_global_results_state_returns_visible_rows_for_query(self) -> None:
        state = MainTextPanelStateController.build_global_results_state(
            query="roadmap",
            hits=[{"meeting_id": "m1"}],
            answer="answer",
            build_rows=lambda query, hits: [{"query": query, "count": len(hits)}],
        )

        self.assertEqual(
            state,
            GlobalResultsState(
                query="roadmap",
                hits=[{"meeting_id": "m1"}],
                answer="answer",
                visible=True,
                rows=[{"query": "roadmap", "count": 1}],
            ),
        )

    def test_activate_kind_reports_selection_only_for_same_active_kind(self) -> None:
        state = MainTextPanelStateController.activate_kind(
            selected_kind="summary",
            kinds=["transcript", "summary"],
            active_kind="summary",
            artifacts_by_kind={"summary": [SimpleNamespace(alias="v1")]},
        )

        self.assertEqual(
            state,
            KindActivationState(
                active_kind="summary",
                versions=[SimpleNamespace(alias="v1")],
                changed=False,
                update_selection_only=True,
            ),
        )

    def test_kind_version_tab_index_accounts_for_results_tab(self) -> None:
        self.assertEqual(
            MainTextPanelStateController.kind_version_tab_index(
                global_results_visible=True,
                version_index=2,
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()
