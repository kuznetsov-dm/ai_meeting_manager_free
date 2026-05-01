import json
import os
import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.pipeline import PipelineEngine, StageContext  # noqa: E402
from aimn.core.plugin_manager import PluginManager  # noqa: E402
from aimn.core.plugins_config import PluginsConfig  # noqa: E402
from aimn.core.stages import StagesRegistry  # noqa: E402
from aimn.domain.meeting import (  # noqa: E402
    MeetingManifest,
    SCHEMA_VERSION,
    SourceInfo,
    SourceItem,
    StorageInfo,
)
from aimn.core.fingerprinting import compute_source_fingerprint  # noqa: E402
from aimn.core.meeting_ids import make_meeting_ids, utc_now_iso  # noqa: E402


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


def _collect_plugin_ids(config_data: dict) -> list[str]:
    ids: list[str] = []
    stages = config_data.get("stages", {})
    for stage_cfg in stages.values():
        plugin_id = stage_cfg.get("plugin_id")
        if plugin_id:
            ids.append(plugin_id)
        for variant in stage_cfg.get("variants", []) or []:
            variant_id = variant.get("plugin_id")
            if variant_id:
                ids.append(variant_id)
    return sorted(set(ids))


def _has_mock_plugin(ids: list[str]) -> bool:
    for plugin_id in ids:
        if ".mock" in plugin_id or ".fake" in plugin_id:
            return True
    return False


class TestPipelineArtifactsReal(unittest.TestCase):
    def setUp(self) -> None:
        output_dir = os.environ.get("AIMN_E2E_OUTPUT_DIR")
        if not output_dir:
            output_dir = str(repo_root / "output_tests")
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        preferred = repo_root / "test.mp4"
        fallback = repo_root / "test_input.wav"
        if preferred.exists():
            self.media_path = preferred
        elif fallback.exists():
            self.media_path = fallback
        else:
            self.skipTest("test.mp4 and test_input.wav missing")

        config_path = os.environ.get(
            "AIMN_E2E_CONFIG",
            str(repo_root / "output" / "settings" / "pipeline" / "e2e_real.json"),
        )
        self.config_path = Path(config_path).resolve()
        if not self.config_path.exists():
            self.skipTest(f"pipeline config not found: {self.config_path}")

    def test_pipeline_outputs_no_mock_artifacts(self) -> None:
        config_data = json.loads(self.config_path.read_text(encoding="utf-8"))
        plugin_ids = _collect_plugin_ids(config_data)
        if _has_mock_plugin(plugin_ids):
            self.skipTest("pipeline config uses mock/fake plugins")

        plugin_manager = PluginManager(repo_root, PluginsConfig({"enabled": plugin_ids}))
        plugin_manager.load()
        stages = StagesRegistry(PluginsConfig(config_data)).build()
        engine = PipelineEngine(stages)

        meeting = _make_meeting(self.media_path)
        context = StageContext(
            meeting=meeting,
            force_run=False,
            output_dir=str(self.output_dir),
            plugin_manager=plugin_manager,
            event_callback=None,
        )
        result = engine.run(context)
        if result.result != "success":
            summary = [
                f"{item.stage_id}:{item.status}:{item.error or ''}" for item in result.stage_results
            ]
            plugin_errors = plugin_manager.plugin_errors()
            detail = "; ".join(summary)
            self.fail(f"pipeline result={result.result} stages={detail} plugin_errors={plugin_errors}")

        text_exts = {".txt", ".md", ".json"}
        for node in meeting.nodes.values():
            for artifact in node.artifacts:
                path = Path(artifact.path)
                if not path.exists():
                    continue
                if path.suffix.lower() not in text_exts:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("MOCK", content.upper(), f"mock content found in {path}")

        plugin_manager.shutdown()


if __name__ == "__main__":
    unittest.main()
