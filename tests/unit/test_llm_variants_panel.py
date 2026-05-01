import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.widgets.variants_panels import LlmVariantsPanel  # noqa: E402


class TestLlmVariantsPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_refresh_button_follows_refreshable_provider_and_emits_selected_provider(self) -> None:
        panel = LlmVariantsPanel()
        stage = SimpleNamespace(
            current_settings={"prompt_profile": "standard", "prompt_custom": ""},
            ui_metadata={
                "available_providers": [("llm.openrouter", "OpenRouter"), ("llm.deepseek", "DeepSeek")],
                "provider_models": {
                    "llm.openrouter": [{"label": "Model A", "model_id": "m-a"}],
                    "llm.deepseek": [{"label": "Model B", "model_id": "m-b"}],
                },
                "enabled_models": {"llm.openrouter": ["id:m-a"]},
                "selected_provider": "llm.openrouter",
                "refreshable_providers": ["llm.openrouter"],
            },
        )
        captured: list[str] = []
        panel.refreshModelsRequested.connect(captured.append)

        panel.apply_stage(stage)

        self.assertFalse(panel._refresh_models_btn.isHidden())  # noqa: SLF001
        self.assertTrue(panel._refresh_models_btn.isEnabled())  # noqa: SLF001
        self.assertIn("All available models appear here.", panel._models_note.text())  # noqa: SLF001

        panel._refresh_models_btn.click()  # noqa: SLF001
        self.assertEqual(captured, ["llm.openrouter"])

        panel.select_provider("llm.deepseek")
        self.assertTrue(panel._refresh_models_btn.isHidden())  # noqa: SLF001
        self.assertIn("Add or download more models in Settings.", panel._models_note.text())  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
