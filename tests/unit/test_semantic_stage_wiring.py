# ruff: noqa: I001
import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from aimn.core.plugins_config import PluginsConfig  # noqa: E402
from aimn.core.stages import StagesRegistry  # noqa: E402
from aimn.ui.widgets.stage_nav_bar_v2 import STAGE_NAV_ORDER  # noqa: E402


class TestSemanticStageWiring(unittest.TestCase):
    def test_runtime_registry_keeps_text_processing_before_llm(self) -> None:
        registry = StagesRegistry(PluginsConfig({}))

        stages = registry.build()
        stage_ids = [stage.stage_id for stage in stages]

        self.assertIn("text_processing", stage_ids)
        self.assertLess(stage_ids.index("transcription"), stage_ids.index("text_processing"))
        self.assertLess(stage_ids.index("text_processing"), stage_ids.index("llm_processing"))

    def test_stage_navigation_hides_text_processing(self) -> None:
        self.assertNotIn("text_processing", STAGE_NAV_ORDER)
        self.assertLess(STAGE_NAV_ORDER.index("transcription"), STAGE_NAV_ORDER.index("llm_processing"))


if __name__ == "__main__":
    unittest.main()
