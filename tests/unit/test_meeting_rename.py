import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.fingerprinting import compute_source_fingerprint  # noqa: E402
from aimn.core.meeting_loader import load_or_create_meeting  # noqa: E402
from aimn.core.meeting_rename import rename_meeting  # noqa: E402
from aimn.core.meeting_store import FileMeetingStore  # noqa: E402
from aimn.domain.meeting import (  # noqa: E402
    SCHEMA_VERSION,
    ArtifactRef,
    LineageNode,
    MeetingManifest,
    NodeInputs,
    NodeTool,
    SourceInfo,
    SourceItem,
    StorageInfo,
)


def _build_manifest(*, base_name: str, media_path: Path) -> MeetingManifest:
    transcript = f"{base_name}.transcript.md"
    summary = f"{base_name}__A01.summary.md"
    return MeetingManifest(
        schema_version=SCHEMA_VERSION,
        meeting_id="250101-1010_deadbeef",
        base_name=base_name,
        created_at="2025-01-01T10:10:00Z",
        updated_at="2025-01-01T10:10:00Z",
        storage=StorageInfo(),
        source=SourceInfo(
            items=[
                SourceItem(
                    source_id="src1",
                    input_filename=media_path.name,
                    input_path=str(media_path),
                    size_bytes=10,
                    mtime_utc="2025-01-01T10:10:00Z",
                    content_fingerprint=compute_source_fingerprint(str(media_path)),
                )
            ]
        ),
        nodes={
            "A01": LineageNode(
                stage_id="llm_processing",
                tool=NodeTool(plugin_id="llm.reference_openai", version="1.0.0"),
                params={},
                inputs=NodeInputs(source_ids=["src1"], parent_nodes=[]),
                fingerprint="fp-A01",
                artifacts=[
                    ArtifactRef(kind="transcript", path=transcript, content_type="text/markdown"),
                    ArtifactRef(kind="summary", path=summary, content_type="text/markdown"),
                ],
            )
        },
        transcript_relpath=transcript,
    )


