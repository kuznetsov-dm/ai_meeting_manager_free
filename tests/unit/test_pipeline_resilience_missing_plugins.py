import sys
import tempfile
import unittest
import wave
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.fingerprinting import compute_source_fingerprint  # noqa: E402
from aimn.core.meeting_ids import make_meeting_ids, utc_now_iso  # noqa: E402
from aimn.core.pipeline import PipelineEngine, StageContext  # noqa: E402
from aimn.core.plugin_manager import PluginManager  # noqa: E402
from aimn.core.plugins_config import PluginsConfig  # noqa: E402
from aimn.core.stages import StagesRegistry  # noqa: E402
from aimn.domain.meeting import (  # noqa: E402
    SCHEMA_VERSION,
    MeetingManifest,
    SourceInfo,
    SourceItem,
    StorageInfo,
)
from tests.plugin_fixture_helpers import temporary_plugin_roots  # noqa: E402

_TEST_TRANSCRIPTION_PLUGIN_ID = "transcription.test_resilience"
_TEST_TRANSCRIPTION_FIXTURE = "_test_transcription_resilience"


def _write_silent_wav(path: Path, *, duration_ms: int = 300, sample_rate: int = 16000) -> None:
    frames = max(1, int(sample_rate * duration_ms / 1000))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)


def _make_meeting(media_path: Path) -> MeetingManifest:
    meeting_id, base_name = make_meeting_ids(media_path)
    stat = media_path.stat()
    item = SourceItem(
        source_id="src1",
        input_filename=media_path.name,
        input_path=str(media_path),
        size_bytes=stat.st_size,
        mtime_utc=utc_now_iso(),
        content_fingerprint=compute_source_fingerprint(str(media_path)),
    )
    return MeetingManifest(
        schema_version=SCHEMA_VERSION,
        meeting_id=meeting_id,
        base_name=base_name,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
        storage=StorageInfo(),
        source=SourceInfo(items=[item]),
    )


class TestPipelineResilienceMissingPlugins(unittest.TestCase):
    def test_pipeline_completes_with_only_transcription_plugin(self) -> None:
        config_data = {
            "pipeline": {"optional_stage_retries": 0},
            "stages": {
                "transcription": {"plugin_id": _TEST_TRANSCRIPTION_PLUGIN_ID},
                "llm_processing": {"plugin_id": "llm.missing"},
                "management": {"plugin_ids": ["management.missing"]},
                "service": {"plugin_id": "service.missing"},
            },
        }
        with temporary_plugin_roots(_TEST_TRANSCRIPTION_FIXTURE):
            plugin_manager = PluginManager(repo_root, PluginsConfig({"enabled": [_TEST_TRANSCRIPTION_PLUGIN_ID]}))
            plugin_manager.load()
            try:
                stages = StagesRegistry(PluginsConfig(config_data)).build()
                engine = PipelineEngine(stages)

                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    media_path = root / "input.wav"
                    output_dir = root / "output"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    _write_silent_wav(media_path)

                    meeting = _make_meeting(media_path)
                    result = engine.run(
                        StageContext(
                            meeting=meeting,
                            force_run=False,
                            output_dir=str(output_dir),
                            plugin_manager=plugin_manager,
                            event_callback=None,
                        )
                    )
                    transcript_exists = bool(
                        meeting.transcript_relpath
                        and (output_dir / str(meeting.transcript_relpath)).exists()
                    )
            finally:
                plugin_manager.shutdown()

        self.assertEqual(result.result, "success")
        self.assertTrue(meeting.transcript_relpath)
        self.assertTrue(transcript_exists)

        by_stage = {item.stage_id: item for item in result.stage_results}
        self.assertEqual(by_stage["transcription"].status, "success")
        self.assertEqual(by_stage["llm_processing"].status, "skipped")
        self.assertEqual(by_stage["llm_processing"].skip_reason, "no_plugin")
        self.assertEqual(by_stage["management"].status, "skipped")
        self.assertEqual(by_stage["service"].status, "skipped")
        self.assertEqual(len([item for item in result.stage_results if item.status == "failed"]), 0)


if __name__ == "__main__":
    unittest.main()
