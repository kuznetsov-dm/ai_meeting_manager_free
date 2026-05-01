import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.widgets.meetings_workspace_v2 import MainTextPanelV2  # noqa: E402


class TestMainTextPanelArtifactKindSwitch(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_inactive_kind_rows_can_switch_on_first_tab_click(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "")
        artifacts = [
            SimpleNamespace(kind="transcript", alias="v1", stage_id="transcription", relpath="a.txt"),
            SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing", relpath="b.txt"),
        ]
        panel.set_artifacts(artifacts, preferred_kind="transcript")

        summary_row = panel._kind_rows["summary"]
        transcript_row = panel._kind_rows["transcript"]

        # Clicking an already selected first tab on an inactive row must still switch active kind.
        summary_row._on_tab_clicked(0)
        self.assertEqual(panel._active_kind, "summary")

        transcript_row._on_tab_clicked(0)
        self.assertEqual(panel._active_kind, "transcript")

    def test_artifact_alias_buttons_wrap_to_multiple_rows_instead_of_scrolling(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "")
        artifacts = [
            SimpleNamespace(kind="summary", alias=f"version-{idx}", stage_id="llm_processing", relpath=f"{idx}.txt")
            for idx in range(1, 7)
        ]
        panel.set_artifacts(artifacts, preferred_kind="summary")

        summary_row = panel._kind_rows["summary"]
        buttons_host = summary_row.findChild(QWidget, "artifactKindTabBar")

        self.assertIsNotNone(buttons_host)
        assert buttons_host is not None
        layout = buttons_host.layout()
        self.assertIsNotNone(layout)
        assert layout is not None

        narrow_height = int(layout.heightForWidth(180))
        wide_height = int(layout.heightForWidth(1200))
        self.assertGreater(narrow_height, wide_height)

    def test_switching_artifact_tab_emits_active_version_signals(self) -> None:
        panel = MainTextPanelV2(lambda relpath: str(relpath))
        panel.set_artifacts(
            [
                SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing", relpath="1.txt"),
                SimpleNamespace(kind="summary", alias="v2", stage_id="llm_processing", relpath="2.txt"),
            ],
            preferred_kind="summary",
        )
        active_versions: list[tuple[str, str]] = []
        selections: list[tuple[str, str, str]] = []
        panel.activeVersionChanged.connect(lambda stage_id, alias: active_versions.append((stage_id, alias)))
        panel.artifactSelectionChanged.connect(
            lambda stage_id, alias, kind: selections.append((stage_id, alias, kind))
        )

        panel._tabs.setCurrentIndex(1)
        QApplication.processEvents()

        self.assertIn(("llm_processing", "v2"), active_versions)
        self.assertIn(("llm_processing", "v2", "summary"), selections)

    def test_kind_version_context_request_emits_selected_artifact_identity(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "")
        panel.set_artifacts(
            [
                SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing", relpath="1.txt"),
                SimpleNamespace(kind="summary", alias="v2", stage_id="llm_processing", relpath="2.txt"),
            ],
            preferred_kind="summary",
        )
        emitted: list[tuple[str, str, str, QPoint]] = []
        panel.artifactVersionContextRequested.connect(
            lambda stage_id, alias, kind, global_pos: emitted.append((stage_id, alias, kind, global_pos))
        )

        panel._on_kind_version_context_requested("summary", 1, QPoint(7, 9))

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][:3], ("llm_processing", "v2", "summary"))


if __name__ == "__main__":
    unittest.main()
