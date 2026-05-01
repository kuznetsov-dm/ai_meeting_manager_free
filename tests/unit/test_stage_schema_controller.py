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

from aimn.ui.controllers.stage_schema_controller import StageSchemaController
from aimn.ui.tabs.contracts import SettingField, SettingOption


def _setting(key: str, value: object, *, options: list[tuple[str, str]] | None = None):
    opts = [SimpleNamespace(label=label, value=raw) for label, raw in (options or [])]
    return SimpleNamespace(
        key=key,
        label=key,
        value=value,
        options=opts,
        editable=True,
    )


class TestStageSchemaController(unittest.TestCase):
    def _make_controller(self) -> StageSchemaController:
        schema = SimpleNamespace(
            settings=[
                _setting("model_id", "default"),
                _setting("api_key", ""),
                _setting("temperature", "0.2"),
            ]
        )
        catalog = SimpleNamespace(schema_for=lambda _pid: schema)
        config = {"stages": {"llm_processing": {"params": {"model_id": "missing-model"}}}}
        return StageSchemaController(
            get_catalog=lambda: catalog,
            config_data_provider=lambda: config,
            is_transcription_local_plugin=lambda _pid: False,
            whisper_models_state=lambda: ([], []),
            model_options_for=lambda _pid: [SettingOption(label="M1", value="m1")],
            load_agenda_catalog=lambda: [],
            load_project_catalog=lambda: [],
            coerce_setting_value=lambda value: value,
            is_secret_field_name=lambda key: str(key).strip().lower() in {"api_key"},
        )

    def test_sanitize_params_for_plugin_filters_unknown(self) -> None:
        controller = self._make_controller()
        payload = {"model_id": "m1", "temperature": 0.3, "unknown": True}
        sanitized = controller.sanitize_params_for_plugin("llm.test", payload)
        self.assertIn("model_id", sanitized)
        self.assertIn("temperature", sanitized)
        self.assertNotIn("unknown", sanitized)

    def test_sanitize_params_for_plugin_keeps_orchestrator_prompt_signature(self) -> None:
        controller = self._make_controller()
        payload = {"model_id": "m1", "prompt_signature": "sig-v1", "unknown": True}
        sanitized = controller.sanitize_params_for_plugin("llm.test", payload)
        self.assertEqual(sanitized.get("prompt_signature"), "sig-v1")
        self.assertNotIn("unknown", sanitized)

    def test_sanitize_params_for_plugin_promotes_orchestrator_model_to_model_id(self) -> None:
        controller = self._make_controller()
        payload = {"model": "qwen/qwen3-coder:free", "unknown": True}
        sanitized = controller.sanitize_params_for_plugin("llm.test", payload)
        self.assertEqual(sanitized.get("model"), "qwen/qwen3-coder:free")
        self.assertEqual(sanitized.get("model_id"), "qwen/qwen3-coder:free")
        self.assertNotIn("unknown", sanitized)

    def test_inline_settings_keys_excludes_secret_and_prefers_options(self) -> None:
        controller = self._make_controller()
        schema = [
            SettingField(key="api_key", label="API key", value="", options=[], editable=True),
            SettingField(
                key="model_id",
                label="Model",
                value="m1",
                options=[SettingOption(label="M1", value="m1")],
                editable=True,
            ),
            SettingField(key="temperature", label="Temp", value="0.2", options=[], editable=True),
        ]
        keys = controller.inline_settings_keys({"ui": {"inline_settings": ["api_key", "model_id", "temperature"]}}, schema)
        self.assertEqual(keys, ["model_id"])

    def test_schema_for_llm_uses_available_model_options_only(self) -> None:
        controller = self._make_controller()
        fields = controller.schema_for("llm.test", stage_id="llm_processing")
        model_field = next((field for field in fields if field.key == "model_id"), None)
        self.assertIsNotNone(model_field)
        values = [option.value for option in (model_field.options or [])]
        self.assertIn("m1", values)
        self.assertNotIn("missing-model", values)

    def test_schema_for_llm_local_model_id_is_not_editable(self) -> None:
        schema = SimpleNamespace(settings=[_setting("model_id", "default")])
        catalog = SimpleNamespace(schema_for=lambda _pid: schema)
        controller = StageSchemaController(
            get_catalog=lambda: catalog,
            config_data_provider=lambda: {"stages": {"llm_processing": {"params": {}}}},
            is_transcription_local_plugin=lambda _pid: False,
            whisper_models_state=lambda: ([], []),
            model_options_for=lambda _pid: [SettingOption(label="M1", value="m1")],
            is_local_models_plugin=lambda _pid: True,
            load_agenda_catalog=lambda: [],
            load_project_catalog=lambda: [],
            coerce_setting_value=lambda value: value,
            is_secret_field_name=lambda _key: False,
        )
        fields = controller.schema_for("llm.local", stage_id="llm_processing")
        model_field = next((field for field in fields if field.key == "model_id"), None)
        self.assertIsNotNone(model_field)
        self.assertFalse(bool(model_field.editable))

    def test_schema_for_management_includes_prompt_fields(self) -> None:
        catalog = SimpleNamespace(schema_for=lambda _pid: None)
        config = {"stages": {"management": {"params": {"prompt_project_ids": "project-1"}}}}
        controller = StageSchemaController(
            get_catalog=lambda: catalog,
            config_data_provider=lambda: config,
            is_transcription_local_plugin=lambda _pid: False,
            whisper_models_state=lambda: ([], []),
            model_options_for=lambda _pid: [],
            load_agenda_catalog=lambda: [{"id": "agenda-1", "title": "Roadmap"}],
            load_project_catalog=lambda: [{"project_id": "project-1", "name": "Apollo"}],
            coerce_setting_value=lambda value: value,
            is_secret_field_name=lambda _key: False,
        )

        fields = controller.schema_for("management.unified", stage_id="management")
        by_key = {field.key: field for field in fields}
        self.assertIn("prompt_agenda_id", by_key)
        self.assertIn("prompt_project_ids", by_key)
        options = [opt.value for opt in (by_key["prompt_agenda_id"].options or [])]
        self.assertIn("agenda-1", options)
        self.assertEqual(by_key["prompt_project_ids"].value, "project-1")
        self.assertTrue(bool(by_key["prompt_project_ids"].multi_select))

    def test_schema_for_management_project_options_support_id_key_and_placeholder(self) -> None:
        catalog = SimpleNamespace(schema_for=lambda _pid: None)
        controller = StageSchemaController(
            get_catalog=lambda: catalog,
            config_data_provider=lambda: {"stages": {"management": {"params": {}}}},
            is_transcription_local_plugin=lambda _pid: False,
            whisper_models_state=lambda: ([], []),
            model_options_for=lambda _pid: [],
            load_agenda_catalog=lambda: [],
            load_project_catalog=lambda: [{"id": "project-42", "name": "Phoenix"}],
            coerce_setting_value=lambda value: value,
            is_secret_field_name=lambda _key: False,
        )

        fields = controller.schema_for("management.unified", stage_id="management")
        by_key = {field.key: field for field in fields}
        project_options = [opt.value for opt in (by_key["prompt_project_ids"].options or [])]
        self.assertIn("", project_options)
        self.assertIn("project-42", project_options)


if __name__ == "__main__":
    unittest.main()
