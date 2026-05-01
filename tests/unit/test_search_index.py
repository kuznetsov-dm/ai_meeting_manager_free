import sqlite3
import sys
import tempfile
import unittest
import json
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from plugins.search.search_index import SearchHit, SqliteFtsSearchIndex  # noqa: E402


class _IndexStub(SqliteFtsSearchIndex):
    def __init__(self) -> None:
        # Intentionally skip parent init (no filesystem/sqlite needed for this unit test).
        pass


class TestSearchIndexFallback(unittest.TestCase):
    def test_search_falls_back_to_like_when_fts_fails(self) -> None:
        index = _IndexStub()

        def _fts_fail(*_args, **_kwargs):
            raise sqlite3.OperationalError("fts failed")

        def _like_ok(*_args, **_kwargs):
            return [
                SearchHit(
                    meeting_id="m1",
                    stage_id="meeting",
                    alias="",
                    kind="transcript",
                    relpath="x.txt",
                    snippet="hit",
                    score=42.0,
                )
            ]

        index._search_fts = _fts_fail  # type: ignore[method-assign]
        index._search_like = _like_ok  # type: ignore[method-assign]

        hits = index.search("query")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].relpath, "x.txt")

    def test_search_returns_empty_when_fallback_also_fails(self) -> None:
        index = _IndexStub()

        def _fts_fail(*_args, **_kwargs):
            raise sqlite3.OperationalError("fts failed")

        def _like_fail(*_args, **_kwargs):
            raise sqlite3.OperationalError("like failed")

        index._search_fts = _fts_fail  # type: ignore[method-assign]
        index._search_like = _like_fail  # type: ignore[method-assign]

        hits = index.search("query")
        self.assertEqual(hits, [])

    def test_search_falls_back_to_like_when_fts_returns_no_hits(self) -> None:
        index = _IndexStub()

        def _fts_empty(*_args, **_kwargs):
            return []

        def _like_ok(*_args, **_kwargs):
            return [
                SearchHit(
                    meeting_id="m1",
                    stage_id="meeting",
                    alias="",
                    kind="transcript",
                    relpath="x.txt",
                    snippet="hit-like",
                    score=100.0,
                )
            ]

        index._search_fts = _fts_empty  # type: ignore[method-assign]
        index._search_like = _like_ok  # type: ignore[method-assign]

        hits = index.search("query")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].snippet, "hit-like")

    def test_rebuild_recreates_index_when_delete_fails(self) -> None:
        index = _IndexStub()
        calls: dict[str, int] = {"recreate": 0, "written": 0}

        class _FailingConn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, *_args, **_kwargs):
                raise sqlite3.OperationalError("SQL logic error")

        index._connect = lambda **_kwargs: _FailingConn()  # type: ignore[method-assign]
        index._recreate_database = lambda: calls.__setitem__("recreate", calls["recreate"] + 1)  # type: ignore[method-assign]
        index._list_meetings = lambda: [  # type: ignore[method-assign]
            {
                "meeting_id": "m1",
                "transcript_relpath": "m1.transcript.txt",
            }
        ]
        index.on_artifact_written = lambda *_args, **_kwargs: calls.__setitem__("written", calls["written"] + 1)  # type: ignore[method-assign]

        index.rebuild(meeting_id="m1")
        self.assertEqual(calls["recreate"], 1)
        self.assertEqual(calls["written"], 1)

    def test_on_artifact_written_replaces_segments_scope(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            app_root = Path(tmp)
            output_dir = app_root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            rel = "m1.segments.json"
            seg_path = output_dir / rel

            seg_path.write_text(
                json.dumps(
                    [
                        {"index": 0, "start_ms": 0, "end_ms": 1000, "text": "alpha"},
                        {"index": 1, "start_ms": 1000, "end_ms": 2000, "text": "beta tail"},
                    ]
                ),
                encoding="utf-8",
            )
            index = SqliteFtsSearchIndex(app_root=app_root, index_relpath="search/test.sqlite")
            index.on_artifact_written("m1", "transcription", "a1", "segments", rel)

            seg_path.write_text(
                json.dumps(
                    [
                        {"index": 0, "start_ms": 0, "end_ms": 1000, "text": "alpha updated"},
                    ]
                ),
                encoding="utf-8",
            )
            index.on_artifact_written("m1", "transcription", "a1", "segments", rel)

            rows = index.search("tail", meeting_id="m1", kind="transcript", stage_id="transcription", alias="a1")
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
