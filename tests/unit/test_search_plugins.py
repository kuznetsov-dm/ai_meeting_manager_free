import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from plugins.search.simple import simple as simple_plugin  # noqa: E402
from plugins.search.smart import smart as semantic_smart_plugin  # noqa: E402
from plugins.search.smart_legacy import smart_legacy as smart_legacy_plugin  # noqa: E402


def _hit(*, meeting_id: str = "m1") -> SimpleNamespace:
    return SimpleNamespace(
        meeting_id=meeting_id,
        alias="a1",
        stage_id="meeting",
        kind="transcript",
        relpath="m1.txt",
        snippet="[query]",
        score=0.1,
        segment_index=0,
        start_ms=1000,
        end_ms=1500,
        content="Example content with query",
        context="Prev line\nExample content with query\nNext line",
    )


class _FakeIndex:
    def __init__(
        self,
        *,
        hits_sequence: list[list[object]] | None = None,
        query_hits: dict[str, list[object]] | None = None,
        doc_count: int = 1,
    ) -> None:
        self._hits_sequence = list(hits_sequence or [])
        self._query_hits = dict(query_hits or {})
        self._doc_count = int(doc_count)
        self.rebuild_calls: list[str] = []
        self.search_calls: list[str] = []

    def search(self, _query: str, **_kwargs):
        query = str(_query or "")
        self.search_calls.append(query)
        if self._query_hits:
            return list(self._query_hits.get(query, []))
        if not self._hits_sequence:
            return []
        return list(self._hits_sequence.pop(0))

    def document_count(self) -> int:
        return self._doc_count

    def rebuild(self, *, meeting_id: str = "") -> None:
        self.rebuild_calls.append(str(meeting_id or ""))


class TestSearchPlugins(unittest.TestCase):
    def test_simple_search_rebuilds_once_after_empty_results(self) -> None:
        simple_plugin._EMPTY_RESULT_REBUILD_ONCE_KEYS.clear()  # noqa: SLF001
        index = _FakeIndex(hits_sequence=[[], [_hit()]])
        with patch("plugins.search.simple.simple._open_index", return_value=index):
            result = simple_plugin._action_search({}, {"query": "q", "meeting_id": "m1"})
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(index.rebuild_calls), 1)
        self.assertEqual(index.rebuild_calls[0], "m1")
        self.assertEqual(int((result.data or {}).get("total", 0)), 1)
        first_hit = ((result.data or {}).get("hits") or [{}])[0]
        self.assertIn("context", first_hit)

    def test_simple_search_does_not_loop_rebuild_for_same_scope(self) -> None:
        simple_plugin._EMPTY_RESULT_REBUILD_ONCE_KEYS.clear()  # noqa: SLF001
        first = _FakeIndex(hits_sequence=[[], []])
        second = _FakeIndex(hits_sequence=[[]])
        with patch("plugins.search.simple.simple._open_index", side_effect=[first, second]):
            simple_plugin._action_search({}, {"query": "q", "meeting_id": "m1"})
            simple_plugin._action_search({}, {"query": "q", "meeting_id": "m1"})
        self.assertEqual(len(first.rebuild_calls), 1)
        self.assertEqual(len(second.rebuild_calls), 0)

    def test_semantic_smart_search_returns_hits(self) -> None:
        plugin = semantic_smart_plugin.Plugin()
        plugin.logger = SimpleNamespace(info=lambda *_args, **_kwargs: None)

        result = plugin.handle_search({}, {"query": "architecture"})

        self.assertEqual(result.status, "ok")
        self.assertEqual(str((result.data or {}).get("query", "")), "architecture")
        self.assertGreaterEqual(int((result.data or {}).get("total", 0)), 1)

    def test_legacy_smart_search_rebuilds_once_after_empty_results(self) -> None:
        smart_legacy_plugin._EMPTY_RESULT_REBUILD_ONCE_KEYS.clear()  # noqa: SLF001
        index = _FakeIndex(hits_sequence=[[], [_hit()]])
        with patch("plugins.search.smart_legacy.smart_legacy._open_index", return_value=index):
            result = smart_legacy_plugin._action_search({}, {"query": "q", "meeting_id": "m1"})
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(index.rebuild_calls), 1)
        self.assertEqual(index.rebuild_calls[0], "m1")
        self.assertEqual(int((result.data or {}).get("total", 0)), 1)

    def test_legacy_smart_search_expands_query_to_context_terms(self) -> None:
        smart_legacy_plugin._EMPTY_RESULT_REBUILD_ONCE_KEYS.clear()  # noqa: SLF001
        query = "товара пропал с витрины"
        index = _FakeIndex(
            query_hits={
                query: [],
                "товара": [_hit(meeting_id="m2")],
                "товар": [_hit(meeting_id="m2")],
            }
        )
        with patch("plugins.search.smart_legacy.smart_legacy._open_index", return_value=index):
            result = smart_legacy_plugin._action_search({}, {"query": query, "meeting_id": ""})
        self.assertEqual(result.status, "ok")
        self.assertGreaterEqual(int((result.data or {}).get("total", 0)), 1)
        self.assertIn("товара", set(index.search_calls))
        self.assertIn("товар", set(index.search_calls))
        self.assertIn("товара*", set(index.search_calls))
        self.assertIn("товар*", set(index.search_calls))
        hits = (result.data or {}).get("hits") or []
        self.assertEqual(len(hits), 1)
        self.assertEqual(str(hits[0].get("kind", "")), "transcript")

    def test_legacy_smart_search_keeps_non_exact_forms_in_top_results(self) -> None:
        smart_legacy_plugin._EMPTY_RESULT_REBUILD_ONCE_KEYS.clear()  # noqa: SLF001
        query = "продукты"
        exact_hits = [_hit(meeting_id=f"exact-{i}") for i in range(25)]
        stem_hit = _hit(meeting_id="stem-form")
        index = _FakeIndex(
            query_hits={
                query: list(exact_hits),
                "продукты*": list(exact_hits),
                "продукт": [stem_hit],
                "продукт*": [stem_hit],
            }
        )
        with patch("plugins.search.smart_legacy.smart_legacy._open_index", return_value=index):
            result = smart_legacy_plugin._action_search({}, {"query": query, "meeting_id": "", "limit": 20})
        self.assertEqual(result.status, "ok")
        hits = (result.data or {}).get("hits") or []
        mids = {str(item.get("meeting_id", "")) for item in hits if isinstance(item, dict)}
        self.assertIn("stem-form", mids)


if __name__ == "__main__":
    unittest.main()