class TestMeetingRename(unittest.TestCase):
    def test_rename_meeting_updates_manifest_and_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            media = root / "demo.wav"
            media.write_bytes(b"0123456789")

            store = FileMeetingStore(output_dir)
            old_base = "250101-1010_old_name"
            manifest = _build_manifest(base_name=old_base, media_path=media)
            store.save(manifest)

            old_transcript = output_dir / f"{old_base}.transcript.md"
            old_summary = output_dir / f"{old_base}__A01.summary.md"
            old_transcript.write_text("transcript", encoding="utf-8")
            old_summary.write_text("summary", encoding="utf-8")

            new_base = rename_meeting(store, base_name=old_base, new_title="Team Sync 2026")
            self.assertEqual(new_base, "250101-1010_Team_Sync_2026")

            self.assertFalse((output_dir / f"{old_base}.transcript.md").exists())
            self.assertFalse((output_dir / f"{old_base}__A01.summary.md").exists())
            self.assertFalse((output_dir / f"{old_base}__MEETING.json").exists())
            self.assertTrue((output_dir / f"{new_base}.transcript.md").exists())
            self.assertTrue((output_dir / f"{new_base}__A01.summary.md").exists())
            self.assertTrue((output_dir / f"{new_base}__MEETING.json").exists())

            renamed = store.load(new_base)
            self.assertEqual(renamed.base_name, new_base)
            self.assertEqual(getattr(renamed, "display_title", ""), "Team Sync 2026")
            self.assertTrue(bool(getattr(renamed, "base_name_locked", False)))
            self.assertEqual(renamed.transcript_relpath, f"{new_base}.transcript.md")

    def test_rename_meeting_fails_on_target_collision(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            media = root / "demo.wav"
            media.write_bytes(b"0123456789")

            store = FileMeetingStore(output_dir)
            old_base = "250101-1010_old_name"
            manifest = _build_manifest(base_name=old_base, media_path=media)
            store.save(manifest)
            (output_dir / f"{old_base}.transcript.md").write_text("transcript", encoding="utf-8")
            (output_dir / f"{old_base}__A01.summary.md").write_text("summary", encoding="utf-8")

            target_base = "250101-1010_Team_Sync_2026"
            (output_dir / f"{target_base}.transcript.md").write_text("collision", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                rename_meeting(store, base_name=old_base, new_title="Team Sync 2026")

            self.assertTrue((output_dir / f"{old_base}.transcript.md").exists())
            self.assertTrue((output_dir / f"{old_base}__A01.summary.md").exists())
            self.assertTrue((output_dir / f"{old_base}__MEETING.json").exists())

    def test_manual_base_name_is_not_overwritten_by_loader(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            media = root / "client_meeting.wav"
            media.write_bytes(b"audio-data")
            fp = compute_source_fingerprint(str(media))

            store = FileMeetingStore(output_dir)
            manifest = MeetingManifest(
                schema_version=SCHEMA_VERSION,
                meeting_id="250101-1010_deadbeef",
                base_name="250101-1010_manual_title",
                created_at="2025-01-01T10:10:00Z",
                updated_at="2025-01-01T10:10:00Z",
                storage=StorageInfo(),
                source=SourceInfo(
                    items=[
                        SourceItem(
                            source_id="src1",
                            input_filename=media.name,
                            input_path=str(media),
                            size_bytes=media.stat().st_size,
                            mtime_utc="2025-01-01T10:10:00Z",
                            content_fingerprint=fp,
                        )
                    ]
                ),
            )
            manifest.base_name_locked = True
            manifest.display_title = "Manual title"
            store.save(manifest)

            loaded = load_or_create_meeting(store, media)
            self.assertEqual(loaded.base_name, "250101-1010_manual_title")

    def test_metadata_only_rename_updates_title_without_file_moves(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            media = root / "demo.wav"
            media.write_bytes(b"0123456789")

            store = FileMeetingStore(output_dir)
            old_base = "250101-1010_old_name"
            manifest = _build_manifest(base_name=old_base, media_path=media)
            store.save(manifest)

            old_transcript = output_dir / f"{old_base}.transcript.md"
            old_summary = output_dir / f"{old_base}__A01.summary.md"
            old_transcript.write_text("transcript", encoding="utf-8")
            old_summary.write_text("summary", encoding="utf-8")

            new_base = rename_meeting(
                store,
                base_name=old_base,
                new_title="Weekly Product Review",
                rename_mode="metadata_only",
            )

            self.assertEqual(new_base, old_base)
            self.assertTrue(old_transcript.exists())
            self.assertTrue(old_summary.exists())
            self.assertTrue((output_dir / f"{old_base}__MEETING.json").exists())
            loaded = store.load(old_base)
            self.assertEqual(str(getattr(loaded, "display_title", "")), "Weekly Product Review")
            self.assertEqual(loaded.base_name, old_base)

    def test_full_with_source_renames_managed_import_source(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            imports_dir = root / "imports"
            imports_dir.mkdir(parents=True, exist_ok=True)
            media = imports_dir / "demo.wav"
            media.write_bytes(b"0123456789")

            store = FileMeetingStore(output_dir)
            old_base = "250101-1010_old_name"
            manifest = _build_manifest(base_name=old_base, media_path=media)
            store.save(manifest)
            (output_dir / f"{old_base}.transcript.md").write_text("transcript", encoding="utf-8")
            (output_dir / f"{old_base}__A01.summary.md").write_text("summary", encoding="utf-8")

            new_base = rename_meeting(
                store,
                base_name=old_base,
                new_title="Team Sync 2026",
                rename_mode="full_with_source",
                rename_source=True,
            )
            new_media = imports_dir / f"{new_base}.wav"
            self.assertTrue(new_media.exists())
            self.assertFalse(media.exists())
            loaded = store.load(new_base)
            self.assertEqual(str(loaded.source.items[0].input_path), str(new_media))
            self.assertEqual(str(loaded.source.items[0].input_filename), new_media.name)

    def test_full_with_source_rejects_external_source_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            media = root / "external_demo.wav"
            media.write_bytes(b"0123456789")

            store = FileMeetingStore(output_dir)
            old_base = "250101-1010_old_name"
            manifest = _build_manifest(base_name=old_base, media_path=media)
            store.save(manifest)
            (output_dir / f"{old_base}.transcript.md").write_text("transcript", encoding="utf-8")
            (output_dir / f"{old_base}__A01.summary.md").write_text("summary", encoding="utf-8")

            with self.assertRaises(PermissionError):
                rename_meeting(
                    store,
                    base_name=old_base,
                    new_title="Team Sync 2026",
                    rename_mode="full_with_source",
                    rename_source=True,
                )

    def test_invalid_rename_mode_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            media = root / "demo.wav"
            media.write_bytes(b"0123456789")

            store = FileMeetingStore(output_dir)
            old_base = "250101-1010_old_name"
            manifest = _build_manifest(base_name=old_base, media_path=media)
            store.save(manifest)

            with self.assertRaises(ValueError):
                rename_meeting(
                    store,
                    base_name=old_base,
                    new_title="Team Sync 2026",
                    rename_mode="broken_mode",
                )


if __name__ == "__main__":
    unittest.main()
