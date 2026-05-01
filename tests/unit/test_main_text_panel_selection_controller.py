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

from aimn.ui.controllers.main_text_panel_selection_controller import MainTextPanelSelectionController  # noqa: E402


class TestMainTextPanelSelectionController(unittest.TestCase):
    def test_activate_kind_selection_returns_tab_target_for_version_click(self) -> None:
        artifacts_by_kind = {
            "summary": [
                SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing"),
                SimpleNamespace(kind="summary", alias="v2", stage_id="llm_processing"),
            ]
        }

        state = MainTextPanelSelectionController.activate_kind_selection(
            kind="summary",
            kinds=["summary"],
            active_kind="summary",
            artifacts_by_kind=artifacts_by_kind,
            version_index=1,
            global_results_visible=False,
        )

        self.assertEqual(state.active_kind, "summary")
        self.assertEqual(state.target_tab_index, 1)
        self.assertTrue(state.emit_selection)
        self.assertTrue(state.update_kind_rows_only)

    def test_current_selection_payload_reads_selection_for_tab(self) -> None:
        payload = MainTextPanelSelectionController.current_selection_payload(
            versions=[SimpleNamespace(kind="summary", alias="v2", stage_id="llm_processing")],
            tab_index=0,
            global_results_visible=False,
        )

        self.assertEqual(payload, ("llm_processing", "v2", "summary"))


if __name__ == "__main__":
    unittest.main()
