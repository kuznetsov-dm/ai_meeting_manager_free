# ruff: noqa: I001
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

from aimn.ui.controllers.stage_runtime_controller import StageRuntimeState  # noqa: E402
from aimn.ui.controllers.stage_view_model_composer import StageViewModelComposer  # noqa: E402
from aimn.ui.tabs.contracts import SettingField  # noqa: E402


class TestStageViewModelComposer(unittest.TestCase):
    def _composer(
        self,
        *,
        config_data: dict,
        states: dict[str, StageRuntimeState],
        input_files: list[str],
        plugin_available: bool = True,
        current_meeting: object | None = None,
    ) -> StageViewModelComposer:
        schema = [SettingField(key="model_id", label="Model", value="", options=[], editable=True)]
        catalog = SimpleNamespace(plugin_by_id=lambda _pid: SimpleNamespace(highlights="", description=""))
        return StageViewModelComposer(
            current_stage_states=lambda: states,
            is_stage_disabled=lambda _stage_id: False,
            stage_display_name=lambda stage_id: stage_id,
            stage_short_name=lambda stage_id: stage_id,
            config_data_provider=lambda: config_data,
            input_files_provider=lambda: list(input_files),
            active_meeting_base_name_provider=lambda: "m1",
            active_meeting_source_path_provider=lambda: "m1.wav",
            stage_plugin_options=lambda stage_id: [("llm.openrouter", "OpenRouter")] if stage_id == "llm_processing" else [],
            stage_defaults=lambda _stage_id: {},
            schema_for=lambda _plugin_id, _stage_id: list(schema),
            inline_settings_keys=lambda _stage_config, _schema: [],
            supports_transcription_quality_presets=lambda _pid: False,
            order_transcription_providers=lambda providers: providers,
            whisper_models_state=lambda: ([], []),
            text_processing_provider_group=lambda _pid: "essentials",
            plugin_available=lambda _pid: plugin_available,
            llm_enabled_models_from_stage=lambda **_kwargs: ({}, "llm.openrouter"),
            llm_provider_models_payload=lambda *_args, **_kwargs: {"llm.openrouter": []},
            get_catalog=lambda: catalog,
            current_meeting_provider=lambda: current_meeting,
            normalize_ui_status=lambda status, **kwargs: ("ready", None) if kwargs.get("plugin_available") else ("idle", "bad"),
        )

    def test_media_convert_without_input_is_idle(self) -> None:
        composer = self._composer(
            config_data={"stages": {"media_convert": {"params": {}}}},
            states={"media_convert": StageRuntimeState(status="idle")},
            input_files=[],
        )
        view = composer.build_stage_view_model("media_convert")
        self.assertEqual(view.status, "idle")
        self.assertEqual(view.stage_id, "media_convert")

    def test_llm_processing_with_input_and_plugin_becomes_ready(self) -> None:
        composer = self._composer(
            config_data={
                "stages": {"llm_processing": {"plugin_id": "llm.openrouter", "params": {}}},
            },
            states={"llm_processing": StageRuntimeState(status="idle")},
            input_files=["meeting.wav"],
            plugin_available=True,
        )
        view = composer.build_stage_view_model("llm_processing")
        self.assertEqual(view.status, "ready")
        self.assertEqual(view.plugin_id, "llm.openrouter")

    def test_management_with_plugin_ids_becomes_ready(self) -> None:
        composer = self._composer(
            config_data={
                "stages": {"management": {"plugin_ids": ["management.unified"], "params": {}}},
            },
            states={"management": StageRuntimeState(status="idle")},
            input_files=["meeting.wav"],
            plugin_available=True,
        )

        view = composer.build_stage_view_model("management")

        self.assertEqual(view.status, "ready")

    def test_transcription_uses_variants_metadata(self) -> None:
        composer = self._composer(
            config_data={
                "stages": {
                    "transcription": {
                        "variants": [
                            {"plugin_id": "transcription.whisperadvanced", "params": {"model": "small"}},
                            {"plugin_id": "transcription.alt_mock", "params": {"model": "medium"}},
                        ]
                    }
                }
            },
            states={"transcription": StageRuntimeState(status="idle")},
            input_files=["meeting.wav"],
            plugin_available=True,
        )
        composer._stage_plugin_options = (  # type: ignore[attr-defined]
            lambda stage_id: (
                [
                    ("transcription.whisperadvanced", "Whisper Advanced"),
                    ("transcription.alt_mock", "Whisper Alt"),
                ]
                if stage_id == "transcription"
                else []
            )
        )
        composer._supports_transcription_quality_presets = (  # type: ignore[attr-defined]
            lambda pid: pid in {"transcription.whisperadvanced", "transcription.alt_mock"}
        )

        view = composer.build_stage_view_model("transcription")
        self.assertEqual(view.plugin_id, "transcription.whisperadvanced")
        self.assertEqual(view.ui_metadata.get("selected_provider"), "transcription.whisperadvanced")
        self.assertEqual(
            view.ui_metadata.get("enabled_providers"),
            ["transcription.whisperadvanced", "transcription.alt_mock"],
        )
        self.assertEqual(
            view.ui_metadata.get("selected_models"),
            {
                "transcription.whisperadvanced": ["small"],
                "transcription.alt_mock": ["medium"],
            },
        )

    def test_transcription_preserves_multiple_models_for_same_provider(self) -> None:
        composer = self._composer(
            config_data={
                "stages": {
                    "transcription": {
                        "plugin_id": "transcription.whisperadvanced",
                        "variants": [
                            {"plugin_id": "transcription.whisperadvanced", "params": {"model": "small"}},
                            {"plugin_id": "transcription.whisperadvanced", "params": {"model": "medium"}},
                        ],
                    }
                }
            },
            states={"transcription": StageRuntimeState(status="idle")},
            input_files=["meeting.wav"],
            plugin_available=True,
        )
        composer._stage_plugin_options = (  # type: ignore[attr-defined]
            lambda stage_id: [("transcription.whisperadvanced", "Whisper Advanced")] if stage_id == "transcription" else []
        )
        composer._supports_transcription_quality_presets = (  # type: ignore[attr-defined]
            lambda pid: pid == "transcription.whisperadvanced"
        )

        view = composer.build_stage_view_model("transcription")

        self.assertEqual(view.plugin_id, "transcription.whisperadvanced")
        self.assertEqual(view.ui_metadata.get("enabled_providers"), ["transcription.whisperadvanced"])
        self.assertEqual(
            view.ui_metadata.get("selected_models"),
            {"transcription.whisperadvanced": ["small", "medium"]},
        )

    def test_llm_processing_splits_semantic_plugins_from_llm_providers(self) -> None:
        composer = self._composer(
            config_data={
                "stages": {
                    "llm_processing": {
                        "variants": [
                            {"plugin_id": "llm.openrouter", "params": {"model_id": "gpt-4.1"}},
                        ]
                    },
                    "text_processing": {
                        "variants": [
                            {"plugin_id": "text_processing.semantic_refiner", "params": {}},
                        ]
                    },
                }
            },
            states={"llm_processing": StageRuntimeState(status="idle")},
            input_files=["meeting.wav"],
            plugin_available=True,
        )
        composer._stage_plugin_options = (  # type: ignore[attr-defined]
            lambda stage_id: (
                [
                    ("llm.openrouter", "OpenRouter"),
                    ("text_processing.semantic_refiner", "Semantic Refiner"),
                ]
                if stage_id == "llm_processing"
                else []
            )
        )
        composer._text_processing_provider_group = (  # type: ignore[attr-defined]
            lambda pid: "essentials" if pid == "text_processing.semantic_refiner" else ""
        )

        view = composer.build_stage_view_model("llm_processing")
        self.assertEqual(view.ui_metadata.get("available_providers"), [("llm.openrouter", "OpenRouter")])
        self.assertEqual(
            view.ui_metadata.get("semantic_available_providers"),
            [("semantic", "Semantic")],
        )
        self.assertEqual(
            view.ui_metadata.get("semantic_enabled_models"),
            {"semantic": ["text_processing.semantic_refiner"]},
        )

    def test_llm_processing_marks_mock_summary_from_latest_run_warning(self) -> None:
        meeting = SimpleNamespace(
            pipeline_runs=[
                SimpleNamespace(
                    warnings=[
                        "llm_processing:mock_fallback",
                        "llm_processing:llama_cli_timeout",
                    ]
                )
            ]
        )
        composer = self._composer(
            config_data={
                "stages": {"llm_processing": {"plugin_id": "llm.openrouter", "params": {}}},
            },
            states={"llm_processing": StageRuntimeState(status="completed", progress=100)},
            input_files=["meeting.wav"],
            current_meeting=meeting,
        )

        view = composer.build_stage_view_model("llm_processing")

        self.assertTrue(view.ui_metadata.get("mock_summary"))
        self.assertEqual(view.ui_metadata.get("mock_summary_reason"), "llama_cli_timeout")
        self.assertEqual(view.ui_metadata.get("mock_summary_reason_label"), "Llama cli timeout")

    def test_llm_processing_ignores_mock_flag_while_stage_is_running(self) -> None:
        meeting = SimpleNamespace(
            pipeline_runs=[SimpleNamespace(warnings=["llm_processing:mock_fallback"])]
        )
        composer = self._composer(
            config_data={
                "stages": {"llm_processing": {"plugin_id": "llm.openrouter", "params": {}}},
            },
            states={"llm_processing": StageRuntimeState(status="running")},
            input_files=["meeting.wav"],
            current_meeting=meeting,
        )

        view = composer.build_stage_view_model("llm_processing")

        self.assertFalse(view.ui_metadata.get("mock_summary", False))

    def test_llm_processing_requests_all_provider_models(self) -> None:
        captured: dict[str, object] = {}

        def _payload(providers, **kwargs):
            captured["providers"] = list(providers)
            captured["available_only"] = kwargs.get("available_only")
            captured["enabled_models"] = kwargs.get("enabled_models")
            return {"llm.openrouter": []}

        composer = self._composer(
            config_data={
                "stages": {
                    "llm_processing": {
                        "variants": [
                            {"plugin_id": "llm.openrouter", "params": {"model_id": "m1"}},
                        ]
                    }
                }
            },
            states={"llm_processing": StageRuntimeState(status="idle")},
            input_files=["meeting.wav"],
            plugin_available=True,
        )
        composer._llm_enabled_models_from_stage = (  # type: ignore[attr-defined]
            lambda **_kwargs: ({"llm.openrouter": ["id:m1"]}, "llm.openrouter")
        )
        composer._llm_provider_models_payload = _payload  # type: ignore[attr-defined]
        composer._text_processing_provider_group = lambda _pid: ""  # type: ignore[attr-defined]

        composer.build_stage_view_model("llm_processing")

        self.assertEqual(captured.get("providers"), ["llm.openrouter"])
        self.assertEqual(captured.get("available_only"), False)
        self.assertEqual(captured.get("enabled_models"), {"llm.openrouter": ["id:m1"]})

    def test_llm_processing_keeps_real_llm_status_when_text_processing_is_also_running(self) -> None:
        composer = self._composer(
            config_data={
                "stages": {
                    "llm_processing": {"plugin_id": "llm.openrouter", "params": {}},
                    "text_processing": {"plugin_id": "text_processing.semantic_refiner", "params": {}},
                }
            },
            states={
                "llm_processing": StageRuntimeState(status="running", progress=60),
                "text_processing": StageRuntimeState(status="running", progress=10, error="semantic"),
            },
            input_files=["meeting.wav"],
            plugin_available=True,
        )

        view = composer.build_stage_view_model("llm_processing")

        self.assertEqual(view.status, "running")
        self.assertEqual(view.progress, 60)
        self.assertNotEqual(view.error, "semantic")


if __name__ == "__main__":
    unittest.main()
