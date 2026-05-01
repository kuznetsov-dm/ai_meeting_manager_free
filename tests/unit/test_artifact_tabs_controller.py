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

from aimn.ui.controllers.artifact_tabs_controller import (  # noqa: E402
    ArtifactTabSpec,
    ArtifactTabsController,
)


class TestArtifactTabsController(unittest.TestCase):
    def test_build_specs_includes_results_and_pinned_titles(self) -> None:
        specs = ArtifactTabsController.build_specs(
            [
                SimpleNamespace(stage_id="llm_processing", alias="v1", relpath="out/v1.txt"),
                SimpleNamespace(stage_id="llm_processing", alias="v2", relpath="out/v2.txt"),
            ],
            global_results_visible=True,
            results_title="Search Results",
            text_title="Text",
            pinned_aliases={"llm_processing": "v2"},
        )

        self.assertEqual([spec.kind for spec in specs], ["results", "artifact", "artifact"])
        self.assertEqual(specs[1].title, "v1")
        self.assertEqual(specs[2].title, "📌 v2")
        self.assertEqual(specs[2].tooltip, "llm_processing:v2\nout/v2.txt")

    def test_build_specs_falls_back_to_text_without_versions(self) -> None:
        specs = ArtifactTabsController.build_specs(
            [],
            global_results_visible=False,
            results_title="Search Results",
            text_title="Text",
        )
        self.assertEqual(specs, [ArtifactTabSpec(kind="text", title="Text", tooltip="", version_index=None)])

    def test_previous_title_validates_index(self) -> None:
        self.assertEqual(ArtifactTabsController.previous_title(["A", "B"], 1), "B")
        self.assertEqual(ArtifactTabsController.previous_title(["A", "B"], -1), "")
        self.assertEqual(ArtifactTabsController.previous_title(["A", "B"], 9), "")

    def test_selected_index_prefers_results_when_requested(self) -> None:
        specs = [
            ArtifactTabSpec(kind="results", title="Search Results"),
            ArtifactTabSpec(kind="artifact", title="v1", version_index=0),
        ]
        selected = ArtifactTabsController.selected_index(
            specs,
            [SimpleNamespace(stage_id="llm_processing", alias="v1")],
            global_results_visible=True,
            results_title="Search Results",
            prefer_results=True,
        )
        self.assertEqual(selected, 0)

    def test_selected_index_preserves_previous_title_before_alias_preference(self) -> None:
        specs = [
            ArtifactTabSpec(kind="results", title="Search Results"),
            ArtifactTabSpec(kind="artifact", title="v1", version_index=0),
            ArtifactTabSpec(kind="artifact", title="v2", version_index=1),
        ]
        versions = [
            SimpleNamespace(stage_id="llm_processing", alias="v1"),
            SimpleNamespace(stage_id="llm_processing", alias="v2"),
        ]
        selected = ArtifactTabsController.selected_index(
            specs,
            versions,
            global_results_visible=True,
            results_title="Search Results",
            prev_title="v1",
            active_aliases={"llm_processing": "v2"},
        )
        self.assertEqual(selected, 1)

    def test_selected_index_uses_active_alias_when_no_previous_title_matches(self) -> None:
        specs = [
            ArtifactTabSpec(kind="artifact", title="v1", version_index=0),
            ArtifactTabSpec(kind="artifact", title="v2", version_index=1),
        ]
        versions = [
            SimpleNamespace(stage_id="llm_processing", alias="v1"),
            SimpleNamespace(stage_id="llm_processing", alias="v2"),
        ]
        selected = ArtifactTabsController.selected_index(
            specs,
            versions,
            global_results_visible=False,
            results_title="Search Results",
            prev_title="",
            active_aliases={"llm_processing": "v2"},
        )
        self.assertEqual(selected, 1)


if __name__ == "__main__":
    unittest.main()
