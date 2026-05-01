import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestLlmTimeoutCoercion(unittest.TestCase):
    def test_string_timeout_is_coerced_to_int(self) -> None:
        from plugins.llm.deepseek.deepseek import DeepSeekPlugin
        from plugins.llm.openrouter.openrouter import OpenRouterPlugin
        from plugins.llm.zai.zai import ZaiPlugin

        self.assertEqual(ZaiPlugin(timeout_seconds="60").timeout_seconds, 60)
        self.assertEqual(OpenRouterPlugin(timeout_seconds="45").timeout_seconds, 45)
        self.assertEqual(DeepSeekPlugin(timeout_seconds="30").timeout_seconds, 30)

    def test_invalid_timeout_falls_back_to_default(self) -> None:
        from plugins.llm.deepseek.deepseek import DeepSeekPlugin
        from plugins.llm.openrouter.openrouter import OpenRouterPlugin
        from plugins.llm.zai.zai import ZaiPlugin

        self.assertEqual(ZaiPlugin(timeout_seconds="bad").timeout_seconds, 60)
        self.assertEqual(OpenRouterPlugin(timeout_seconds=None).timeout_seconds, 60)
        self.assertEqual(DeepSeekPlugin(timeout_seconds="0").timeout_seconds, 60)


if __name__ == "__main__":
    unittest.main()


