import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from aimn.core.lineage import alias_code_for_stage, stage_alias_prefix  # noqa: E402


class TestLineageAliasLlm(unittest.TestCase):
    def test_llm_stage_prefix_is_ai(self) -> None:
        self.assertEqual(stage_alias_prefix("llm_processing"), "ai")

    def test_llm_alias_code_contains_provider_and_model(self) -> None:
        code = alias_code_for_stage(
            "llm_processing",
            {
                "plugin_id": "llm.openrouter",
                "model_id": "meta-llama/llama-3.3-70b-instruct:free",
            },
        )
        self.assertTrue(code.startswith("or"))
        self.assertLessEqual(len(code), 6)

    def test_llm_alias_code_for_llama_model_path(self) -> None:
        code = alias_code_for_stage(
            "llm_processing",
            {
                "plugin_id": "llm.llama_cli",
                "model_path": "models/llama/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            },
        )
        self.assertTrue(code.startswith("lm"))
        self.assertIn("tl", code)

    def test_llm_alias_code_for_deepseek_chat_is_short(self) -> None:
        code = alias_code_for_stage(
            "llm_processing",
            {
                "plugin_id": "llm.deepseek",
                "model_id": "deepseek-chat",
            },
        )
        self.assertEqual(code, "dsch")


if __name__ == "__main__":
    unittest.main()
