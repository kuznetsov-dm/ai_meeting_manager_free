# ruff: noqa: E402, I001

import sys
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

# Some environments may already have an older installed `aimn` package imported.
# Ensure the local UI package directory participates in submodule resolution.
try:
    import aimn.ui as _aimn_ui

    local_ui_dir = src_root / "aimn" / "ui"
    local_ui_str = str(local_ui_dir)
    if hasattr(_aimn_ui, "__path__") and local_ui_str not in list(_aimn_ui.__path__):
        _aimn_ui.__path__.insert(0, local_ui_str)
except Exception:
    pass

from aimn.ui.meetings_tab_v2 import MeetingsTabV2, _ui_status_for_configured_stage


class TestMeetingsTabV2UiStatus(unittest.TestCase):
    def test_on_pipeline_event_schedules_active_meeting_refresh_for_artifact_written(self) -> None:
        events: list[tuple[str, object]] = []
        fake = SimpleNamespace(
            _log_service=SimpleNamespace(append_event=lambda event: events.append(("log", event.event_type))),
            _record_stage_activity=lambda event: events.append(("record", event.event_type)),
            _active_meeting_base_name="m-base",
            _refresh_history=lambda: events.append(("history", None)),
            _refresh_active_meeting=lambda **kwargs: events.append(("refresh", dict(kwargs))),
        )

        MeetingsTabV2._on_pipeline_event(
            fake,
            SimpleNamespace(event_type="artifact_written", base_name="m-base"),
        )

        self.assertEqual(
            events,
            [
                ("log", "artifact_written"),
                ("record", "artifact_written"),
                ("refresh", {"base_name": "m-base", "immediate": True}),
            ],
        )

    def test_on_pipeline_event_ignores_other_meeting_refresh(self) -> None:
        events: list[tuple[str, object]] = []
        fake = SimpleNamespace(
            _log_service=SimpleNamespace(append_event=lambda event: events.append(("log", event.event_type))),
            _record_stage_activity=lambda event: events.append(("record", event.event_type)),
            _active_meeting_base_name="m-base",
            _refresh_history=lambda: events.append(("history", None)),
            _refresh_active_meeting=lambda **kwargs: events.append(("refresh", dict(kwargs))),
        )

        MeetingsTabV2._on_pipeline_event(
            fake,
            SimpleNamespace(event_type="artifact_written", base_name="other-base"),
        )

        self.assertEqual(
            events,
            [
                ("log", "artifact_written"),
                ("record", "artifact_written"),
            ],
        )

    def test_on_pipeline_event_refreshes_history_for_stage_terminal_events(self) -> None:
        events: list[tuple[str, object]] = []
        fake = SimpleNamespace(
            _log_service=SimpleNamespace(append_event=lambda event: events.append(("log", event.event_type))),
            _record_stage_activity=lambda event: events.append(("record", event.event_type)),
            _active_meeting_base_name="m-base",
            _refresh_history=lambda: events.append(("history", None)),
            _refresh_active_meeting=lambda **kwargs: events.append(("refresh", dict(kwargs))),
        )

        MeetingsTabV2._on_pipeline_event(
            fake,
            SimpleNamespace(event_type="stage_finished", base_name="m-base"),
        )

        self.assertEqual(
            events,
            [
                ("log", "stage_finished"),
                ("record", "stage_finished"),
                ("history", None),
                ("refresh", {"base_name": "m-base"}),
            ],
        )

    def test_restore_selected_artifact_reselects_kind_and_version(self) -> None:
        events: list[tuple[str, object]] = []
        fake = SimpleNamespace(
            _selected_artifact_kind="summary",
            _selected_artifact_stage_id="llm_processing",
            _selected_artifact_alias="A7",
            _text_panel=SimpleNamespace(
                select_artifact_kind=lambda kind: events.append(("kind", kind)),
                select_version=lambda **kwargs: events.append(("version", dict(kwargs))),
            ),
        )

        MeetingsTabV2._restore_selected_artifact(fake)

        self.assertEqual(
            events,
            [
                ("kind", "summary"),
                ("version", {"stage_id": "llm_processing", "alias": "A7", "kind": "summary"}),
            ],
        )

    def test_fmt_returns_template_when_format_args_are_missing(self) -> None:
        fake = SimpleNamespace(_tr=lambda _key, default: default)

        result = MeetingsTabV2._fmt(fake, "demo.key", "Hello {name}", missing="x")

        self.assertEqual(result, "Hello {name}")

    def test_emit_slow_path_log_tolerates_runtime_error_from_log_service(self) -> None:
        class _BrokenLogService:
            def append_message(self, *_args, **_kwargs) -> None:
                raise RuntimeError("log unavailable")

        fake = SimpleNamespace(_log_service=_BrokenLogService())

        MeetingsTabV2._emit_slow_path_log(
            fake,
            name="demo.path",
            started_at=0.0,
            threshold_ms=1,
            details={"value": 1},
        )

    def test_build_runtime_config_retries_without_prompt_signature_for_legacy_controller(self) -> None:
        class _LegacyController:
            def __init__(self) -> None:
                self.calls = 0

            def build_runtime_config(
                self,
                config_data,
                *,
                pipeline_preset,
                sanitize_params_for_plugin,
                model_available_for_plugin=None,
            ):
                self.calls += 1
                return {
                    "config_data": config_data,
                    "pipeline_preset": pipeline_preset,
                    "sanitized": sanitize_params_for_plugin("llm.legacy", {"a": 1}),
                    "model_ok": None
                    if model_available_for_plugin is None
                    else model_available_for_plugin("llm.legacy", {"model_id": "demo"}),
                }

        controller = _LegacyController()
        fake = SimpleNamespace(
            _pipeline_runtime_config_controller=controller,
            _pipeline_preset="offline",
            _sanitize_params_for_plugin=lambda plugin_id, params: {
                "plugin_id": plugin_id,
                **dict(params),
            },
            _is_stage_model_available=lambda _plugin_id, _params: True,
            _compute_llm_prompt_signature=lambda profile_id, custom_prompt: (
                f"{profile_id}:{len(custom_prompt)}"
            ),
            _config_data={"stages": {"llm_processing": {"params": {"prompt_profile": "standard"}}}},
        )

        payload = MeetingsTabV2._build_runtime_config(fake)

        self.assertEqual(controller.calls, 1)
        self.assertEqual(payload["pipeline_preset"], "offline")
        self.assertEqual(payload["sanitized"]["plugin_id"], "llm.legacy")
        self.assertTrue(payload["model_ok"])

    def test_configured_stage_is_ready_with_input(self) -> None:
        status, error = _ui_status_for_configured_stage(
            "idle",
            has_input=True,
            is_enabled=True,
            plugin_id="transcription.whisperadvanced",
            plugin_available=True,
        )
        self.assertEqual(status, "ready")
        self.assertIsNone(error)

    def test_missing_plugin_explains_idle(self) -> None:
        status, error = _ui_status_for_configured_stage(
            "idle",
            has_input=True,
            is_enabled=True,
            plugin_id="transcription.whatever",
            plugin_available=False,
        )
        self.assertEqual(status, "idle")
        self.assertIsInstance(error, str)
        self.assertIn("not available/enabled", error)

    def test_no_input_keeps_idle(self) -> None:
        status, error = _ui_status_for_configured_stage(
            "idle",
            has_input=False,
            is_enabled=True,
            plugin_id="transcription.whisperadvanced",
            plugin_available=True,
        )
        self.assertEqual(status, "idle")
        self.assertIsNone(error)

    def test_disabled_wins(self) -> None:
        status, error = _ui_status_for_configured_stage(
            "idle",
            has_input=True,
            is_enabled=False,
            plugin_id="transcription.whisperadvanced",
            plugin_available=True,
        )
        self.assertEqual(status, "disabled")
        self.assertIsNone(error)

    def test_effective_force_run_from_ignores_dirty_stage_for_plain_run(self) -> None:
        panel = SimpleNamespace(selected_stage_id=lambda: "transcription")
        fake = SimpleNamespace(
            _pipeline_panel=panel,
            _is_single_active_meeting_run=lambda _files: True,
            _is_stage_disabled=lambda _stage_id: False,
            _is_stage_dirty=lambda stage_id: stage_id == "llm_processing",
            _first_dirty_stage_id=lambda: "llm_processing",
            _can_auto_rerun_from_stage=lambda _stage_id: True,
        )
        stage = MeetingsTabV2._effective_force_run_from(
            fake,
            files=["demo.wav"],
            requested_stage_id=None,
            force_run_flag=False,
        )
        self.assertIsNone(stage)

    def test_effective_force_run_from_ignores_selected_dirty_stage_for_plain_run(self) -> None:
        panel = SimpleNamespace(selected_stage_id=lambda: "transcription")
        fake = SimpleNamespace(
            _pipeline_panel=panel,
            _is_single_active_meeting_run=lambda _files: True,
            _is_stage_disabled=lambda _stage_id: False,
            _is_stage_dirty=lambda stage_id: stage_id == "transcription",
            _first_dirty_stage_id=lambda: "llm_processing",
            _can_auto_rerun_from_stage=lambda _stage_id: True,
        )
        stage = MeetingsTabV2._effective_force_run_from(
            fake,
            files=["demo.wav"],
            requested_stage_id=None,
            force_run_flag=False,
        )
        self.assertIsNone(stage)

    def test_effective_force_run_from_uses_explicit_requested_stage(self) -> None:
        panel = SimpleNamespace(selected_stage_id=lambda: "transcription")
        fake = SimpleNamespace(
            _pipeline_panel=panel,
            _is_single_active_meeting_run=lambda _files: True,
            _is_stage_disabled=lambda _stage_id: False,
            _is_stage_dirty=lambda stage_id: stage_id == "transcription",
            _first_dirty_stage_id=lambda: "llm_processing",
            _can_auto_rerun_from_stage=lambda _stage_id: True,
        )
        stage = MeetingsTabV2._effective_force_run_from(
            fake,
            files=["demo.wav"],
            requested_stage_id="llm_processing",
            force_run_flag=False,
        )
        self.assertEqual(stage, "llm_processing")

    def test_effective_force_run_from_skips_implicit_rerun_even_when_stage_is_dirty(self) -> None:
        panel = SimpleNamespace(selected_stage_id=lambda: "llm_processing")
        fake = SimpleNamespace(
            _pipeline_panel=panel,
            _is_single_active_meeting_run=lambda _files: True,
            _is_stage_disabled=lambda _stage_id: False,
            _is_stage_dirty=lambda stage_id: stage_id == "llm_processing",
            _first_dirty_stage_id=lambda: "llm_processing",
            _can_auto_rerun_from_stage=lambda _stage_id: False,
        )
        stage = MeetingsTabV2._effective_force_run_from(
            fake,
            files=["demo.wav"],
            requested_stage_id=None,
            force_run_flag=False,
        )
        self.assertIsNone(stage)

    def test_plugin_id_from_runtime_message_prefers_actual_provider_prefix(self) -> None:
        catalog = SimpleNamespace(plugin_by_id=lambda pid: object() if pid == "llm.ollama" else None)
        fake = SimpleNamespace(_get_catalog=lambda: catalog)
        plugin_id = MeetingsTabV2._plugin_id_from_runtime_message(
            fake,
            "llm.ollama:phi3:mini (2/8)",
        )
        self.assertEqual(plugin_id, "llm.ollama")

    def test_runtime_active_plugin_id_falls_back_to_selected_when_no_runtime_message(self) -> None:
        catalog = SimpleNamespace(plugin_by_id=lambda pid: object() if pid == "llm.ollama" else None)

        class _Fake:
            def _get_catalog(self):
                return catalog

            def _current_stage_states(self):
                return {"llm_processing": SimpleNamespace(last_message="")}

            def _selected_plugin_id(self, _sid):
                return "llm.deepseek"

            def _plugin_id_from_runtime_message(self, message: str) -> str:
                return MeetingsTabV2._plugin_id_from_runtime_message(self, message)

        plugin_id = MeetingsTabV2._runtime_active_plugin_id(_Fake(), "llm_processing")
        self.assertEqual(plugin_id, "llm.deepseek")

    def test_runtime_active_plugin_id_prefers_real_llm_stage_over_text_processing(self) -> None:
        catalog = SimpleNamespace(
            plugin_by_id=lambda pid: object() if pid in {"llm.llama_cli", "llm.deepseek"} else None
        )

        class _Fake:
            def _get_catalog(self):
                return catalog

            def _current_stage_states(self):
                return {
                    "llm_processing": SimpleNamespace(
                        status="running",
                        last_message="llm.llama_cli:Qwen/Qwen3-1.7B-GGUF (2/4)",
                    ),
                    "text_processing": SimpleNamespace(
                        status="running",
                        last_message="llm.deepseek:deepseek-chat",
                    ),
                }

            def _selected_plugin_id(self, _sid):
                return "llm.deepseek"

            def _plugin_id_from_runtime_message(self, message: str) -> str:
                return MeetingsTabV2._plugin_id_from_runtime_message(self, message)

        plugin_id = MeetingsTabV2._runtime_active_plugin_id(_Fake(), "llm_processing")
        self.assertEqual(plugin_id, "llm.llama_cli")

    def test_running_stage_id_prefers_llm_processing_when_both_ai_stages_are_running(self) -> None:
        fake = SimpleNamespace(
            _current_stage_states=lambda: {
                "text_processing": SimpleNamespace(status="running"),
                "llm_processing": SimpleNamespace(status="running"),
            }
        )

        stage_id = MeetingsTabV2._running_stage_id(fake)
        self.assertEqual(stage_id, "llm_processing")

    def test_on_plugin_models_changed_invalidates_cache_and_rerenders_open_drawer(self) -> None:
        calls: list[tuple[str, object]] = []

        fake = SimpleNamespace(
            _model_catalog_controller=SimpleNamespace(
                invalidate_provider_cache=lambda plugin_id: calls.append(("invalidate", plugin_id))
            ),
            refresh_plugin_catalog_state=lambda: calls.append(("refresh", None)),
            _pipeline_panel=SimpleNamespace(is_settings_open=lambda: True),
            _rerender_timer=SimpleNamespace(start=lambda value: calls.append(("rerender", value))),
        )

        MeetingsTabV2.on_plugin_models_changed(fake, "llm.llama_cli")

        self.assertEqual(
            calls,
            [
                ("invalidate", "llm.llama_cli"),
                ("refresh", None),
                ("rerender", 0),
            ],
        )

    def test_on_plugin_models_changed_ignores_blank_plugin_id(self) -> None:
        calls: list[tuple[str, object]] = []

        fake = SimpleNamespace(
            _model_catalog_controller=SimpleNamespace(
                invalidate_provider_cache=lambda plugin_id: calls.append(("invalidate", plugin_id))
            ),
            refresh_plugin_catalog_state=lambda: calls.append(("refresh", None)),
            _pipeline_panel=SimpleNamespace(is_settings_open=lambda: True),
            _rerender_timer=SimpleNamespace(start=lambda value: calls.append(("rerender", value))),
        )

        MeetingsTabV2.on_plugin_models_changed(fake, " ")

        self.assertEqual(calls, [])

    def test_startup_prewarm_plugin_ids_include_enabled_server_plugin_outside_pipeline(self) -> None:
        catalog = SimpleNamespace(
            enabled_plugins=lambda: [
                SimpleNamespace(plugin_id="llm.ollama"),
                SimpleNamespace(plugin_id="llm.zai"),
            ]
        )

        class _Fake:
            _config_data = {
                "stages": {
                    "llm_processing": {
                        "plugin_id": "llm.zai",
                    }
                }
            }
            _settings_store = SimpleNamespace(
                get_settings=lambda plugin_id, include_secrets=True: (
                    {"auto_start_server": True} if plugin_id == "llm.ollama" else {}
                )
            )

            def _pipeline_configured_plugin_ids(self):
                return ["llm.zai"]

            def _get_catalog(self):
                return catalog

            def _plugin_enabled_for_config(self, plugin_id: str) -> bool:
                return plugin_id in {"llm.ollama", "llm.zai"}

            def _plugin_capabilities(self, plugin_id: str) -> dict:
                if plugin_id == "llm.ollama":
                    return {"health": {"server": {"auto_start_action": "start_server"}}}
                return {}

        targets = MeetingsTabV2._startup_prewarm_plugin_ids(_Fake())

        self.assertEqual(targets, ["llm.zai", "llm.ollama"])

    def test_startup_prewarm_plugin_ids_skip_server_plugin_when_auto_start_disabled(self) -> None:
        catalog = SimpleNamespace(
            enabled_plugins=lambda: [SimpleNamespace(plugin_id="llm.ollama")]
        )

        class _Fake:
            _settings_store = SimpleNamespace(
                get_settings=lambda plugin_id, include_secrets=True: {"auto_start_server": False}
            )

            def _pipeline_configured_plugin_ids(self):
                return []

            def _get_catalog(self):
                return catalog

            def _plugin_enabled_for_config(self, plugin_id: str) -> bool:
                return plugin_id == "llm.ollama"

            def _plugin_capabilities(self, plugin_id: str) -> dict:
                return {"health": {"server": {"auto_start_action": "start_server"}}}

        targets = MeetingsTabV2._startup_prewarm_plugin_ids(_Fake())

        self.assertEqual(targets, [])

    def test_startup_prewarm_plugin_ids_tolerate_catalog_runtime_error(self) -> None:
        class _Catalog:
            def enabled_plugins(self):
                raise RuntimeError("catalog unavailable")

        class _Fake:
            def _pipeline_configured_plugin_ids(self):
                return ["llm.zai"]

            def _get_catalog(self):
                return _Catalog()

            def _plugin_enabled_for_config(self, plugin_id: str) -> bool:
                return plugin_id == "llm.zai"

            def _plugin_capabilities(self, plugin_id: str) -> dict:
                return {}

            _settings_store = SimpleNamespace(get_settings=lambda *args, **kwargs: {})

        targets = MeetingsTabV2._startup_prewarm_plugin_ids(_Fake())

        self.assertEqual(targets, ["llm.zai"])

    def test_pipeline_meta_tolerates_registry_value_error(self) -> None:
        class _Catalog:
            def load(self):
                raise ValueError("bad registry")

        fake = SimpleNamespace(
            _catalog_service=_Catalog(),
            _pipeline_ui_state_controller=SimpleNamespace(
                pipeline_meta=lambda **kwargs: dict(kwargs)
            ),
            _pipeline_panel=SimpleNamespace(selected_stage_id=lambda: "llm_processing"),
            _config_source="default",
            _config_path="config/settings/pipeline/default.json",
            _overrides=[],
            _pipeline_preset="default",
            _active_meeting_base_name="m-base",
            _active_meeting_source_path="input.wav",
            _active_meeting_status=lambda: "completed",
            _input_files=[],
            _default_rerun_stage=lambda: "",
        )

        payload = MeetingsTabV2._pipeline_meta(fake)

        self.assertEqual(payload["plugin_registry"], {})

    def test_is_single_active_meeting_run_falls_back_to_raw_paths_when_resolve_fails(self) -> None:
        fake = SimpleNamespace(
            _active_meeting_base_name="m-base",
            _active_meeting_path=lambda: "C:/demo/input.wav",
        )

        with patch("aimn.ui.meetings_tab_v2.Path.resolve", side_effect=RuntimeError("resolve failed")):
            result = MeetingsTabV2._is_single_active_meeting_run(fake, ["C:/demo/input.wav"])

        self.assertTrue(result)

    def test_navigate_to_management_evidence_applies_immediately_for_active_meeting(self) -> None:
        calls: list[tuple[str, object]] = []

        class _History:
            def select_by_base_name(self, base_name: str) -> None:
                calls.append(("history", base_name))

        class _Fake:
            _active_meeting_base_name = "m-base"
            _active_meeting_manifest = object()
            _pending_management_navigation = None
            _history_panel = _History()

            def _resolve_meeting_base(self, key: str) -> str:
                return key

            def _apply_pending_management_navigation_if_ready(self, base: str) -> None:
                calls.append(("apply", base))

            def _on_meeting_selected(self, base: str) -> None:
                calls.append(("select", base))

        MeetingsTabV2.navigate_to_management_evidence(
            _Fake(),
            {
                "meeting_id": "m-base",
                "source_kind": "summary",
                "source_alias": "A1",
                "query": "budget",
            },
        )

        self.assertIn(("history", "m-base"), calls)
        self.assertIn(("apply", "m-base"), calls)
        self.assertNotIn(("select", "m-base"), calls)

    def test_navigate_to_management_evidence_tolerates_runtime_error_from_history_panel(self) -> None:
        calls: list[tuple[str, object]] = []

        class _History:
            def select_by_base_name(self, _base_name: str) -> None:
                raise RuntimeError("history unavailable")

        class _Fake:
            _active_meeting_base_name = "m-base"
            _active_meeting_manifest = object()
            _pending_management_navigation = None
            _history_panel = _History()

            def _resolve_meeting_base(self, key: str) -> str:
                return key

            def _apply_pending_management_navigation_if_ready(self, base: str) -> None:
                calls.append(("apply", base))

            def _on_meeting_selected(self, base: str) -> None:
                calls.append(("select", base))

        MeetingsTabV2.navigate_to_management_evidence(_Fake(), {"meeting_id": "m-base"})

        self.assertIn(("apply", "m-base"), calls)

    def test_current_meeting_manifest_for_ui_tolerates_missing_meeting(self) -> None:
        fake = SimpleNamespace(
            _active_meeting_manifest=None,
            _active_meeting_base_name="m-base",
            _artifact_service=SimpleNamespace(load_meeting=lambda _base: (_ for _ in ()).throw(FileNotFoundError("gone"))),
        )

        result = MeetingsTabV2._current_meeting_manifest_for_ui(fake)

        self.assertIsNone(result)

    def test_meeting_delete_request_tolerates_missing_manifest_preview(self) -> None:
        events: list[tuple[str, object]] = []

        fake = SimpleNamespace(
            _resolve_meeting_base=lambda key: key,
            _meeting_service=SimpleNamespace(
                load_by_base_name=lambda _base: (_ for _ in ()).throw(FileNotFoundError("gone"))
            ),
            _active_meeting_base_name="",
            _text_panel=SimpleNamespace(set_audio_path=lambda _path: events.append(("audio", _path))),
            _tr=lambda _key, default: default,
            _fmt=lambda _key, default, **kwargs: default.format(**kwargs),
            _meeting_actions_controller=SimpleNamespace(delete_meeting_files=lambda base: events.append(("delete", base))),
            _stage_runtime=SimpleNamespace(clear_meeting_states=lambda base: events.append(("clear", base))),
            _invalidate_meeting_payload_cache=lambda base: events.append(("invalidate", base)),
            _refresh_history=lambda: events.append(("history", None)),
            _refresh_pipeline_ui=lambda: events.append(("pipeline", None)),
            _app_root=repo_root,
        )

        with patch("aimn.ui.meetings_tab_v2.QMessageBox.question", return_value=0):
            MeetingsTabV2._on_meeting_delete_requested(fake, "m-base")

        self.assertEqual(events, [])

    def test_meeting_rename_request_warns_when_manifest_load_fails(self) -> None:
        warnings: list[tuple[str, str]] = []

        fake = SimpleNamespace(
            _resolve_meeting_base=lambda key: key,
            _meeting_service=SimpleNamespace(
                load_by_base_name=lambda _base: (_ for _ in ()).throw(RuntimeError("load failed"))
            ),
            _tr=lambda _key, default: default,
            _fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        with patch(
            "aimn.ui.meetings_tab_v2.QMessageBox.warning",
            side_effect=lambda _parent, title, message: warnings.append((title, message)),
        ):
            MeetingsTabV2._on_meeting_rename_requested(fake, "m-base")

        self.assertEqual(len(warnings), 1)
        self.assertIn("Rename failed", warnings[0][0])
        self.assertIn("load failed", warnings[0][1])

    def test_on_files_added_logs_meeting_load_failure_for_local_service_error(self) -> None:
        logs: list[str] = []
        fake = SimpleNamespace(
            _ad_hoc_input_files=[],
            _input_files=[],
            _active_meeting_base_name="",
            _text_panel=SimpleNamespace(set_audio_path=lambda _path: None),
            _meeting_service=SimpleNamespace(
                load_or_create=lambda _path: (_ for _ in ()).throw(RuntimeError("bad media")),
                save=lambda _meeting: None,
            ),
            _log_service=SimpleNamespace(append_message=lambda message: logs.append(str(message))),
            _fmt=lambda _key, default, **kwargs: default.format(**kwargs),
            _refresh_history=lambda **kwargs: None,
            _refresh_pipeline_ui=lambda: None,
            _set_meeting_status=lambda *_args, **_kwargs: None,
        )

        MeetingsTabV2._on_files_added(fake, [str(Path(__file__).resolve())])

        self.assertEqual(len(logs), 1)
        self.assertIn("Meeting load failed", logs[0])
        self.assertEqual(fake._active_meeting_base_name, "")

    def test_meeting_rename_request_warns_when_rename_operation_fails(self) -> None:
        warnings: list[tuple[str, str]] = []

        class _Dialog:
            def exec(self):
                return 1

            def title_text(self):
                return "New Title"

        fake = SimpleNamespace(
            _resolve_meeting_base=lambda key: key,
            _meeting_service=SimpleNamespace(
                load_by_base_name=lambda _base: SimpleNamespace(),
                rename_meeting=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rename failed")),
            ),
            _meeting_actions_controller=SimpleNamespace(
                meeting_display_title=lambda _meeting: "Current",
                meeting_topic_suggestions=lambda _base, meeting=None: [],
                meeting_rename_policy=lambda: ("metadata_only", False),
            ),
            _active_meeting_base_name="",
            _last_stage_base_name="",
            _invalidate_meeting_payload_cache=lambda _base: None,
            _refresh_history=lambda **kwargs: None,
            _refresh_pipeline_ui=lambda: None,
            _text_panel=SimpleNamespace(set_audio_path=lambda _path: None),
            _tr=lambda _key, default: default,
            _fmt=lambda _key, default, **kwargs: default.format(**kwargs),
        )

        with patch("aimn.ui.meetings_tab_v2._MeetingRenameDialog", return_value=_Dialog()):
            with patch(
                "aimn.ui.meetings_tab_v2.QMessageBox.warning",
                side_effect=lambda _parent, title, message: warnings.append((title, message)),
            ):
                MeetingsTabV2._on_meeting_rename_requested(fake, "m-base")

        self.assertEqual(len(warnings), 1)
        self.assertIn("Rename failed", warnings[0][0])
        self.assertIn("rename failed", warnings[0][1])

    def test_text_selection_changed_clears_inspection_when_meeting_load_fails(self) -> None:
        events: list[str] = []
        fake = SimpleNamespace(
            _active_meeting_base_name="m-base",
            _active_meeting_manifest=None,
            _artifact_service=SimpleNamespace(
                load_meeting=lambda _base: (_ for _ in ()).throw(FileNotFoundError("gone"))
            ),
            _inspection_panel=SimpleNamespace(clear=lambda: events.append("clear")),
            _render_inspection_html=lambda *_args, **_kwargs: "<html></html>",
        )

        MeetingsTabV2._on_text_selection_changed(fake, "llm_processing", "A1", "summary")

        self.assertEqual(events, ["clear"])

    def test_poll_registry_tolerates_catalog_runtime_error(self) -> None:
        events: list[tuple[str, object]] = []

        fake = SimpleNamespace(
            _global_search_controller=SimpleNamespace(poll_registry=lambda: events.append(("poll", None))),
            _catalog_service=SimpleNamespace(load=lambda: (_ for _ in ()).throw(RuntimeError("catalog failed"))),
            _registry_stamp="",
            _registry_poll_request_id=0,
            _registry_poll_running=False,
            _registry_poll_pending=False,
            _refresh_artifact_export_targets=lambda: events.append(("refresh_targets", None)),
            _sync_pipeline_config_plugins=lambda save_if_changed: events.append(("sync", save_if_changed)) or False,
            _refresh_pipeline_ui=lambda: events.append(("pipeline", None)),
        )

        def _run_async(*, request_id, fn, on_finished, on_error=None, thread_pool=None, args=(), kwargs=None):
            _ = thread_pool
            try:
                result = fn(*(args or ()), **(kwargs or {}))
            except Exception as exc:
                if on_error is not None:
                    on_error(request_id, exc)
                return None
            on_finished(request_id, result)
            return None

        with patch("aimn.ui.meetings_tab_v2.run_async", side_effect=_run_async):
            MeetingsTabV2._poll_registry(fake)

        self.assertEqual(events, [("poll", None)])

    def test_poll_registry_refreshes_after_async_stamp_change(self) -> None:
        events: list[tuple[str, object]] = []

        fake = SimpleNamespace(
            _global_search_controller=SimpleNamespace(poll_registry=lambda: events.append(("poll", None))),
            _catalog_service=SimpleNamespace(load=lambda: SimpleNamespace(stamp="new-stamp")),
            _registry_stamp="old-stamp",
            _registry_poll_request_id=0,
            _registry_poll_running=False,
            _registry_poll_pending=False,
            _refresh_artifact_export_targets=lambda: events.append(("refresh_targets", None)),
            _sync_pipeline_config_plugins=lambda save_if_changed: events.append(("sync", save_if_changed)) or True,
            _refresh_pipeline_ui=lambda: events.append(("pipeline", None)),
        )

        def _run_async(*, request_id, fn, on_finished, on_error=None, thread_pool=None, args=(), kwargs=None):
            _ = thread_pool
            try:
                result = fn(*(args or ()), **(kwargs or {}))
            except Exception as exc:
                if on_error is not None:
                    on_error(request_id, exc)
                return None
            on_finished(request_id, result)
            return None

        with patch("aimn.ui.meetings_tab_v2.run_async", side_effect=_run_async):
            MeetingsTabV2._poll_registry(fake)

        self.assertEqual(fake._registry_stamp, "new-stamp")
        self.assertEqual(
            events,
            [("poll", None), ("refresh_targets", None), ("sync", True), ("pipeline", None)],
        )

    def test_apply_pending_management_navigation_highlights_query(self) -> None:
        calls: list[tuple[str, object]] = []

        class _TextPanel:
            def select_artifact_kind(self, kind: str) -> None:
                calls.append(("kind", kind))

            def select_version(self, **kwargs) -> None:
                calls.append(("version", dict(kwargs)))

            def jump_to_transcript_segment(self, **kwargs) -> None:
                calls.append(("jump", dict(kwargs)))

            def highlight_query(self, query: str) -> None:
                calls.append(("query", query))

        fake = SimpleNamespace(
            _pending_management_navigation={
                "base_name": "m-base",
                "kind": "summary",
                "alias": "A77",
                "query": "launch memo",
                "segment_index": -1,
                "start_ms": -1,
            },
            _text_panel=_TextPanel(),
        )

        MeetingsTabV2._apply_pending_management_navigation_if_ready(fake, "m-base")

        self.assertIn(("kind", "summary"), calls)
        self.assertIn(("query", "launch memo"), calls)
        self.assertTrue(any(item[0] == "version" for item in calls))
        self.assertIsNone(fake._pending_management_navigation)

    def test_global_search_requested_clears_when_mode_not_global(self) -> None:
        events: list[tuple[str, object]] = []
        fake = SimpleNamespace(
            _global_search_controller=SimpleNamespace(
                normalize_mode=lambda _mode: "local",
                clear_global_search=lambda: events.append(("clear", None)),
            ),
            _global_search_request_id=0,
            _all_meetings=[],
        )

        MeetingsTabV2._on_global_search_requested(fake, "roadmap", "local")

        self.assertEqual(fake._global_search_request_id, 1)
        self.assertEqual(events, [("clear", None)])

    def test_global_search_requested_ignores_stale_async_result(self) -> None:
        events: list[tuple[str, object]] = []
        fake = SimpleNamespace(
            _global_search_controller=SimpleNamespace(
                normalize_mode=lambda _mode: "global",
                build_global_search_payload=lambda query, mode, all_meetings=None: {
                    "clear": False,
                    "query": query,
                    "hits": [],
                    "meeting_ids": set(),
                    "filtered_meetings": list(all_meetings or []),
                    "selected_base": "",
                    "status_text": f"{mode}:{query}",
                },
                apply_global_search_payload=lambda payload: events.append(("apply", dict(payload))),
                clear_global_search=lambda: events.append(("clear", None)),
            ),
            _global_search_request_id=0,
            _all_meetings=[SimpleNamespace(base_name="m-base", meeting_id="m-1")],
            _text_panel=SimpleNamespace(set_global_search_status=lambda text: events.append(("status", text))),
        )

        def _run_async(*, request_id, fn, on_finished, on_error=None, thread_pool=None, args=(), kwargs=None):
            _ = (thread_pool, on_error)
            result = fn(*(args or ()), **(kwargs or {}))
            fake._global_search_request_id = request_id + 1
            on_finished(request_id, result)
            return None

        with patch("aimn.ui.meetings_tab_v2.run_async", side_effect=_run_async):
            MeetingsTabV2._on_global_search_requested(fake, "roadmap", "global")

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
