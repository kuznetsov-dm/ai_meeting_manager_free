# ruff: noqa: E402

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.pipeline_input_controller import (
    PipelineInputController,
    PipelineInputIngestResult,
    PipelineStartFilesResolution,
)


class TestPipelineInputController(unittest.TestCase):
    def test_resolve_start_files_prefers_explicit_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit = root / "explicit.wav"
            pending = root / "pending.wav"
            ad_hoc = root / "adhoc.wav"
            for path in (explicit, pending, ad_hoc):
                path.write_text("x", encoding="utf-8")

            result = PipelineInputController.resolve_start_files(
                explicit_files=[str(explicit), str(explicit), str(root / "missing.wav")],
                pending_files=[str(pending)],
                ad_hoc_files=[str(ad_hoc)],
                active_meeting_base_name="meeting-1",
                active_meeting_path=str(pending),
                active_meeting_status="completed",
            )

            self.assertEqual(
                result,
                PipelineStartFilesResolution(files=[str(explicit)], missing_selected_source=False),
            )

    def test_resolve_start_files_uses_pending_batch_when_active_meeting_is_not_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending_a = root / "pending-a.wav"
            pending_b = root / "pending-b.wav"
            for path in (pending_a, pending_b):
                path.write_text("x", encoding="utf-8")

            result = PipelineInputController.resolve_start_files(
                explicit_files=[],
                pending_files=[str(pending_a), str(pending_b)],
                ad_hoc_files=[],
                active_meeting_base_name="meeting-1",
                active_meeting_path=str(pending_a),
                active_meeting_status="completed",
            )

            self.assertEqual(result.files, [str(pending_a), str(pending_b)])
            self.assertFalse(result.missing_selected_source)

    def test_resolve_start_files_reports_missing_selected_source(self) -> None:
        result = PipelineInputController.resolve_start_files(
            explicit_files=[],
            pending_files=[],
            ad_hoc_files=[],
            active_meeting_base_name="meeting-1",
            active_meeting_path="",
            active_meeting_status="pending",
        )

        self.assertEqual(result.files, [])
        self.assertTrue(result.missing_selected_source)

    def test_discover_monitored_files_returns_new_signatures_for_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "clip.wav"
            ignored = root / "notes.txt"
            media.write_text("media", encoding="utf-8")
            ignored.write_text("notes", encoding="utf-8")

            discovered, signatures = PipelineInputController.discover_monitored_files(
                root,
                previous_signatures=set(),
                monitored_extensions={".wav", ".mp3"},
            )

            self.assertEqual(discovered, [str(media.resolve())])
            self.assertEqual(len(signatures), 1)

            discovered_again, next_signatures = PipelineInputController.discover_monitored_files(
                root,
                previous_signatures=signatures,
                monitored_extensions={".wav", ".mp3"},
            )
            self.assertEqual(discovered_again, [])
            self.assertEqual(next_signatures, signatures)

    def test_pending_monitored_files_only_returns_pending_media_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inside = root / "inside.wav"
            queued = root / "queued.wav"
            outside_dir = root / "external"
            outside_dir.mkdir()
            outside = outside_dir / "outside.wav"
            for path in (inside, queued, outside):
                path.write_text("x", encoding="utf-8")

            meetings = [
                SimpleNamespace(processing_status="raw", source_path=str(inside)),
                SimpleNamespace(processing_status="queued", source_path=str(queued)),
                SimpleNamespace(processing_status="completed", source_path=str(inside)),
                SimpleNamespace(processing_status="pending", source_path=str(outside)),
                SimpleNamespace(processing_status="pending", source_path=""),
            ]

            result = PipelineInputController.pending_monitored_files(
                meetings,
                monitored_root=root,
                resolve_meeting_primary_path=lambda meeting: str(getattr(meeting, "source_path", "") or ""),
            )

            self.assertEqual(result, [str(inside.resolve()), str(queued.resolve())])

    def test_ingest_files_sets_raw_status_for_new_pending_meetings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "meeting.wav"
            media.write_text("x", encoding="utf-8")
            meeting = SimpleNamespace(base_name="m-1", processing_status="pending", pipeline_runs=[])
            saved: list[object] = []
            statuses: list[tuple[str, str]] = []

            result = PipelineInputController.ingest_files(
                [str(media)],
                load_or_create_meeting=lambda _path: meeting,
                save_meeting=lambda loaded: saved.append(loaded),
                set_meeting_status=lambda loaded, status: statuses.append(
                    (str(getattr(loaded, "base_name", "") or ""), str(status))
                ),
            )

            self.assertEqual(
                result,
                PipelineInputIngestResult(
                    normalized_paths=[str(media)],
                    added_base_names=["m-1"],
                    reset_runtime_base_names=["m-1"],
                    load_failures=[],
                ),
            )
            self.assertEqual(statuses, [("m-1", "raw")])
            self.assertEqual(saved, [meeting])

    def test_ingest_files_collects_load_failures_without_saving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "meeting.wav"
            media.write_text("x", encoding="utf-8")
            saved: list[object] = []

            result = PipelineInputController.ingest_files(
                [str(media)],
                load_or_create_meeting=lambda _path: (_ for _ in ()).throw(RuntimeError("bad media")),
                save_meeting=lambda loaded: saved.append(loaded),
                set_meeting_status=lambda _loaded, _status: None,
            )

            self.assertEqual(result.normalized_paths, [str(media)])
            self.assertEqual(result.added_base_names, [])
            self.assertEqual(result.reset_runtime_base_names, [])
            self.assertEqual(len(result.load_failures), 1)
            self.assertIn("bad media", str(result.load_failures[0].error))
            self.assertEqual(saved, [])

    def test_ingest_files_does_not_reset_runtime_for_meeting_with_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "meeting.wav"
            media.write_text("x", encoding="utf-8")
            meeting = SimpleNamespace(base_name="m-1", processing_status="completed", pipeline_runs=[object()], nodes={})

            result = PipelineInputController.ingest_files(
                [str(media)],
                load_or_create_meeting=lambda _path: meeting,
                save_meeting=lambda _loaded: None,
                set_meeting_status=lambda _loaded, _status: None,
            )

            self.assertEqual(result.reset_runtime_base_names, [])


if __name__ == "__main__":
    unittest.main()
