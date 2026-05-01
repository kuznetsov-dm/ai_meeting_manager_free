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

from aimn.ui.controllers.artifact_kind_bar_controller import (  # noqa: E402
    ArtifactKindBarController,
)


class TestArtifactKindBarController(unittest.TestCase):
    def test_ordered_kinds_prioritizes_transcript_and_summary(self) -> None:
        self.assertEqual(
            ArtifactKindBarController.ordered_kinds(["summary", "edited", "transcript", "logs"]),
            ["transcript", "summary", "edited", "logs"],
        )

    def test_build_row_specs_uses_titles_and_versions(self) -> None:
        specs = ArtifactKindBarController.build_row_specs(
            ["summary", "transcript"],
            kind_titles={"transcript": "Transcript", "summary": "Summary"},
            artifacts_by_kind={
                "summary": [SimpleNamespace(alias="v1")],
                "transcript": [SimpleNamespace(alias="T1"), SimpleNamespace(alias="T2")],
            },
        )
        self.assertEqual([spec.kind for spec in specs], ["transcript", "summary"])
        self.assertEqual(specs[0].title, "Transcript")
        self.assertEqual(len(specs[0].versions), 2)
        self.assertEqual(specs[1].title, "Summary")
        self.assertEqual(len(specs[1].versions), 1)

    def test_resolve_active_kind_preserves_existing_or_falls_back(self) -> None:
        self.assertEqual(
            ArtifactKindBarController.resolve_active_kind(["transcript", "summary"], "summary"),
            "summary",
        )
        self.assertEqual(
            ArtifactKindBarController.resolve_active_kind(["transcript", "summary"], "edited"),
            "transcript",
        )
        self.assertEqual(ArtifactKindBarController.resolve_active_kind([], "summary"), "")

    def test_selected_version_index_only_for_active_row(self) -> None:
        self.assertEqual(
            ArtifactKindBarController.selected_version_index(
                row_kind="summary",
                active_kind="summary",
                version_index=2,
            ),
            2,
        )
        self.assertIsNone(
            ArtifactKindBarController.selected_version_index(
                row_kind="transcript",
                active_kind="summary",
                version_index=2,
            )
        )


if __name__ == "__main__":
    unittest.main()
