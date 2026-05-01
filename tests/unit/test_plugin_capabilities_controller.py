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

from aimn.ui.controllers.plugin_capabilities_controller import PluginCapabilitiesController


class TestPluginCapabilitiesController(unittest.TestCase):
    def test_integration_export_targets_filters_missing_actions_and_sorts(self) -> None:
        plugins = [
            SimpleNamespace(
                plugin_id="integration.b",
                capabilities={"artifact_export": {"manual_action": "export_text", "label": "Beta", "icon": "b"}},
            ),
            SimpleNamespace(
                plugin_id="integration.a",
                capabilities={"artifact_export": {"manual_action": "export_text", "label": "Alpha", "icon": "a"}},
            ),
            SimpleNamespace(
                plugin_id="integration.skip",
                capabilities={"artifact_export": {"manual_action": "missing_action", "label": "Skip"}},
            ),
        ]
        catalog = SimpleNamespace(
            enabled_plugins=lambda: plugins,
            display_name=lambda pid: {"integration.a": "A", "integration.b": "B", "integration.skip": "S"}.get(pid, pid),
            plugin_by_id=lambda pid: next((p for p in plugins if p.plugin_id == pid), None),
        )
        actions = {"integration.a": [SimpleNamespace(action_id="export_text")], "integration.b": [SimpleNamespace(action_id="export_text")]}

        controller = PluginCapabilitiesController(
            get_catalog=lambda: catalog,
            list_actions=lambda pid: actions.get(pid, []),
        )

        targets = controller.integration_export_targets(action_keys=("manual_text_action", "manual_action"))

        self.assertEqual(
            targets,
            [
                {"plugin_id": "integration.a", "action_id": "export_text", "label": "Alpha", "icon": "a"},
                {"plugin_id": "integration.b", "action_id": "export_text", "label": "Beta", "icon": "b"},
            ],
        )

    def test_capability_bool_and_int_read_plugin_capabilities(self) -> None:
        plugin = SimpleNamespace(
            plugin_id="demo.plugin",
            capabilities={"ui": {"transcription": {"local_provider": "true", "order": "7"}}},
        )
        catalog = SimpleNamespace(
            enabled_plugins=lambda: [plugin],
            display_name=lambda pid: pid,
            plugin_by_id=lambda pid: plugin if pid == "demo.plugin" else None,
        )
        controller = PluginCapabilitiesController(
            get_catalog=lambda: catalog,
            list_actions=lambda _pid: [],
        )

        self.assertTrue(controller.capability_bool("demo.plugin", "ui", "transcription", "local_provider"))
        self.assertEqual(controller.capability_int("demo.plugin", "ui", "transcription", "order"), 7)


if __name__ == "__main__":
    unittest.main()
