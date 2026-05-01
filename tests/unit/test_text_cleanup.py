import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.services.text_cleanup import cleanup_transcript  # noqa: E402


class TestTextCleanup(unittest.TestCase):
    def test_removes_excess_duplicate_lines(self) -> None:
        text = "Hello\nHello\nHello\nHello\n"
        cleaned, stats = cleanup_transcript(text)
        self.assertIn("Hello", cleaned)
        self.assertLessEqual(cleaned.splitlines().count("Hello"), 2)
        self.assertGreaterEqual(stats["lines_removed"], 1)

    def test_removes_duplicate_sentences(self) -> None:
        text = "Yes. Yes. Yes. Done."
        cleaned, stats = cleanup_transcript(text)
        self.assertIn("Yes.", cleaned)
        self.assertIn("Done.", cleaned)
        self.assertGreaterEqual(stats["sentences_removed"], 1)

    def test_keeps_non_empty(self) -> None:
        text = "One sentence."
        cleaned, stats = cleanup_transcript(text)
        self.assertEqual(cleaned, "One sentence.")
        self.assertEqual(stats["lines_removed"], 0)


if __name__ == "__main__":
    unittest.main()
