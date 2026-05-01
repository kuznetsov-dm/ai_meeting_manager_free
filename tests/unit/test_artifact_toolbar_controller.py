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

from aimn.ui.controllers.artifact_toolbar_controller import ArtifactToolbarController  # noqa: E402


class TestArtifactToolbarController(unittest.TestCase):
    def test_current_artifact_identity_accounts_for_results_tab_offset(self) -> None:
        versions = [
            SimpleNamespace(stage_id="transcription", alias="T05", kind="transcript"),
            SimpleNamespace(stage_id="llm_processing", alias="v1", kind="summary"),
        ]

        identity = ArtifactToolbarController.current_artifact_identity(
            versions,
            tab_index=2,
            global_results_visible=True,
        )

        self.assertEqual(identity, ("llm_processing", "v1", "summary"))

    def test_copyable_text_prefers_selection(self) -> None:
        text = ArtifactToolbarController.copyable_text("Selected", "Full text")
        self.assertEqual(text, "Selected")

    def test_export_request_payload_requires_complete_identity_and_text(self) -> None:
        payload = ArtifactToolbarController.export_request_payload(
            plugin_id="integration.export_alpha",
            action_id="export_text",
            stage_id="llm_processing",
            alias="v1",
            kind="summary",
            text="Summary text",
        )

        self.assertEqual(
            payload,
            ("integration.export_alpha", "export_text", "llm_processing", "v1", "summary", "Summary text"),
        )
        self.assertIsNone(
            ArtifactToolbarController.export_request_payload(
                plugin_id="integration.export_alpha",
                action_id="export_text",
                stage_id="",
                alias="v1",
                kind="summary",
                text="Summary text",
            )
        )

    def test_export_request_payload_for_tab_resolves_identity_from_versions(self) -> None:
        versions = [
            SimpleNamespace(stage_id="transcription", alias="T05", kind="transcript"),
            SimpleNamespace(stage_id="llm_processing", alias="v1", kind="summary"),
        ]

        payload = ArtifactToolbarController.export_request_payload_for_tab(
            versions=versions,
            tab_index=2,
            global_results_visible=True,
            plugin_id="integration.export_alpha",
            action_id="export_text",
            text="Summary text",
        )

        self.assertEqual(
            payload,
            ("integration.export_alpha", "export_text", "llm_processing", "v1", "summary", "Summary text"),
        )

    def test_export_controls_state_requires_text_for_copy_and_export(self) -> None:
        state = ArtifactToolbarController.export_controls_state(
            has_targets=True,
            stage_id="llm_processing",
            alias="v1",
            kind="summary",
            text="Summary text",
        )
        self.assertEqual(
            state,
            {"copy_enabled": True, "host_visible": True, "export_enabled": True},
        )
        self.assertEqual(
            ArtifactToolbarController.export_controls_state(
                has_targets=True,
                stage_id="llm_processing",
                alias="v1",
                kind="summary",
                text="   ",
            ),
            {"copy_enabled": False, "host_visible": True, "export_enabled": False},
        )

    def test_export_controls_state_for_tab_uses_current_tab_identity(self) -> None:
        versions = [
            SimpleNamespace(stage_id="transcription", alias="T05", kind="transcript"),
            SimpleNamespace(stage_id="llm_processing", alias="v1", kind="summary"),
        ]
        self.assertEqual(
            ArtifactToolbarController.export_controls_state_for_tab(
                versions=versions,
                tab_index=2,
                global_results_visible=True,
                has_targets=True,
                text="Summary text",
            ),
            {"copy_enabled": True, "host_visible": True, "export_enabled": True},
        )


if __name__ == "__main__":
    unittest.main()
