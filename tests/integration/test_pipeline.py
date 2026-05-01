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
from aimn.core.management_store import ManagementStore  # noqa: E402
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

_TEST_TRANSCRIPTION_PLUGIN_ID = "transcription.test_mock"
_TEST_TRANSCRIPTION_FIXTURE = "_test_transcription_mock"

_TEST_LLM_PLUGIN_ID = "llm.test_stub_pipeline"
_TEST_LLM_FIXTURE = "_test_llm_stub_pipeline"


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


def _artifact_paths(meeting: MeetingManifest, kind: str) -> list[str]:
    paths: list[str] = []
    for node in meeting.nodes.values():
        for artifact in node.artifacts:
            if artifact.kind == kind:
                paths.append(artifact.path)
    return paths


class TestPipelineIntegration(unittest.TestCase):
    def setUp(self) -> None:
        preferred = repo_root / "test.mp4"
        fallback = repo_root / "test_input.wav"
        if preferred.exists():
            self.media_path = preferred
        elif fallback.exists():
            self.media_path = fallback
        else:
            self.skipTest("test.mp4 and test_input.wav missing")

    def _run_pipeline(
        self, config_data: dict, enabled_plugins: list[str]
    ) -> tuple[MeetingManifest, list[StageEvent], dict[str, int]]:
        plugin_manager = PluginManager(repo_root, PluginsConfig({"enabled": enabled_plugins}))
        plugin_manager.load()
        stages = StagesRegistry(PluginsConfig(config_data)).build()
        engine = PipelineEngine(stages)
        events: list[StageEvent] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir)
            output_dir = app_root / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            meeting = _make_meeting(self.media_path)
            context = StageContext(
                meeting=meeting,
                force_run=False,
                output_dir=str(output_dir),
                plugin_manager=plugin_manager,
                event_callback=events.append,
            )
            result = engine.run(context, emit=events.append)
            self.assertEqual(result.result, "success", "pipeline result should be success")
            store = ManagementStore(app_root)
            try:
                snapshot = {
                    "tasks": len(store.list_tasks()),
                    "projects": len(store.list_projects()),
                    "agendas": len(store.list_agendas()),
                }
            finally:
                store.close()
            plugin_manager.shutdown()
            return meeting, events, snapshot

    def test_pipeline_main_scenario(self) -> None:
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
            meeting, _events, snapshot = self._run_pipeline(config_data, enabled)
        self.assertTrue(meeting.transcript_relpath)
        self.assertTrue(_artifact_paths(meeting, "summary"))
        self.assertEqual(snapshot["tasks"], 0)
        self.assertEqual(snapshot["projects"], 0)
        self.assertEqual(snapshot["agendas"], 0)
        self.assertTrue(_artifact_paths(meeting, "management_suggestions"))
        self.assertFalse(_artifact_paths(meeting, "tasks"))
        self.assertFalse(_artifact_paths(meeting, "projects"))
        self.assertTrue(_artifact_paths(meeting, "index"))

    def test_pipeline_branching_variants(self) -> None:
        config_data = {
            "pipeline": {"optional_stage_retries": 0},
            "stages": {
                "transcription": {"plugin_id": _TEST_TRANSCRIPTION_PLUGIN_ID},
                "llm_processing": {
                    "plugin_id": _TEST_LLM_PLUGIN_ID,
                    "variants": [
                        {"plugin_id": _TEST_LLM_PLUGIN_ID, "params": {"profile": "a"}},
                        {"plugin_id": _TEST_LLM_PLUGIN_ID, "params": {"profile": "b"}},
                    ],
                },
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
            meeting, _events, _snapshot = self._run_pipeline(config_data, enabled)
        summary_paths = _artifact_paths(meeting, "summary")
        self.assertEqual(meeting.naming_mode, "branched")
        self.assertGreaterEqual(len(summary_paths), 2)

    def test_pipeline_management_multiple_plugins(self) -> None:
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
            _meeting, _events, snapshot = self._run_pipeline(config_data, enabled)
        self.assertEqual(snapshot["tasks"], 0)
        self.assertEqual(snapshot["projects"], 0)
        self.assertEqual(snapshot["agendas"], 0)


if __name__ == "__main__":
    unittest.main()
