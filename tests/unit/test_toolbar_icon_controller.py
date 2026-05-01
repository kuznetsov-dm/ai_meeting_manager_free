import sys
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.toolbar_icon_controller import ToolbarIconController  # noqa: E402


class TestToolbarIconController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_command_button_specs_cover_expected_buttons(self) -> None:
        specs = ToolbarIconController.command_button_specs()
        self.assertEqual(specs[0].button_name, "_find_btn")
        self.assertEqual(specs[-1].button_name, "_btn_stop")
        self.assertEqual(len(specs), 9)

    def test_toolbar_icon_color_uses_theme_and_palette(self) -> None:
        self.assertEqual(ToolbarIconController.toolbar_icon_color(theme_id="dark_modern", palette_lightness=200).name(), "#e5edf8")
        self.assertEqual(ToolbarIconController.toolbar_icon_color(theme_id="light_modern", palette_lightness=10).name(), "#334155")
        self.assertEqual(ToolbarIconController.toolbar_icon_color(theme_id="", palette_lightness=10).name(), "#e5edf8")
        self.assertEqual(ToolbarIconController.toolbar_icon_color(theme_id="", palette_lightness=220).name(), "#334155")

    def test_export_target_glyph_falls_back_to_e(self) -> None:
        self.assertEqual(ToolbarIconController.export_target_glyph("Alpha"), "A")
        self.assertEqual(ToolbarIconController.export_target_glyph(" 3D Export"), "3")
        self.assertEqual(ToolbarIconController.export_target_glyph("..."), "E")

    def test_draw_toolbar_icon_returns_non_null_icon(self) -> None:
        icon = ToolbarIconController.draw_toolbar_icon(
            "target",
            color=ToolbarIconController.toolbar_icon_color(theme_id="", palette_lightness=220),
            glyph="A",
            icon_size=24,
        )
        self.assertFalse(icon.isNull())


if __name__ == "__main__":
    unittest.main()
