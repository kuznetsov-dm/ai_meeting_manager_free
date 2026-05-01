import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_catalog import _stage_id_from_manifest, _ui_stage_from_raw  # noqa: E402
from aimn.core.plugin_manifest import HookSpec, PluginManifest  # noqa: E402


class TestPluginCatalogStageMapping(unittest.TestCase):
    def test_derive_hook_overrides_text_processing_prefix(self) -> None:
        manifest = PluginManifest(
            plugin_id="text_processing.minutes_heuristic_v2",
            name="Minutes",
            version="1.0.0",
            api_version="1",
            entrypoint="plugins.text_processing.minutes_heuristic_v2.minutes_heuristic_v2:Plugin",
            hooks=[
                HookSpec(name="postprocess.after_transcribe"),
                HookSpec(name="derive.after_postprocess"),
            ],
            artifacts=["edited"],
            product_name="Minutes",
        )
        stage_id = _stage_id_from_manifest(manifest)
        self.assertEqual(stage_id, "llm_processing")

    def test_ui_stage_from_raw(self) -> None:
        self.assertEqual(_ui_stage_from_raw({"ui_stage": "service"}), "service")
        self.assertEqual(_ui_stage_from_raw({"ui_stage": "llm_processing"}), "llm_processing")
        self.assertEqual(_ui_stage_from_raw({"ui_stage": "wat"}), "")
        self.assertEqual(_ui_stage_from_raw({}), "")


if __name__ == "__main__":
    unittest.main()

