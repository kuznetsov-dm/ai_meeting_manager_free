import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.artifact_export_buttons_controller import (  # noqa: E402
    ArtifactExportButtonsController,
)


class TestArtifactExportButtonsController(unittest.TestCase):
    def test_normalize_targets_supports_dicts_and_tuples(self) -> None:
        targets = ArtifactExportButtonsController.normalize_targets(
            [
                {"plugin_id": "integration.alpha", "action_id": "export_text", "label": "Alpha", "icon": "a"},
                ("integration.beta", "export_text", "Beta"),
                {"plugin_id": "", "action_id": "export_text", "label": "Skip"},
            ]
        )

        self.assertEqual(
            targets,
            [
                {
                    "plugin_id": "integration.alpha",
                    "action_id": "export_text",
                    "label": "Alpha",
                    "icon": "a",
                },
                {
                    "plugin_id": "integration.beta",
                    "action_id": "export_text",
                    "label": "Beta",
                    "icon": "",
                },
            ],
        )

    def test_build_specs_filters_invalid_targets_and_builds_tooltips(self) -> None:
        specs = ArtifactExportButtonsController.build_specs(
            [
                {"plugin_id": "integration.alpha", "action_id": "export_text", "label": "Alpha", "icon": "a"},
                {"plugin_id": "integration.beta", "action_id": "", "label": "Beta"},
                {"plugin_id": "integration.gamma", "action_id": "export_text"},
                "bad",
            ],
            export_label="Export",
        )

        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0].plugin_id, "integration.alpha")
        self.assertEqual(specs[0].tooltip, "Export: Alpha")
        self.assertEqual(specs[1].plugin_id, "integration.gamma")
        self.assertEqual(specs[1].label, "integration.gamma")


if __name__ == "__main__":
    unittest.main()
