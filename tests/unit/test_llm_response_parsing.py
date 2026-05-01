import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestLlmResponseParsing(unittest.TestCase):
    def test_openrouter_extracts_text_from_string_content(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        payload = {
            "choices": [
                {
                    "message": {
                        "content": "  summary text  ",
                    }
                }
            ]
        }
        self.assertEqual(openrouter._extract_message_text(payload), "summary text")

    def test_openrouter_extracts_text_from_content_blocks(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "output_text", "text": "line one"},
                            {"type": "text", "text": "line two"},
                        ]
                    }
                }
            ]
        }
        self.assertEqual(openrouter._extract_message_text(payload), "line one\nline two")

    def test_zai_extracts_text_from_string_content(self) -> None:
        import plugins.llm.zai.zai as zai

        payload = {
            "choices": [
                {
                    "message": {
                        "content": "  summary text  ",
                    }
                }
            ]
        }
        self.assertEqual(zai._extract_message_text(payload), "summary text")

    def test_zai_extracts_text_from_content_blocks(self) -> None:
        import plugins.llm.zai.zai as zai

        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "output_text", "text": "line one"},
                            {"type": "text", "text": "line two"},
                        ]
                    }
                }
            ]
        }
        self.assertEqual(zai._extract_message_text(payload), "line one\nline two")


if __name__ == "__main__":
    unittest.main()

