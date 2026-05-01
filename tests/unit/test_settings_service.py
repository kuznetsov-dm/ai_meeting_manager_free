import sys
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.services.settings_service import PipelineSettingsUiService
from aimn.ui.tabs.contracts import SettingField, SettingOption


class TestSettingsService(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_multi_select_field_uses_checklist_and_collects_csv(self) -> None:
        field = SettingField(
            key="prompt_project_ids",
            label="Projects",
            value="",
            options=[
                SettingOption(label="Project One", value="p1"),
                SettingOption(label="Project Two", value="p2"),
            ],
            editable=False,
            multi_select=True,
        )

        widget = PipelineSettingsUiService.build_field_widget(field, "p1")
        self.assertIsInstance(widget, QListWidget)

        first = widget.item(0)
        second = widget.item(1)
        self.assertEqual(first.checkState(), Qt.Checked)
        self.assertEqual(second.checkState(), Qt.Unchecked)

        second.setCheckState(Qt.Checked)
        values = PipelineSettingsUiService.collect_widget_values({"prompt_project_ids": widget})
        self.assertEqual(values.get("prompt_project_ids"), "p1,p2")

        PipelineSettingsUiService.apply_widget_value(widget, "p2")
        values_after = PipelineSettingsUiService.collect_widget_values({"prompt_project_ids": widget})
        self.assertEqual(values_after.get("prompt_project_ids"), "p2")


if __name__ == "__main__":
    unittest.main()
