import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from aimn.ui.widgets.model_cards import (
    _MODEL_JOB_STATES,
    ModelCardsPanel,
    _action_note_text,
    _apply_curated_model_metadata,
    _cloud_failure_code_from_probe_message,
    _compose_setup_message,
    _friendly_download_error,
)


class TestModelCardsSetupMessage(unittest.TestCase):
    def tearDown(self) -> None:
        _MODEL_JOB_STATES.clear()

    def test_compose_setup_message_includes_generic_actions_and_plugin_notes(self) -> None:
        text = _compose_setup_message(
            {},
            highlights="Local summaries without cloud calls.",
            howto=[
                "Open Settings > AI Processing.",
                "Download a model or select a local GGUF.",
            ],
        )

        self.assertIn("needs a local model", text)
        self.assertIn("1. Add a model from the catalog below, then download it.", text)
        self.assertIn("2. Add your own model entry or direct model-file URL if the provider supports it.", text)
        self.assertIn("3. Use a local model file from disk if the provider supports direct file selection.", text)
        self.assertIn("Local summaries without cloud calls.", text)
        self.assertIn("- Open Settings > AI Processing.", text)

    def test_remove_action_note_reports_removed_file(self) -> None:
        text = _action_note_text(
            {"models.note.model_removed": "Model removed: {value}"},
            "remove_model",
            "success",
            "model_removed",
            {"data": {"file": "Qwen3-4B-Q4_K_M.gguf"}},
            remove_action_id="remove_model",
        )

        self.assertEqual(text, "Model removed: Qwen3-4B-Q4_K_M.gguf")

    def test_apply_curated_model_metadata_clears_stale_local_binding(self) -> None:
        row = {
            "model_id": "Qwen/Qwen3-4B-GGUF",
            "product_name": "Old card",
            "file": "phi-4-mini-instruct-q4_k_m.gguf",
            "filename": "phi-4-mini-instruct-q4_k_m.gguf",
            "model_path": "models/llama/phi-4-mini-instruct-q4_k_m.gguf",
            "path": "models/llama/phi-4-mini-instruct-q4_k_m.gguf",
            "download_url": "https://stale.example/model.gguf",
            "source_url": "https://stale.example/repo",
            "size_hint": "9 GB",
            "user_added": False,
        }
        curated = {
            "model_name": "Qwen3 4B (GGUF)",
            "model_description": "Размер: 2.6 ГБ.",
            "quant": "Q4_K_M",
            "size_hint": "2.6 GB",
            "source_url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF",
            "catalog_source": "recommended",
        }

        updated = _apply_curated_model_metadata(row, curated, row["model_id"])

        self.assertEqual(updated["product_name"], "Qwen3 4B (GGUF)")
        self.assertEqual(updated["source_url"], "https://huggingface.co/Qwen/Qwen3-4B-GGUF")
        self.assertEqual(updated["download_url"], "")
        self.assertEqual(updated["size_hint"], "2.6 GB")
        self.assertNotIn("file", updated)
        self.assertNotIn("filename", updated)
        self.assertNotIn("model_path", updated)
        self.assertNotIn("path", updated)

    def test_pull_model_uses_background_action_runner(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cli"
        panel._labels = {}
        panel._pending_model_actions = {}
        panel._focus_model_after_render = ("", "")
        panel._note_text = ""
        panel._note_visible = False
        panel._note = SimpleNamespace(
            setText=lambda value: setattr(panel, "_note_text", value),
            setVisible=lambda value: setattr(panel, "_note_visible", bool(value)),
        )
        panel._render_current_plugin = lambda **_kwargs: None  # type: ignore[method-assign]
        panel._job_state_for = lambda plugin_id, model_id: None  # type: ignore[method-assign]
        panel._managed_actions_for = lambda plugin_id: {"pull": "download_model"}  # type: ignore[method-assign]
        captured: list[tuple[str, dict]] = []
        panel._run_action = lambda action_id, payload: captured.append((action_id, dict(payload)))  # type: ignore[method-assign]

        panel._pull_model("Qwen/Qwen3-4B-GGUF")

        self.assertEqual(
            captured,
            [("download_model", {"model_id": "Qwen/Qwen3-4B-GGUF"})],
        )
        self.assertEqual(
            panel._pending_model_actions,
            {("llm.llama_cli", "Qwen/Qwen3-4B-GGUF"): "download_model"},
        )
        self.assertEqual(panel._note_text, "Download started: Qwen/Qwen3-4B-GGUF")
        self.assertTrue(panel._note_visible)

    def test_toggle_model_emits_models_changed_when_using_models_service_fallback(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.remote"
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {}
        )
        updated: list[tuple[str, str, bool]] = []
        emitted: list[str] = []
        panel._models = SimpleNamespace(
            update_model_enabled=lambda plugin_id, model_id, enabled: updated.append((plugin_id, model_id, enabled))
        )
        panel._emit_models_changed = lambda plugin_id: emitted.append(plugin_id)  # type: ignore[method-assign]
        panel.set_plugin = lambda _pid: None  # type: ignore[method-assign]

        panel._toggle_model("m1", True)

        self.assertEqual(updated, [("llm.remote", "m1", True)])
        self.assertEqual(emitted, ["llm.remote"])

    def test_toggle_model_rejects_enable_for_local_model_that_is_not_downloaded(self) -> None:
        stored = {
            "models": [
                {
                    "model_id": "m1",
                    "product_name": "Model 1",
                    "enabled": False,
                    "installed": False,
                }
            ]
        }
        set_calls: list[dict[str, object]] = []
        notes: list[str] = []
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cpp"
        panel._labels = {}
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: dict(stored),
            set_settings=lambda _pid, payload, secret_fields, preserve_secrets: set_calls.append(dict(payload)),
        )
        panel._models = SimpleNamespace(update_model_enabled=lambda *_args: (_ for _ in ()).throw(AssertionError("fallback should not be used")))
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._is_local_model_available = lambda _pid, _settings, _entry: False  # type: ignore[method-assign]
        panel._set_note_message = lambda text: notes.append(text)  # type: ignore[method-assign]
        panel.set_plugin = lambda _pid: None  # type: ignore[method-assign]

        panel._toggle_model("m1", True)

        self.assertEqual(set_calls, [])
        self.assertEqual(notes, ["Only downloaded local models can be used from stage settings."])

    def test_toggle_model_appends_explicit_disabled_row_for_missing_model(self) -> None:
        stored = {
            "models": [
                {
                    "model_id": "other",
                    "product_name": "Other",
                    "enabled": True,
                }
            ]
        }
        saved: list[dict[str, object]] = []
        emitted: list[str] = []
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.remote"
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: dict(stored),
            set_settings=lambda _pid, payload, secret_fields, preserve_secrets: saved.append(dict(payload)),
        )
        panel._models = SimpleNamespace()
        panel._labels = {}
        panel._is_local_models_plugin = lambda _pid: False  # type: ignore[method-assign]
        panel._emit_models_changed = lambda plugin_id: emitted.append(plugin_id)  # type: ignore[method-assign]
        panel.set_plugin = lambda _pid: None  # type: ignore[method-assign]

        panel._toggle_model("m1", False)

        self.assertEqual(emitted, ["llm.remote"])
        self.assertEqual(len(saved), 1)
        models = saved[0]["models"]
        assert isinstance(models, list)
        by_id = {str(item["model_id"]): item for item in models if isinstance(item, dict)}
        self.assertFalse(by_id["m1"]["enabled"])
        self.assertNotIn("favorite", by_id["m1"])

    def test_toggle_model_enables_local_inventory_model_not_preexisting_in_settings(self) -> None:
        stored: dict[str, object] = {}
        saved: list[dict[str, object]] = []
        emitted: list[str] = []
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cpp"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: dict(stored),
            set_settings=lambda _pid, payload, secret_fields, preserve_secrets: (stored.clear(), stored.update(dict(payload)), saved.append(dict(payload))),
        )
        panel._models = SimpleNamespace(
            load_models_config=lambda _pid: []
        )
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={
                            "m1": {
                                "model_name": "Model 1",
                                "file": "model.gguf",
                                "source_url": "https://example.test/m1",
                            }
                        }
                    )
                )
            )
        )
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._is_local_model_available = lambda _pid, _settings, entry: str(entry.get("file", "")) == "model.gguf"  # type: ignore[method-assign]
        panel._sync_local_file_inventory = lambda _pid: None  # type: ignore[method-assign]
        panel._emit_models_changed = lambda plugin_id: emitted.append(plugin_id)  # type: ignore[method-assign]
        panel.set_plugin = lambda _pid: None  # type: ignore[method-assign]

        panel._toggle_model("m1", True)

        self.assertEqual(emitted, ["llm.llama_cpp"])
        self.assertTrue(saved)
        models = saved[-1]["models"]
        assert isinstance(models, list)
        by_id = {str(item["model_id"]): item for item in models if isinstance(item, dict)}
        self.assertTrue(by_id["m1"]["enabled"])
        self.assertTrue(by_id["m1"]["installed"])
        self.assertEqual(by_id["m1"]["file"], "model.gguf")
        self.assertNotIn("favorite", by_id["m1"])

    def test_friendly_download_error_for_ollama_missing_binary_includes_install_link(self) -> None:
        text = _friendly_download_error(
            {},
            "Ollama binary not found in PATH",
            {"data": {"model_id": "llama3.2"}},
            plugin_id="llm.ollama",
        )

        self.assertIn("Ollama is not installed on this computer.", text)
        self.assertIn("https://ollama.com/download", text)

    def test_friendly_download_error_for_ollama_server_not_running_is_human_readable(self) -> None:
        text = _friendly_download_error(
            {},
            "server_not_running",
            {"data": {"model_id": "llama3.2"}},
            plugin_id="llm.ollama",
        )

        self.assertIn("Ollama is not running.", text)
        self.assertIn("https://ollama.com/download", text)

    def test_build_entries_keeps_model_metadata_for_ollama_cards(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.ollama"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = False
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={},
                        capabilities={"models": {"storage": "local", "managed_actions": {"list": "list_models"}}},
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "_ollama_runtime_state": {
                    "ollama_installed": True,
                    "server_running": True,
                    "total": 1,
                },
                "models": [
                    {
                        "model_id": "llama3.2",
                        "product_name": "Llama 3.2",
                        "installed": True,
                        "status": "installed",
                        "source_url": "https://ollama.com/library/llama3.2",
                        "size_hint": "~2GB",
                        "description": "Meta local model",
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._status_for = lambda enabled, installed: ("Installed", "#fff", "#000")  # type: ignore[method-assign]
        panel._status_for_download = lambda job: ("Downloading", "#fff", "#000")  # type: ignore[method-assign]
        panel._file_installed = lambda _pid, _settings, _file: True  # type: ignore[method-assign]
        panel._file_size = lambda _pid, _settings, _file: 0  # type: ignore[method-assign]
        panel._format_bytes = lambda size: "0 B"  # type: ignore[method-assign]

        entries = panel._build_entries("llm.ollama")

        self.assertEqual(len(entries), 1)
        self.assertIn("Size: ~2GB", entries[0].meta_lines)
        self.assertIn("Source: https://ollama.com/library/llama3.2", entries[0].meta_lines)

    def test_build_entries_hides_stale_ollama_models_without_confirmed_runtime_state(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.ollama"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = False
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={},
                        capabilities={"models": {"storage": "local", "managed_actions": {"list": "list_models"}}},
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "llama3.2",
                        "product_name": "Llama 3.2",
                        "installed": True,
                        "status": "installed",
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._status_for = lambda enabled, installed: ("Installed", "#fff", "#000")  # type: ignore[method-assign]
        panel._status_for_download = lambda job: ("Downloading", "#fff", "#000")  # type: ignore[method-assign]
        panel._file_installed = lambda _pid, _settings, _file: True  # type: ignore[method-assign]
        panel._file_size = lambda _pid, _settings, _file: 0  # type: ignore[method-assign]
        panel._format_bytes = lambda size: "0 B"  # type: ignore[method-assign]

        entries = panel._build_entries("llm.ollama")

        self.assertEqual(entries, [])

    def test_build_entries_disables_favorite_toggle_for_not_downloaded_local_model(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cpp"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = False
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={
                            "m1": {
                                "model_name": "Model 1",
                                "description": "Local model",
                            }
                        },
                        capabilities={"models": {"storage": "local", "managed_actions": {"pull": "download_model"}}},
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "m1",
                        "product_name": "Model 1",
                        "favorite": False,
                        "installed": False,
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {"pull": "download_model"}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._is_local_model_available = lambda _pid, _settings, _entry: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._status_for = lambda enabled, installed: ("Not installed", "#fff", "#000")  # type: ignore[method-assign]
        panel._status_for_download = lambda job: ("Downloading", "#fff", "#000")  # type: ignore[method-assign]
        panel._file_size = lambda _pid, _settings, _file: 0  # type: ignore[method-assign]
        panel._format_bytes = lambda size: "0 B"  # type: ignore[method-assign]

        entries = panel._build_entries("llm.llama_cpp")

        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].can_toggle)
        self.assertTrue(entries[0].can_download)
        self.assertFalse(entries[0].can_remove)

    def test_build_entries_shows_remove_for_downloaded_local_model(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "transcription.whisperadvanced"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = True
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={"small": {"model_name": "Whisper Small", "file": "ggml-small.bin"}},
                        capabilities={
                            "models": {
                                "storage": "local",
                                "managed_actions": {"pull": "pull_model", "remove": "remove_model"},
                            }
                        },
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "small",
                        "product_name": "Whisper Small",
                        "file": "ggml-small.bin",
                        "installed": True,
                        "status": "installed",
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {"pull": "pull_model", "remove": "remove_model"}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._is_local_model_available = lambda _pid, _settings, _entry: True  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._status_for = lambda enabled, installed: ("Installed", "#fff", "#000")  # type: ignore[method-assign]
        panel._status_for_download = lambda job: ("Downloading", "#fff", "#000")  # type: ignore[method-assign]
        panel._file_size = lambda _pid, _settings, _file: 0  # type: ignore[method-assign]
        panel._format_bytes = lambda size: "0 B"  # type: ignore[method-assign]

        entries = panel._build_entries("transcription.whisperadvanced")

        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].can_download)
        self.assertTrue(entries[0].can_remove)

    def test_build_entries_hides_stale_llama_cli_models_without_local_file(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cli"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = True
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={},
                        capabilities={
                            "models": {
                                "storage": "local",
                                "local_files": {"root_setting": "cache_dir", "default_root": "models/llama", "glob": "*.gguf"},
                                "managed_actions": {"pull": "download_model", "remove": "remove_model"},
                            }
                        },
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "Qwen/Qwen3-4B-GGUF",
                        "product_name": "Qwen3 4B",
                        "file": "Qwen3-4B-Q4_K_M.gguf",
                        "installed": False,
                        "status": "",
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {"pull": "download_model", "remove": "remove_model"}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._is_local_model_available = lambda _pid, _settings, _entry: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._status_for = lambda enabled, installed: ("Needs setup", "#fff", "#000")  # type: ignore[method-assign]
        panel._status_for_download = lambda job: ("Downloading", "#fff", "#000")  # type: ignore[method-assign]
        panel._file_size = lambda _pid, _settings, _file: 0  # type: ignore[method-assign]
        panel._format_bytes = lambda size: "0 B"  # type: ignore[method-assign]

        entries = panel._build_entries("llm.llama_cli")

        self.assertEqual(entries, [])

    def test_build_entries_keeps_curated_llama_cli_starter_model_without_local_file(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cli"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = True
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={
                            "unsloth/Qwen3-0.6B-GGUF": {
                                "model_name": "Qwen3 0.6B (GGUF)",
                                "description": "Starter model",
                                "file": "Qwen3-0.6B-Q4_K_M.gguf",
                                "download_url": "https://example.test/qwen3-0.6b.gguf",
                            }
                        },
                        capabilities={
                            "models": {
                                "storage": "local",
                                "local_files": {"root_setting": "cache_dir", "default_root": "models/llama", "glob": "*.gguf"},
                                "managed_actions": {"pull": "download_model", "remove": "remove_model"},
                            }
                        },
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "unsloth/Qwen3-0.6B-GGUF",
                        "product_name": "Qwen3 0.6B (GGUF)",
                        "file": "Qwen3-0.6B-Q4_K_M.gguf",
                        "installed": False,
                        "status": "",
                        "catalog_source": "recommended",
                        "download_url": "https://example.test/qwen3-0.6b.gguf",
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {"pull": "download_model", "remove": "remove_model"}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._is_local_model_available = lambda _pid, _settings, _entry: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._status_for = lambda enabled, installed: ("Needs setup", "#fff", "#000")  # type: ignore[method-assign]
        panel._status_for_download = lambda job: ("Downloading", "#fff", "#000")  # type: ignore[method-assign]
        panel._file_size = lambda _pid, _settings, _file: 0  # type: ignore[method-assign]
        panel._format_bytes = lambda size: "0 B"  # type: ignore[method-assign]

        entries = panel._build_entries("llm.llama_cli")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].model_id, "unsloth/Qwen3-0.6B-GGUF")
        self.assertTrue(entries[0].can_download)
        self.assertFalse(entries[0].can_remove)

    def test_build_entries_hides_remove_for_noninstalled_local_file_row(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "transcription.whisperadvanced"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = True
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={},
                        capabilities={
                            "models": {
                                "storage": "local",
                                "local_files": {"root_setting": "models_dir", "default_root": "models/whisper", "glob": "*.bin"},
                                "managed_actions": {"remove": "remove_model"},
                            }
                        },
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_path": "models/whisper/missing.bin",
                        "file": "missing.bin",
                        "product_name": "Missing local file",
                        "installed": False,
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {"remove": "remove_model"}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._status_for = lambda enabled, installed: ("Needs setup", "#fff", "#000")  # type: ignore[method-assign]
        panel._file_installed = lambda _pid, _settings, _file: False  # type: ignore[method-assign]
        panel._file_size = lambda _pid, _settings, _file: 0  # type: ignore[method-assign]
        panel._format_bytes = lambda size: "0 B"  # type: ignore[method-assign]

        entries = panel._build_entries("transcription.whisperadvanced")

        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].can_remove)

    def test_capabilities_can_hide_available_selector_and_custom_inputs(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._models_caps = lambda _pid: {  # type: ignore[method-assign]
            "show_available_selector": False,
            "allow_custom_inputs": False,
        }

        self.assertFalse(panel._show_available_selector("transcription.whisperadvanced"))
        self.assertFalse(panel._allow_custom_inputs("transcription.whisperadvanced"))

    def test_build_entries_ignores_recommended_marker_for_cloud_cards(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.openrouter"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = False
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={
                            "m1": {
                                "model_name": "Model 1",
                                "description": "Recommended model",
                                "catalog_source": "recommended",
                            }
                        },
                        capabilities={"models": {"storage": "online", "managed_actions": {"list": "list_models"}}},
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "m1",
                        "product_name": "Model 1",
                        "favorite": True,
                        "availability_status": "ready",
                        "status": "ready",
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._cloud_status_for = lambda meta: ("Ready", "#fff", "#000")  # type: ignore[method-assign]
        panel._cloud_primary_action_for_entry = lambda **_kwargs: ("", "", {}, "")  # type: ignore[method-assign]
        panel._format_timestamp = lambda value: ""  # type: ignore[method-assign]

        entries = panel._build_entries("llm.openrouter")

        self.assertEqual(len(entries), 1)
        self.assertTrue(bool(entries[0].enabled))
        self.assertFalse(bool(entries[0].can_toggle))
        self.assertEqual(entries[0].toggle_label, "")
        self.assertNotIn("Favorite", entries[0].meta_lines)
        self.assertNotIn("Recommended by team", entries[0].meta_lines)

    def test_build_entries_keeps_observed_success_without_recommended_marker_for_cloud_cards(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.openrouter"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = False
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={
                            "m1": {
                                "model_name": "Model 1",
                                "description": "Recommended model",
                                "catalog_source": "recommended",
                            }
                        },
                        capabilities={"models": {"storage": "online", "managed_actions": {"list": "list_models"}}},
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "m1",
                        "product_name": "Model 1",
                        "favorite": True,
                        "recommended": True,
                        "observed_success": True,
                        "availability_status": "ready",
                        "status": "ready",
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._cloud_status_for = lambda meta: ("Ready", "#fff", "#000")  # type: ignore[method-assign]
        panel._cloud_primary_action_for_entry = lambda **_kwargs: ("", "", {}, "")  # type: ignore[method-assign]
        panel._format_timestamp = lambda value: ""  # type: ignore[method-assign]

        entries = panel._build_entries("llm.openrouter")

        self.assertEqual(len(entries), 1)
        self.assertTrue(bool(entries[0].observed_success))
        self.assertNotIn("Recommended by team", entries[0].meta_lines)
        self.assertNotIn("Observed successful run", entries[0].meta_lines)

    def test_build_entries_shows_runtime_policy_metadata_for_cloud_cards(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.openrouter"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = True
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={"m1": {"model_name": "Model 1", "description": "Cloud model"}},
                        capabilities={"models": {"storage": "online", "managed_actions": {"list": "list_models"}}},
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "m1",
                        "product_name": "Model 1",
                        "favorite": True,
                        "availability_status": "limited",
                        "failure_code": "rate_limited",
                        "status": "rate_limited",
                        "cooldown_until": 2000000000,
                    }
                ]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._cloud_status_for = lambda meta: ("Limited", "#fff", "#000")  # type: ignore[method-assign]
        panel._cloud_primary_action_for_entry = lambda **_kwargs: ("", "", {}, "")  # type: ignore[method-assign]
        panel._format_timestamp = lambda value: "2033-05-18" if int(value or 0) else ""  # type: ignore[method-assign]
        panel._provider_status_label = lambda value: "Limited" if value == "rate_limited" else str(value)  # type: ignore[method-assign]

        entries = panel._build_entries("llm.openrouter")

        self.assertEqual(len(entries), 1)
        self.assertIn("Retry after: 2033-05-18", entries[0].meta_lines)
        self.assertIn("Reason: Limited", entries[0].meta_lines)

    def test_add_custom_model_accepts_url_only_and_derives_model_id_from_filename(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cli"
        panel._labels = {}
        panel._custom_model = Mock()
        panel._custom_model.text.return_value = ""
        panel._custom_url = Mock()
        panel._custom_url.text.return_value = "https://example.com/models/gemma-3-1b-reasoning.Q8_0.gguf"
        panel._note = SimpleNamespace(setText=lambda _value: None, setVisible=lambda _value: None)
        panel._supports_custom_download_url = lambda _pid: True  # type: ignore[method-assign]
        captured: list[tuple[tuple, dict]] = []
        panel._upsert_model_in_settings_with_meta = lambda *args, **kwargs: captured.append((args, kwargs))  # type: ignore[method-assign]
        panel.set_plugin = lambda _pid: None  # type: ignore[method-assign]

        panel._add_custom_model()

        self.assertEqual(len(captured), 1)
        args, kwargs = captured[0]
        self.assertEqual(args[:2], ("llm.llama_cli", "gemma-3-1b-reasoning.Q8_0.gguf"))
        self.assertEqual(kwargs["label"], "gemma-3-1b-reasoning.Q8_0")
        self.assertEqual(kwargs["file_name"], "gemma-3-1b-reasoning.Q8_0.gguf")
        self.assertEqual(kwargs["download_url"], "https://example.com/models/gemma-3-1b-reasoning.Q8_0.gguf")

    def test_add_custom_model_uses_display_name_when_url_is_present(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cli"
        panel._labels = {}
        panel._custom_model = Mock()
        panel._custom_model.text.return_value = "Gemma 3 1B Reasoning"
        panel._custom_url = Mock()
        panel._custom_url.text.return_value = "https://example.com/models/gemma-3-1b-reasoning.Q8_0.gguf"
        panel._note = SimpleNamespace(setText=lambda _value: None, setVisible=lambda _value: None)
        panel._supports_custom_download_url = lambda _pid: True  # type: ignore[method-assign]
        captured: list[tuple[tuple, dict]] = []
        panel._upsert_model_in_settings_with_meta = lambda *args, **kwargs: captured.append((args, kwargs))  # type: ignore[method-assign]
        panel.set_plugin = lambda _pid: None  # type: ignore[method-assign]

        panel._add_custom_model()

        self.assertEqual(len(captured), 1)
        args, kwargs = captured[0]
        self.assertEqual(args[:2], ("llm.llama_cli", "gemma-3-1b-reasoning.Q8_0.gguf"))
        self.assertEqual(kwargs["label"], "Gemma 3 1B Reasoning")

    def test_resolve_custom_model_payload_normalizes_hf_repo_url(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._labels = {}
        panel._note = SimpleNamespace(setText=lambda _value: None, setVisible=lambda _value: None)

        payload = panel._resolve_custom_model_payload("https://huggingface.co/unsloth/Qwen3.5-4B-GGUF", "")

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["model_id"], "unsloth/Qwen3.5-4B-GGUF")
        self.assertEqual(payload["source_url"], "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF")

    def test_job_state_is_shared_across_panel_instances(self) -> None:
        first = ModelCardsPanel.__new__(ModelCardsPanel)
        first._job_states = _MODEL_JOB_STATES
        second = ModelCardsPanel.__new__(ModelCardsPanel)
        second._job_states = _MODEL_JOB_STATES

        first._job_states["job-1"] = {
            "plugin_id": "llm.llama_cli",
            "job_id": "job-1",
            "model_id": "Qwen/Qwen3-4B-GGUF",
            "status": "running",
            "progress": 42,
            "message": "running",
        }

        state = second._job_state_for("llm.llama_cli", "Qwen/Qwen3-4B-GGUF")

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["job_id"], "job-1")
        self.assertEqual(state["progress"], 42)

    def test_primary_connection_check_uses_unified_availability_messages(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.openrouter"
        panel._labels = {
            "models.note.testing_started": "Checking availability: {value}",
            "models.note.testing_success_provider": "Provider is ready: {value}",
        }
        panel._settings = SimpleNamespace(get_settings=lambda _pid, include_secrets=False: {"models": []})
        panel._note_text = ""
        panel._note_visible = False
        panel._note = SimpleNamespace(
            setText=lambda value: setattr(panel, "_note_text", value),
            setVisible=lambda value: setattr(panel, "_note_visible", bool(value)),
        )
        panel._cloud_primary_action_for_entry = lambda **_kwargs: ("Check availability", "test_connection", {}, "")  # type: ignore[method-assign]
        panel._render_current_plugin = lambda **_kwargs: None  # type: ignore[method-assign]
        captured: list[tuple[str, dict]] = []
        panel._run_action = lambda action_id, payload: captured.append((action_id, dict(payload)))  # type: ignore[method-assign]
        panel._action_thread = None
        panel._pending_model_actions = {}
        panel._focus_model_after_render = ("", "")

        panel._run_primary_model_action("google/gemini-2.0-flash-exp:free")

        self.assertEqual(captured, [("test_connection", {})])
        self.assertEqual(panel._note_text, "Checking availability: google/gemini-2.0-flash-exp:free")
        self.assertTrue(panel._note_visible)

    def test_build_entries_marks_cloud_model_needs_setup_when_required_key_is_missing(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.openrouter"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = False
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={"m1": {"model_name": "Model 1"}},
                        capabilities={
                            "health": {"required_settings": [{"keys": ["api_key"]}]},
                            "models": {"storage": "online", "managed_actions": {"list": "list_models"}},
                        },
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(get_settings=lambda _pid, include_secrets=False: {"models": [{"model_id": "m1"}]})
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {"list": "list_models"}  # type: ignore[method-assign]
        panel._has_action = lambda _pid, action: action in {"test_connection", "test_model", "list_models"}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._format_timestamp = lambda value: ""  # type: ignore[method-assign]

        entries = panel._build_entries("llm.openrouter")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].status_label, "Needs setup")
        self.assertEqual(entries[0].primary_action_label, "Check availability")

    def test_build_entries_marks_catalog_only_unknown_model_ready(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "text_processing.minutes_heuristic_v2"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = False
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={"intfloat/multilingual-e5-base": {"model_name": "E5 Base"}},
                        capabilities={"models": {"storage": "online"}},
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [{"model_id": "intfloat/multilingual-e5-base", "availability_status": "unknown"}]
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {}  # type: ignore[method-assign]
        panel._has_action = lambda _pid, _action: False  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: False  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._format_timestamp = lambda value: ""  # type: ignore[method-assign]

        entries = panel._build_entries("text_processing.minutes_heuristic_v2")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].status_label, "Ready")
        self.assertEqual(entries[0].primary_action_label, "")

    def test_toggle_model_uses_update_model_enabled_fallback(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.remote"
        panel._settings = SimpleNamespace(get_settings=lambda _pid, include_secrets=False: {})
        calls: list[tuple[str, str, bool]] = []
        panel._models = SimpleNamespace(
            update_model_enabled=lambda pid, mid, enabled: calls.append((pid, mid, enabled)),
        )
        panel.set_plugin = lambda _pid: None  # type: ignore[method-assign]

        panel._toggle_model("m1", True)

        self.assertEqual(calls, [("llm.remote", "m1", True)])

    def test_persist_single_model_probe_result_writes_normalized_availability_status(self) -> None:
        stored: dict[str, object] = {
            "models": [{"model_id": "m1", "product_name": "Model 1", "favorite": True}],
        }

        def get_settings(_pid: str, include_secrets: bool = False) -> dict[str, object]:
            return dict(stored)

        def set_settings(
            _pid: str,
            payload: dict[str, object],
            *,
            secret_fields: list[str],
            preserve_secrets: list[str],
        ) -> None:
            _ = secret_fields, preserve_secrets
            stored.clear()
            stored.update(payload)

        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._settings = SimpleNamespace(get_settings=get_settings, set_settings=set_settings)
        panel._emit_models_changed = lambda _pid: None  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: False  # type: ignore[method-assign]

        result = SimpleNamespace(status="error", message="status=429 rate limit", data={"model_id": "m1"})

        changed = panel._persist_single_model_probe_result(
            plugin_id="llm.remote",
            action_id="test_model",
            result=result,
        )

        self.assertTrue(changed)
        rows = stored["models"]
        assert isinstance(rows, list)
        self.assertEqual(rows[0]["failure_code"], "rate_limited")
        self.assertEqual(rows[0]["availability_status"], "limited")
        self.assertEqual(rows[0]["selectable"], False)

    def test_cloud_failure_code_from_probe_message_handles_timeout_and_transport_errors(self) -> None:
        self.assertEqual(
            _cloud_failure_code_from_probe_message("request timeout after 20s"),
            "timeout",
        )
        self.assertEqual(
            _cloud_failure_code_from_probe_message("SSL: UNEXPECTED_EOF_WHILE_READING"),
            "transport_error",
        )

    def test_build_entries_keeps_installed_local_model_visible_even_if_hidden(self) -> None:
        panel = ModelCardsPanel.__new__(ModelCardsPanel)
        panel._plugin_id = "llm.llama_cli"
        panel._app_root = Path(".")
        panel._labels = {}
        panel._advanced_mode = True
        panel._catalog_service = SimpleNamespace(
            load=lambda: SimpleNamespace(
                catalog=SimpleNamespace(
                    plugin_by_id=lambda _pid: SimpleNamespace(
                        model_info={
                            "Qwen/Qwen3-4B-GGUF": {
                                "model_name": "Qwen3 4B (GGUF)",
                                "file": "Qwen3-4B-Q4_K_M.gguf",
                            }
                        },
                        capabilities={
                            "models": {
                                "storage": "local",
                                "local_files": {
                                    "default_root": "models/llama",
                                    "glob": "*.gguf",
                                }
                            }
                        },
                    )
                )
            )
        )
        panel._settings = SimpleNamespace(
            get_settings=lambda _pid, include_secrets=False: {
                "models": [
                    {
                        "model_id": "Qwen/Qwen3-4B-GGUF",
                        "product_name": "Qwen3 4B (GGUF)",
                        "file": "Qwen3-4B-Q4_K_M.gguf",
                        "hidden": True,
                        "installed": True,
                        "status": "installed",
                    }
                ],
                "hidden_model_ids": ["Qwen/Qwen3-4B-GGUF"],
                "hidden_model_files": ["Qwen3-4B-Q4_K_M.gguf"],
            }
        )
        panel._models = SimpleNamespace(load_models_config=lambda _pid: [])
        panel._managed_actions_for = lambda _pid: {}  # type: ignore[method-assign]
        panel._is_local_models_plugin = lambda _pid: True  # type: ignore[method-assign]
        panel._is_local_model_available = lambda _pid, _settings, _entry: True  # type: ignore[method-assign]
        panel._job_state_for = lambda _pid, _mid: None  # type: ignore[method-assign]
        panel._pending_model_actions = {}
        panel._uses_starter_add_flow = lambda _pid: False  # type: ignore[method-assign]
        panel._cloud_status_for = lambda meta: ("Ready", "#fff", "#000")  # type: ignore[method-assign]
        panel._cloud_primary_action_for_entry = lambda **_kwargs: ("", "", {}, "")  # type: ignore[method-assign]
        panel._format_timestamp = lambda value: ""  # type: ignore[method-assign]
        panel._provider_status_label = lambda value: str(value)  # type: ignore[method-assign]

        entries = panel._build_entries("llm.llama_cli")

        titles = [entry.title for entry in entries]
        self.assertIn("Qwen3 4B (GGUF)", titles)


if __name__ == "__main__":
    unittest.main()
