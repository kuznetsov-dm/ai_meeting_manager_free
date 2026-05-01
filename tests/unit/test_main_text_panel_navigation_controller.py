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

from aimn.ui.controllers.main_text_panel_navigation_controller import MainTextPanelNavigationController  # noqa: E402


class TestMainTextPanelNavigationController(unittest.TestCase):
    def test_alias_tab_index_resolves_matching_alias(self) -> None:
        versions = [
            SimpleNamespace(alias="v1", stage_id="s1", kind="summary"),
            SimpleNamespace(alias="v2", stage_id="s1", kind="summary"),
        ]
        self.assertEqual(
            MainTextPanelNavigationController.alias_tab_index(
                versions=versions,
                global_results_visible=False,
                alias="v2",
            ),
            1,
        )

    def test_version_tab_index_resolves_stage_alias_kind(self) -> None:
        versions = [
            SimpleNamespace(alias="v1", stage_id="s1", kind="summary"),
            SimpleNamespace(alias="v2", stage_id="s2", kind="transcript"),
        ]
        self.assertEqual(
            MainTextPanelNavigationController.version_tab_index(
                versions=versions,
                global_results_visible=False,
                stage_id="s2",
                alias="v2",
                kind="transcript",
            ),
            1,
        )

    def test_transcript_row_index_prefers_matching_segment_index(self) -> None:
        payloads = [
            {"segment_index": 0, "start_ms": 0},
            {"segment_index": 1, "start_ms": 1200},
        ]
        self.assertEqual(
            MainTextPanelNavigationController.transcript_row_index(
                payloads=payloads,
                segment_index=1,
                start_ms=-1,
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
