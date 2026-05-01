import sys
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

from aimn.ui.controllers.artifact_tab_navigation_controller import (  # noqa: E402
    ArtifactTabNavigationController,
)


class TestArtifactTabNavigationController(unittest.TestCase):
    def test_tab_to_version_index_accounts_for_results_tab(self) -> None:
        self.assertEqual(
            ArtifactTabNavigationController.tab_to_version_index(
                2,
                global_results_visible=True,
                versions_count=3,
            ),
            1,
        )

    def test_select_alias_tab_index_returns_tab_with_offset(self) -> None:
        versions = [
            SimpleNamespace(alias="T05", stage_id="transcription", kind="transcript"),
            SimpleNamespace(alias="v1", stage_id="llm_processing", kind="summary"),
        ]
        self.assertEqual(
            ArtifactTabNavigationController.select_alias_tab_index(
                versions,
                global_results_visible=True,
                alias="v1",
            ),
            2,
        )

    def test_select_version_tab_index_prefers_exact_then_fallbacks(self) -> None:
        versions = [
            SimpleNamespace(alias="T05", stage_id="transcription", kind="transcript"),
            SimpleNamespace(alias="v1", stage_id="llm_processing", kind="summary"),
        ]
        self.assertEqual(
            ArtifactTabNavigationController.select_version_tab_index(
                versions,
                global_results_visible=False,
                stage_id="llm_processing",
                alias="v1",
                kind="summary",
            ),
            1,
        )
        self.assertEqual(
            ArtifactTabNavigationController.select_version_tab_index(
                versions,
                global_results_visible=False,
                alias="missing",
                kind="summary",
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
