import os
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
from aimn.core.meeting_store import FileMeetingStore  # noqa: E402
from aimn.core.pipeline import PipelineEngine, StageContext  # noqa: E402
from aimn.core.plugin_discovery import PluginDiscovery  # noqa: E402
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
from tests.plugin_fixture_helpers import temporary_plugin_roots, write_plugin_package  # noqa: E402

_TEST_TRANSCRIPTION_PLUGIN_ID = "transcription.test_mock_arch"
_TEST_TRANSCRIPTION_FIXTURE = "_test_transcription_mock_arch"


def _media_path() -> Path | None:
    preferred = repo_root / "test.mp4"
    fallback = repo_root / "test_input.wav"
    if preferred.exists():
        return preferred
    if fallback.exists():
        return fallback
    return None


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


def _run_and_save(
    meeting: MeetingManifest,
    plugin_manager: PluginManager,
    config_data: dict,
    output_dir: Path,
) -> None:
    stages = StagesRegistry(PluginsConfig(config_data)).build()
    engine = PipelineEngine(stages)
    context = StageContext(
        meeting=meeting,
        force_run=False,
        output_dir=str(output_dir),
        plugin_manager=plugin_manager,
    )
    result = engine.run(context)
    assert result is not None
    store = FileMeetingStore(output_dir)
    store.save(meeting)
    store.load(meeting.base_name)


class TestArchitectureSmoke(unittest.TestCase):
    def setUp(self) -> None:
        media = _media_path()
        if not media:
            self.skipTest("test.mp4 and test_input.wav missing")
        self.media_path = media

    def test_pipeline_with_no_plugins(self) -> None:
        config_data = {"pipeline": {"optional_stage_retries": 0}, "stages": {}}
        plugin_manager = PluginManager(repo_root, PluginsConfig({"enabled": []}))
        plugin_manager.load()
        meeting = _make_meeting(self.media_path)
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_and_save(meeting, plugin_manager, config_data, Path(temp_dir))
        plugin_manager.shutdown()

    def test_pipeline_with_missing_plugins_dir(self) -> None:
        config_data = {
            "pipeline": {"optional_stage_retries": 0},
            "stages": {"transcription": {"plugin_id": "transcription.whisperadvanced"}},
        }
        old_env = os.environ.get("AIMN_PLUGINS_DIR")
        missing_dir = Path(tempfile.gettempdir()) / "aimn_missing_plugins_dir"
        os.environ["AIMN_PLUGINS_DIR"] = str(missing_dir)
        plugin_manager = None
        try:
            plugin_manager = PluginManager(repo_root, PluginsConfig({"enabled": []}))
            plugin_manager.load()
            meeting = _make_meeting(self.media_path)
            with tempfile.TemporaryDirectory() as temp_dir:
                _run_and_save(meeting, plugin_manager, config_data, Path(temp_dir))
        finally:
            if plugin_manager is not None:
                plugin_manager.shutdown()
            if old_env is None:
                os.environ.pop("AIMN_PLUGINS_DIR", None)
            else:
                os.environ["AIMN_PLUGINS_DIR"] = old_env

    def test_pipeline_with_all_plugins_disabled(self) -> None:
        discovery = PluginDiscovery(repo_root / "plugins")
        plugin_ids = [manifest.plugin_id for manifest in discovery.discover()]
        config_data = {
            "pipeline": {"optional_stage_retries": 0},
            "stages": {"transcription": {"plugin_id": "transcription.whisperadvanced"}},
        }
        plugin_manager = PluginManager(repo_root, PluginsConfig({"disabled": plugin_ids}))
        plugin_manager.load()
        meeting = _make_meeting(self.media_path)
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_and_save(meeting, plugin_manager, config_data, Path(temp_dir))
        plugin_manager.shutdown()

    def test_pipeline_with_failing_plugin(self) -> None:
        with temporary_plugin_roots(_TEST_TRANSCRIPTION_FIXTURE) as plugins_root:
            write_plugin_package(
                plugins_root,
                "_test_failure",
                {
                    "__init__.py": "",
                    "failing_plugin.py": (
                        "from aimn.plugins.api import ArtifactSchema, HookContext\n"
                        "def _raise(ctx: HookContext):\n"
                        "    raise ValueError('fail')\n"
                        "class Plugin:\n"
                        "    def register(self, ctx):\n"
                        "        ctx.register_artifact_kind('summary', ArtifactSchema(content_type='text/markdown', user_visible=True))\n"
                        "        ctx.register_hook_handler('derive.after_postprocess', _raise)\n"
                    ),
                    "plugin.json": (
                        "{\n"
                        '  "id": "llm.failure",\n'
                        '  "name": "Failure Plugin",\n'
                        '  "product_name": "Failure Plugin",\n'
                        '  "highlights": "",\n'
                        '  "description": "",\n'
                        '  "version": "0.1.0",\n'
                        '  "api_version": "1",\n'
                        '  "entrypoint": "_test_failure.failing_plugin:Plugin",\n'
                        '  "hooks": [{"name": "derive.after_postprocess"}],\n'
                        '  "artifacts": ["summary"],\n'
                        '  "ui": {"tabs": [], "widgets": []}\n'
                        "}\n"
                    ),
                },
            )
            config_data = {
                "pipeline": {"optional_stage_retries": 0},
                "stages": {
                    "transcription": {"plugin_id": _TEST_TRANSCRIPTION_PLUGIN_ID},
                    "llm_processing": {"plugin_id": "llm.failure"},
                },
            }
            enabled = [_TEST_TRANSCRIPTION_PLUGIN_ID, "llm.failure"]
            plugin_manager = PluginManager(repo_root, PluginsConfig({"enabled": enabled}))
            plugin_manager.load()
            meeting = _make_meeting(self.media_path)
            with tempfile.TemporaryDirectory() as temp_dir:
                _run_and_save(meeting, plugin_manager, config_data, Path(temp_dir))
            plugin_manager.shutdown()


if __name__ == "__main__":
    unittest.main()
