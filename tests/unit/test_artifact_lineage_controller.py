# ruff: noqa: E402

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

from aimn.ui.controllers.artifact_lineage_controller import (  # noqa: E402
    ArtifactLineageController,
)


class TestArtifactLineageController(unittest.TestCase):
    def test_resolve_lineage_node_tolerates_meeting_load_failure(self) -> None:
        events: list[tuple[str, str]] = []
        resolution = ArtifactLineageController.resolve_lineage_node(
            stage_id="llm_processing",
            alias="A1",
            active_meeting_manifest=None,
            active_meeting_base_name="m-base",
            load_meeting=lambda _base: (_ for _ in ()).throw(FileNotFoundError("gone")),
            log_load_error=lambda base, exc: events.append((base, str(exc))),
        )

        self.assertIsNone(resolution.meeting)
        self.assertIsNone(resolution.node)
        self.assertEqual(events, [("m-base", "gone")])

    def test_resolve_lineage_node_finds_matching_alias_and_stage(self) -> None:
        meeting = SimpleNamespace(
            nodes={
                "A1": SimpleNamespace(
                    stage_id="llm_processing",
                    tool=SimpleNamespace(plugin_id="llm.demo"),
                    params={"model": "demo"},
                )
            }
        )
        resolution = ArtifactLineageController.resolve_lineage_node(
            stage_id="llm_processing",
            alias="A1",
            active_meeting_manifest=meeting,
            active_meeting_base_name="",
            load_meeting=lambda _base: None,
            log_load_error=lambda _base, _exc: None,
        )

        self.assertIs(resolution.meeting, meeting)
        self.assertIs(resolution.node, meeting.nodes["A1"])
        self.assertEqual(
            ArtifactLineageController.provider_id_for_node(resolution.node),
            "llm.demo",
        )

    def test_enable_stage_in_runtime_config_removes_only_requested_disabled_stage(self) -> None:
        runtime = {"pipeline": {"disabled_stages": ["media_convert", "llm_processing", "text_processing"]}}

        ArtifactLineageController.enable_stage_in_runtime_config(runtime, "llm_processing")

        self.assertEqual(runtime["pipeline"]["disabled_stages"], ["media_convert", "text_processing"])

    def test_build_runtime_config_for_node_materializes_plugin_and_params(self) -> None:
        runtime = {
            "pipeline": {"disabled_stages": ["llm_processing", "text_processing"]},
            "stages": {
                "llm_processing": {
                    "variants": [{"plugin_id": "llm.old", "params": {"model": "old"}, "enabled": True}],
                    "plugin_id": "llm.old",
                    "params": {"model": "old"},
                }
            },
        }
        node = SimpleNamespace(
            tool=SimpleNamespace(plugin_id="llm.demo"),
            params={"model": "demo", "temperature": 0.2},
        )

        result = ArtifactLineageController.build_runtime_config_for_node(
            runtime_config=runtime,
            stage_id="llm_processing",
            node=node,
            sanitize_params_for_plugin=lambda _plugin_id, params: dict(params),
        )

        self.assertIs(result, runtime)
        stage_cfg = runtime["stages"]["llm_processing"]
        self.assertEqual(stage_cfg["plugin_id"], "llm.demo")
        self.assertEqual(stage_cfg["params"]["model"], "demo")
        self.assertEqual(stage_cfg["variants"][0]["plugin_id"], "llm.demo")
        self.assertEqual(runtime["pipeline"]["disabled_stages"], ["text_processing"])


if __name__ == "__main__":
    unittest.main()
