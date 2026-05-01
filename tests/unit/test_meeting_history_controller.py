# ruff: noqa: E402, I001

import sys
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.meeting_history_controller import MeetingHistoryController


def _meeting(
    *,
    base_name: str,
    meeting_id: str = "",
    status: str = "",
    input_path: str = "",
) -> object:
    item = SimpleNamespace(input_path=input_path)
    source = SimpleNamespace(items=[item] if input_path else [])
    return SimpleNamespace(
        base_name=base_name,
        meeting_id=meeting_id,
        processing_status=status,
        source=source,
    )


class TestMeetingHistoryController(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = MeetingHistoryController()

    def test_meeting_primary_path(self) -> None:
        meeting = _meeting(base_name="m1", input_path="C:/tmp/a.wav")
        self.assertEqual(self.controller.meeting_primary_path(meeting), "C:/tmp/a.wav")

    def test_pending_files_only_for_pending_statuses(self) -> None:
        meetings = [
            _meeting(base_name="m1", status="raw", input_path="raw.wav"),
            _meeting(base_name="m2", status="completed", input_path="done.wav"),
            _meeting(base_name="m3", status="queued", input_path="queued.wav"),
        ]
        pending = self.controller.pending_files_from_meetings(meetings)
        self.assertEqual(pending, ["raw.wav", "queued.wav"])

    def test_resolve_meeting_base_supports_meeting_id(self) -> None:
        self.controller.set_meetings(
            [
                _meeting(base_name="base-1", meeting_id="id-1"),
                _meeting(base_name="base-2", meeting_id="id-2"),
            ]
        )
        self.assertEqual(self.controller.resolve_meeting_base("base-1"), "base-1")
        self.assertEqual(self.controller.resolve_meeting_base("id-2"), "base-2")

    def test_active_meeting_path_and_status(self) -> None:
        def loader(base: str) -> object:
            return _meeting(base_name=base, status="running", input_path=f"{base}.wav")

        self.assertEqual(
            self.controller.active_meeting_path(base_name="meeting-a", loader=loader),
            "meeting-a.wav",
        )
        self.assertEqual(
            self.controller.active_meeting_status(base_name="meeting-a", loader=loader),
            "running",
        )

    def test_active_meeting_status_normalizes_stale_running_to_completed(self) -> None:
        def loader(base: str) -> object:
            return SimpleNamespace(
                base_name=base,
                processing_status="running",
                processing_error="",
                pipeline_runs=[SimpleNamespace(result="completed", finished_at="2026-02-14T11:00:00Z")],
                source=SimpleNamespace(items=[SimpleNamespace(input_path=f"{base}.wav")]),
            )

        self.assertEqual(
            self.controller.active_meeting_status(base_name="meeting-a", loader=loader),
            "completed",
        )

    def test_normalize_ad_hoc_input_files_filters_missing(self) -> None:
        with self.subTest("existing"):
            existing = str(Path(__file__))
            normalized = self.controller.normalize_ad_hoc_input_files([existing, "", "missing-file.wav"])
            self.assertEqual(normalized, [existing])

    def test_enrich_history_meta_populates_display_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "m1__transcript.txt").write_text("hello world", encoding="utf-8")
            segments = [
                {"end_ms": 1200, "speaker": "A"},
                {"end_ms": 2500, "speaker": "B"},
            ]
            (output_dir / "m1__segments.json").write_text(json.dumps(segments), encoding="utf-8")
            meeting = SimpleNamespace(
                transcript_relpath="m1__transcript.txt",
                segments_relpath="m1__segments.json",
                source=SimpleNamespace(
                    items=[
                        SimpleNamespace(
                            mtime_utc="2026-02-14T10:00:00Z",
                            input_path=str(output_dir / "input.wav"),
                            size_bytes=1024,
                        )
                    ]
                ),
                created_at="2026-02-14T10:00:00Z",
                updated_at="2026-02-14T11:00:00Z",
                pipeline_runs=[SimpleNamespace(finished_at="2026-02-14T11:00:00Z")],
                nodes={},
            )

            self.controller.enrich_history_meta(meeting, output_dir=output_dir)

            self.assertTrue(str(getattr(meeting, "display_meeting_time", "")).startswith("Meeting: "))
            self.assertTrue(str(getattr(meeting, "display_processed_time", "")).startswith("Last processed: "))
            stats = str(getattr(meeting, "display_stats", "") or "")
            self.assertIn("Words: 2", stats)
            self.assertIn("Segments: 2", stats)

    def test_set_meeting_status_updates_fields_and_touches(self) -> None:
        touched: list[object] = []
        meeting = SimpleNamespace(updated_at="2026-02-14T11:00:00Z")

        self.controller.set_meeting_status(
            meeting,
            "completed",
            error="",
            touch_updated=lambda item: touched.append(item),
        )

        self.assertEqual(getattr(meeting, "processing_status", ""), "completed")
        self.assertEqual(getattr(meeting, "processing_error", ""), "")
        self.assertEqual(len(touched), 1)

    def test_set_meetings_normalizes_stale_running_statuses(self) -> None:
        meeting = SimpleNamespace(
            base_name="m1",
            processing_status="running",
            processing_error="",
            pipeline_runs=[SimpleNamespace(result="completed", finished_at="2026-02-14T11:00:00Z")],
            source=SimpleNamespace(items=[]),
        )

        self.controller.set_meetings([meeting])

        self.assertEqual(getattr(meeting, "processing_status", ""), "completed")

    def test_pending_files_ignore_stale_running_meetings(self) -> None:
        stale = SimpleNamespace(
            base_name="m1",
            processing_status="running",
            processing_error="",
            pipeline_runs=[SimpleNamespace(result="completed", finished_at="2026-02-14T11:00:00Z")],
            source=SimpleNamespace(items=[SimpleNamespace(input_path="done.wav")]),
        )
        raw = _meeting(base_name="m2", status="raw", input_path="raw.wav")

        pending = self.controller.pending_files_from_meetings([stale, raw])

        self.assertEqual(pending, ["raw.wav"])

    def test_enrich_history_meta_uses_cache_for_unchanged_updated_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            meeting = SimpleNamespace(
                base_name="cache-meeting",
                transcript_relpath="missing.txt",
                segments_relpath="missing.json",
                source=SimpleNamespace(items=[SimpleNamespace(mtime_utc="2026-02-14T10:00:00Z")]),
                created_at="2026-02-14T10:00:00Z",
                updated_at="2026-02-14T11:00:00Z",
                pipeline_runs=[],
                nodes={},
            )

            calls = {"words": 0, "segments": 0}

            def _words(_meeting: object, *, output_dir: Path) -> int:
                calls["words"] += 1
                return 12

            def _segments(_meeting: object, *, output_dir: Path) -> tuple[int, int, int]:
                calls["segments"] += 1
                return 30, 3, 2

            self.controller.meeting_word_count = _words  # type: ignore[method-assign]
            self.controller.meeting_segments_stats = _segments  # type: ignore[method-assign]

            self.controller.enrich_history_meta(meeting, output_dir=output_dir)
            self.controller.enrich_history_meta(meeting, output_dir=output_dir)

            self.assertEqual(calls["words"], 1)
            self.assertEqual(calls["segments"], 1)

    def test_meta_cache_snapshot_restore_roundtrip(self) -> None:
        self.controller.restore_meta_cache(
            {
                "m1": {
                    "updated_at": "2026-02-14T11:00:00Z",
                    "display_meeting_time": "Meeting: Fri 14 Feb 11:00",
                    "display_processed_time": "Last processed: Fri 14 Feb 11:00",
                    "display_stats": "Words: 10",
                }
            }
        )
        snapshot = self.controller.meta_cache_snapshot()
        self.assertIn("m1", snapshot)
        self.assertEqual(snapshot["m1"]["display_stats"], "Words: 10")


if __name__ == "__main__":
    unittest.main()
