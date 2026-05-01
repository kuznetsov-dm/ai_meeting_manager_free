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

from aimn.ui.controllers.artifact_selection_controller import (  # noqa: E402
    ArtifactSelectionController,
)


class TestArtifactSelectionController(unittest.TestCase):
    def test_selected_artifact_validates_index(self) -> None:
        versions = [SimpleNamespace(alias="v1"), SimpleNamespace(alias="v2")]
        self.assertIs(ArtifactSelectionController.selected_artifact(versions, version_index=1), versions[1])
        self.assertIsNone(ArtifactSelectionController.selected_artifact(versions, version_index=None))
        self.assertIsNone(ArtifactSelectionController.selected_artifact(versions, version_index=9))

    def test_selection_payload_extracts_stage_alias_kind(self) -> None:
        artifact = SimpleNamespace(stage_id="llm_processing", alias="v2", kind="summary")
        self.assertEqual(
            ArtifactSelectionController.selection_payload(artifact),
            ("llm_processing", "v2", "summary"),
        )

    def test_pin_menu_actions_for_pinned_and_unpinned_versions(self) -> None:
        artifact = SimpleNamespace(stage_id="llm_processing", alias="v2", kind="summary")
        self.assertEqual(
            [item.action for item in ArtifactSelectionController.pin_menu_actions(artifact, pinned_aliases={})],
            ["pin"],
        )
        self.assertEqual(
            [item.action for item in ArtifactSelectionController.pin_menu_actions(artifact, pinned_aliases={"llm_processing": "v2"})],
            ["unpin"],
        )
        self.assertEqual(
            [item.action for item in ArtifactSelectionController.pin_menu_actions(artifact, pinned_aliases={"llm_processing": "v1"})],
            ["pin", "unpin"],
        )

    def test_selection_payload_for_tab_respects_global_results_offset(self) -> None:
        versions = [
            SimpleNamespace(stage_id="transcription", alias="t1", kind="transcript"),
            SimpleNamespace(stage_id="llm_processing", alias="s1", kind="summary"),
        ]
        self.assertEqual(
            ArtifactSelectionController.selection_payload_for_tab(
                versions,
                tab_index=0,
                global_results_visible=True,
            ),
            ("", "", ""),
        )
        self.assertEqual(
            ArtifactSelectionController.selection_payload_for_tab(
                versions,
                tab_index=2,
                global_results_visible=True,
            ),
            ("llm_processing", "s1", "summary"),
        )

    def test_pin_menu_actions_for_tab_uses_selected_artifact(self) -> None:
        versions = [
            SimpleNamespace(stage_id="transcription", alias="t1", kind="transcript"),
            SimpleNamespace(stage_id="llm_processing", alias="s2", kind="summary"),
        ]
        self.assertEqual(
            [item.action for item in ArtifactSelectionController.pin_menu_actions_for_tab(
                versions,
                tab_index=2,
                global_results_visible=True,
                pinned_aliases={"llm_processing": "s1"},
            )],
            ["pin", "unpin"],
        )

    def test_kind_version_context_payload_uses_kind_bucket_and_index(self) -> None:
        artifacts_by_kind = {
            "summary": [
                SimpleNamespace(stage_id="llm_processing", alias="v1", kind="summary"),
                SimpleNamespace(stage_id="llm_processing", alias="v2", kind="summary"),
            ]
        }
        self.assertEqual(
            ArtifactSelectionController.kind_version_context_payload(
                artifacts_by_kind,
                kind="summary",
                version_index=1,
            ),
            ("llm_processing", "v2", "summary"),
        )
        self.assertEqual(
            ArtifactSelectionController.kind_version_context_payload(
                artifacts_by_kind,
                kind="summary",
                version_index=5,
            ),
            ("", "", ""),
        )


if __name__ == "__main__":
    unittest.main()
