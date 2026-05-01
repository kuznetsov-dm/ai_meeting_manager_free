import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.fingerprinting import compute_source_fingerprint  # noqa: E402
from aimn.core.meeting_ids import make_meeting_ids, utc_now_iso  # noqa: E402
from aimn.core.pipeline import PipelineEngine, StageContext, StageEvent  # noqa: E402
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

_TEST_TRANSCRIPTION_PLUGIN_ID = "transcription.test_mock_cache"
_TEST_TRANSCRIPTION_FIXTURE = "_test_transcription_mock_cache"

_TEST_LLM_PLUGIN_ID = "llm.test_stub_cache"
_TEST_LLM_FIXTURE = "_test_llm_stub_cache"


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


class TestPipelineCacheHit(unittest.TestCase):
    def setUp(self) -> None:
        preferred = repo_root / "test.mp4"
        fallback = repo_root / "test_input.wav"
        if preferred.exists():
            self.media_path = preferred
        elif fallback.exists():
            self.media_path = fallback
        else:
            self.skipTest("test.mp4 and test_input.wav missing")

    def test_cache_hit_on_second_run(self) -> None:
        config_data = {
            "pipeline": {"optional_stage_retries": 0},
            "stages": {
                "transcription": {"plugin_id": _TEST_TRANSCRIPTION_PLUGIN_ID},
                "llm_processing": {"plugin_id": _TEST_LLM_PLUGIN_ID},
                "management": {"plugin_ids": ["management.unified"]},
                "service": {"plugin_id": "service.management_index"},
            },
        }
        enabled = [
            _TEST_TRANSCRIPTION_PLUGIN_ID,
            _TEST_LLM_PLUGIN_ID,
            "management.unified",
            "service.management_index",
        ]
        with temporary_plugin_roots(_TEST_TRANSCRIPTION_FIXTURE, _TEST_LLM_FIXTURE):
            plugin_manager = PluginManager(repo_root, PluginsConfig({"enabled": enabled}))
            plugin_manager.load()
            stages = StagesRegistry(PluginsConfig(config_data)).build()
            engine = PipelineEngine(stages)

            with tempfile.TemporaryDirectory() as temp_dir:
                meeting = _make_meeting(self.media_path)
                events: list[StageEvent] = []
                context = StageContext(
                    meeting=meeting,
                    force_run=False,
                    output_dir=temp_dir,
                    plugin_manager=plugin_manager,
                    event_callback=events.append,
                )
                engine.run(context, emit=events.append)

                events.clear()
                engine.run(context, emit=events.append)
                cache_hits = [event for event in events if event.event_type == "cache_hit"]
                self.assertTrue(cache_hits, "expected cache_hit events on second run")

            plugin_manager.shutdown()


if __name__ == "__main__":
    unittest.main()
