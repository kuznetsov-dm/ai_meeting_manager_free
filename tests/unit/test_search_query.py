import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.search_query import normalize_search_query, query_variants


class TestSearchQuery(unittest.TestCase):
    def test_normalize_search_query_replaces_qtextedit_separators(self) -> None:
        value = "alpha\u2029beta\xa0gamma"

        normalized = normalize_search_query(value)

        self.assertEqual(normalized, "alpha beta gamma")

    def test_normalize_search_query_removes_zero_width_marks(self) -> None:
        value = "copy\u200bpaste"

        normalized = normalize_search_query(value)

        self.assertEqual(normalized, "copypaste")

    def test_query_variants_use_normalized_query(self) -> None:
        variants = query_variants("launch\u2029memo")

        self.assertIn("launch memo", variants)


if __name__ == "__main__":
    unittest.main()
