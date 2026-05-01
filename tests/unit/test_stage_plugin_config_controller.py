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

from aimn.ui.controllers.stage_plugin_config_controller import StagePluginConfigController


def _is_secret_field_name(key: str) -> bool:
    return str(key or "").strip().lower() in {"api_key", "token"}


class TestStagePluginConfigController(unittest.TestCase):
    def test_selected_plugin_id_prefers_primary_then_variant(self) -> None:
        controller = StagePluginConfigController(
            get_catalog=lambda: None,
            config_data_provider=lambda: {
                "stages": {
                    "llm_processing": {"variants": [{"plugin_id": "llm.zai"}]},
                    "transcription": {"plugin_id": "transcription.whisperadvanced"},
                }
            },
            offline_mode=lambda: False,
            coerce_setting_value=lambda value: value,
            is_secret_field_name=_is_secret_field_name,
            plugin_capabilities=lambda _pid: {},
            capability_bool=lambda *_args, **_kwargs: False,
            capability_int=lambda *_args, **_kwargs: 100,
        )

        self.assertEqual(controller.selected_plugin_id("transcription"), "transcription.whisperadvanced")
        self.assertEqual(controller.selected_plugin_id("llm_processing"), "llm.zai")

    def test_stage_plugin_options_respect_offline_mode(self) -> None:
        plugins = [
            SimpleNamespace(plugin_id="llm.a", installed=True, enabled=False),
            SimpleNamespace(plugin_id="llm.b", installed=True, enabled=True),
        ]
        catalog = SimpleNamespace(
            plugins_for_stage=lambda _stage_id: plugins,
            display_name=lambda pid: pid.upper(),
        )

        offline = StagePluginConfigController(
            get_catalog=lambda: catalog,
            config_data_provider=lambda: {},
            offline_mode=lambda: True,
            coerce_setting_value=lambda value: value,
            is_secret_field_name=_is_secret_field_name,
            plugin_capabilities=lambda _pid: {},
            capability_bool=lambda *_args, **_kwargs: False,
            capability_int=lambda *_args, **_kwargs: 100,
        )
        online = StagePluginConfigController(
            get_catalog=lambda: catalog,
            config_data_provider=lambda: {},
            offline_mode=lambda: False,
            coerce_setting_value=lambda value: value,
            is_secret_field_name=_is_secret_field_name,
            plugin_capabilities=lambda _pid: {},
            capability_bool=lambda *_args, **_kwargs: False,
            capability_int=lambda *_args, **_kwargs: 100,
        )

        self.assertEqual(offline.stage_plugin_options("llm_processing"), [("llm.a", "LLM.A"), ("llm.b", "LLM.B")])
        self.assertEqual(online.stage_plugin_options("llm_processing"), [("llm.b", "LLM.B")])

    def test_stage_defaults_skip_empty_secret_fields(self) -> None:
        schema = SimpleNamespace(
            settings=[
                SimpleNamespace(key="model_id", value="demo"),
                SimpleNamespace(key="api_key", value=""),
                SimpleNamespace(key="temperature", value="0.2"),
            ]
        )
        catalog = SimpleNamespace(schema_for=lambda _pid: schema)
        controller = StagePluginConfigController(
            get_catalog=lambda: catalog,
            config_data_provider=lambda: {"stages": {"llm_processing": {"plugin_id": "llm.demo"}}},
            offline_mode=lambda: False,
            coerce_setting_value=lambda value: float(value) if str(value) == "0.2" else value,
            is_secret_field_name=_is_secret_field_name,
            plugin_capabilities=lambda _pid: {},
            capability_bool=lambda *_args, **_kwargs: False,
            capability_int=lambda *_args, **_kwargs: 100,
        )

        self.assertEqual(controller.stage_defaults("llm_processing"), {"model_id": "demo", "temperature": 0.2})


if __name__ == "__main__":
    unittest.main()
