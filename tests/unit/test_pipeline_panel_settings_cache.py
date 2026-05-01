# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLineEdit

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.tabs.contracts import StageViewModel  # noqa: E402
from aimn.ui.widgets.meetings_workspace_v2 import PipelinePanelV2  # noqa: E402


class _FakeSettingsService:
    def selected_plugin(self, _stage_id: str) -> str:
        return "plugin.fake"

    def stage_plugin_options(self, _stage_id: str) -> list[tuple[str, str]]:
        return [("plugin.fake", "Fake provider")]

    def build_custom_panel(self, _stage_id: str, _parent):
        return None

    def build_field_widget(self, _field, value):
        widget = QLineEdit()
        widget.setText(str(value or ""))
        return widget

    def attach_change_handler(self, _widget, _handler) -> None:
        return

    def collect_widget_values(self, _fields) -> dict:
        return {}


def _stage(stage_id: str, *, ui_metadata: dict | None = None) -> StageViewModel:
    return StageViewModel(
        stage_id=stage_id,
        display_name=stage_id,
        short_name=stage_id,
        status="idle",
        progress=None,
        is_enabled=True,
        is_dirty=False,
        is_blocked=False,
        plugin_id="plugin.fake",
        plugin_options=[],
        inline_settings_keys=[],
        settings_schema=[],
        current_settings={},
        effective_settings={},
        ui_metadata=dict(ui_metadata or {}),
        artifacts=[],
        can_run=True,
        can_rerun=True,
    )


class TestPipelinePanelSettingsCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_open_settings_reuses_stage_tab(self) -> None:
        panel = PipelinePanelV2(_FakeSettingsService())
        stage = _stage("transcription")

        panel.open_settings(stage)
        first_tab = panel._settings_tabs.get("transcription")
        self.assertIsNotNone(first_tab)
        self.assertEqual(len(panel._settings_tabs), 1)

        panel.open_settings(stage)
        second_tab = panel._settings_tabs.get("transcription")

        self.assertIs(first_tab, second_tab)
        self.assertEqual(len(panel._settings_tabs), 1)

    def test_stage_settings_signature_tracks_ui_metadata_changes(self) -> None:
        base = _stage("llm_processing")
        changed = _stage(
            "llm_processing",
            ui_metadata={
                "provider_models": {"llm.openrouter": [{"model_id": "m1", "label": "Model 1"}]},
            },
        )

        first = PipelinePanelV2._stage_settings_signature(base)
        second = PipelinePanelV2._stage_settings_signature(changed)

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
