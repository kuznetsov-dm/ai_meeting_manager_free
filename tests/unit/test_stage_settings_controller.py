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

from aimn.ui.controllers.stage_settings_controller import StageSettingsController


class TestStageSettingsController(unittest.TestCase):
    def test_apply_stage_settings_sets_plugin_and_params(self) -> None:
        config = {"stages": {}}

        prev_plugin_id, plugin_id = StageSettingsController.apply_stage_settings(
            config,
            stage_id="llm_processing",
            payload={"plugin_id": "llm.test", "params": {"temperature": 0.2}},
            supports_transcription_quality_presets=lambda _pid: False,
            sanitize_params_for_plugin=lambda _pid, params: dict(params),
            get_plugin_by_id=lambda _pid: SimpleNamespace(module="x.module", class_name="XClass"),
            coerce_bool=lambda value: bool(value),
        )

        self.assertEqual(prev_plugin_id, "")
        self.assertEqual(plugin_id, "llm.test")
        stage = config["stages"]["llm_processing"]
        self.assertEqual(stage.get("plugin_id"), "llm.test")
        self.assertEqual(stage.get("module"), "x.module")
        self.assertEqual(stage.get("class"), "XClass")
        self.assertEqual(stage.get("params", {}).get("temperature"), 0.2)

    def test_apply_stage_settings_variants_replace_single_plugin_binding(self) -> None:
        config = {
            "stages": {
                "llm_processing": {
                    "plugin_id": "old.plugin",
                    "module": "old.module",
                    "class": "OldClass",
                }
            }
        }

        StageSettingsController.apply_stage_settings(
            config,
            stage_id="llm_processing",
            payload={
                "variants": [
                    {"plugin_id": "p1", "params": {"k": "v"}},
                    {"plugin_id": "", "params": {"skip": True}},
                ]
            },
            supports_transcription_quality_presets=lambda _pid: False,
            sanitize_params_for_plugin=lambda _pid, params: dict(params),
            get_plugin_by_id=lambda _pid: None,
            coerce_bool=lambda value: bool(value),
        )

        stage = config["stages"]["llm_processing"]
        self.assertNotIn("plugin_id", stage)
        self.assertNotIn("module", stage)
        self.assertNotIn("class", stage)
        self.assertEqual(len(stage.get("variants", [])), 1)
        self.assertEqual(stage["variants"][0]["plugin_id"], "p1")

    def test_apply_stage_settings_maps_transcription_preset_values(self) -> None:
        config = {"stages": {}}

        StageSettingsController.apply_stage_settings(
            config,
            stage_id="transcription",
            payload={"plugin_id": "tr.local", "params": {"language_mode": "auto_two_pass"}},
            supports_transcription_quality_presets=lambda _pid: True,
            sanitize_params_for_plugin=lambda _pid, params: dict(params),
            get_plugin_by_id=lambda _pid: None,
            coerce_bool=lambda value: str(value).lower() in {"1", "true", "yes"},
        )

        params = config["stages"]["transcription"]["params"]
        self.assertEqual(params.get("language_mode"), "auto")
        self.assertTrue(params.get("two_pass"))

    def test_apply_stage_settings_management_keeps_prompt_params(self) -> None:
        config = {"stages": {"management": {"plugin_id": "management.unified", "params": {"existing": 1}}}}

        StageSettingsController.apply_stage_settings(
            config,
            stage_id="management",
            payload={
                "plugin_id": "management.unified",
                "params": {"prompt_agenda_id": "agenda-1", "prompt_project_ids": "p1,p2"},
            },
            supports_transcription_quality_presets=lambda _pid: False,
            sanitize_params_for_plugin=lambda _pid, _params: {},
            get_plugin_by_id=lambda _pid: None,
            coerce_bool=lambda value: bool(value),
        )

        params = config["stages"]["management"]["params"]
        self.assertEqual(params.get("prompt_agenda_id"), "agenda-1")
        self.assertEqual(params.get("prompt_project_ids"), "p1,p2")

    def test_apply_stage_settings_transcription_variants_keep_selected_plugin(self) -> None:
        config = {"stages": {"transcription": {"plugin_id": "transcription.old"}}}

        StageSettingsController.apply_stage_settings(
            config,
            stage_id="transcription",
            payload={
                "plugin_id": "transcription.whisperadvanced",
                "variants": [
                    {"plugin_id": "transcription.whisperadvanced", "params": {"model": "small"}},
                    {"plugin_id": "transcription.alt_mock", "params": {"model": "medium"}},
                ],
            },
            supports_transcription_quality_presets=lambda _pid: False,
            sanitize_params_for_plugin=lambda _pid, params: dict(params),
            get_plugin_by_id=lambda _pid: SimpleNamespace(module="x.module", class_name="XClass"),
            coerce_bool=lambda value: bool(value),
        )

        stage = config["stages"]["transcription"]
        self.assertEqual(stage.get("plugin_id"), "transcription.whisperadvanced")
        self.assertEqual(stage.get("module"), "x.module")
        self.assertEqual(stage.get("class"), "XClass")
        self.assertEqual(len(stage.get("variants", [])), 2)

    def test_apply_stage_settings_transcription_empty_variants_keeps_selected_plugin(self) -> None:
        config = {"stages": {"transcription": {"plugin_id": "transcription.old"}}}

        StageSettingsController.apply_stage_settings(
            config,
            stage_id="transcription",
            payload={"plugin_id": "transcription.whisperadvanced", "variants": []},
            supports_transcription_quality_presets=lambda _pid: False,
            sanitize_params_for_plugin=lambda _pid, params: dict(params),
            get_plugin_by_id=lambda _pid: SimpleNamespace(module="x.module", class_name="XClass"),
            coerce_bool=lambda value: bool(value),
        )

        stage = config["stages"]["transcription"]
        self.assertEqual(stage.get("plugin_id"), "transcription.whisperadvanced")
        self.assertEqual(stage.get("module"), "x.module")
        self.assertEqual(stage.get("class"), "XClass")
        self.assertNotIn("variants", stage)

    def test_apply_stage_settings_sanitizes_each_variant_independently_for_same_provider(self) -> None:
        config = {"stages": {"llm_processing": {}}}

        StageSettingsController.apply_stage_settings(
            config,
            stage_id="llm_processing",
            payload={
                "variants": [
                    {"plugin_id": "llm.local", "params": {"model_id": "one"}},
                    {"plugin_id": "llm.local", "params": {"model_id": "two"}},
                ]
            },
            supports_transcription_quality_presets=lambda _pid: False,
            sanitize_params_for_plugin=lambda pid, params: {"plugin": pid, **dict(params)},
            get_plugin_by_id=lambda _pid: None,
            coerce_bool=lambda value: bool(value),
        )

        variants = config["stages"]["llm_processing"]["variants"]
        self.assertEqual(
            variants,
            [
                {"plugin_id": "llm.local", "params": {"plugin": "llm.local", "model_id": "one"}},
                {"plugin_id": "llm.local", "params": {"plugin": "llm.local", "model_id": "two"}},
            ],
        )

    def test_set_stage_enabled_updates_disabled_stages(self) -> None:
        config = {"pipeline": {"disabled_stages": ["llm_processing"]}}

        StageSettingsController.set_stage_enabled(config, stage_id="llm_processing", enabled=True)
        self.assertEqual(config["pipeline"]["disabled_stages"], [])

        StageSettingsController.set_stage_enabled(config, stage_id="service", enabled=False)
        self.assertEqual(config["pipeline"]["disabled_stages"], ["service"])


if __name__ == "__main__":
    unittest.main()
