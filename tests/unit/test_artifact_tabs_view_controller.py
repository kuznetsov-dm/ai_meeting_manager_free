# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel, QTabWidget

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.artifact_tabs_view_controller import ArtifactTabsViewController


class TestArtifactTabsViewController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_rebuild_tabs_materializes_results_and_artifact_tabs(self) -> None:
        tabs = QTabWidget()
        versions = [SimpleNamespace(stage_id="transcription", alias="T05", relpath="a.txt")]

        ArtifactTabsViewController.rebuild_tabs(
            tabs,
            versions=versions,
            global_results_visible=True,
            results_title="Search Results",
            text_title="Text",
            pinned_aliases={"transcription": "T05"},
            active_aliases={"transcription": "T05"},
            previous_title="",
            prefer_results=False,
            make_results_view=lambda: QLabel("results"),
            make_text_view=lambda: QLabel("text"),
            make_artifact_view=lambda art: QLabel(str(getattr(art, "alias", ""))),
            set_tab_tooltip=lambda index, tooltip: tabs.setTabToolTip(index, tooltip),
        )

        self.assertEqual(tabs.count(), 2)
        self.assertEqual(tabs.tabText(0), "Search Results")
        self.assertIn("T05", tabs.tabText(1))
        self.assertIn("transcription:T05", tabs.tabToolTip(1))

    def test_rebuild_tabs_prefers_results_when_requested(self) -> None:
        tabs = QTabWidget()
        versions = [SimpleNamespace(stage_id="transcription", alias="T05", relpath="a.txt")]

        target = ArtifactTabsViewController.rebuild_tabs(
            tabs,
            versions=versions,
            global_results_visible=True,
            results_title="Search Results",
            text_title="Text",
            pinned_aliases={},
            active_aliases={},
            previous_title="T05",
            prefer_results=True,
            make_results_view=lambda: QLabel("results"),
            make_text_view=lambda: QLabel("text"),
            make_artifact_view=lambda art: QLabel(str(getattr(art, "alias", ""))),
        )

        self.assertEqual(target, 0)
        self.assertEqual(tabs.currentIndex(), 0)


if __name__ == "__main__":
    unittest.main()
