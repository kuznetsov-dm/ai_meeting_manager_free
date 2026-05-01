import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.llm_prompt_context_controller import LlmPromptContextController


class _SettingsStoreStub:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = dict(payload or {})
        self.saved: dict | None = None

    def get_settings(self, _settings_id: str, *, include_secrets: bool = False) -> dict:
        _ = include_secrets
        return dict(self.payload)

    def set_settings(
        self,
        _settings_id: str,
        data: dict,
        *,
        secret_fields: list[str],
        preserve_secrets: list[str],
    ) -> None:
        _ = secret_fields
        _ = preserve_secrets
        self.saved = dict(data)
        self.payload = dict(data)


class TestLlmPromptContextController(unittest.TestCase):
    def test_llm_stage_will_run_when_stage_enabled(self) -> None:
        runtime = {
            "pipeline": {"disabled_stages": []},
            "stages": {"llm_processing": {"plugin_id": "llm.ollama"}},
        }

        result = LlmPromptContextController.llm_stage_will_run(
            runtime,
            force_run_from=None,
            stage_order=["media_convert", "transcription", "llm_processing", "service"],
        )

        self.assertTrue(result)

    def test_llm_stage_will_not_run_if_start_after_llm(self) -> None:
        runtime = {
            "pipeline": {"disabled_stages": []},
            "stages": {"llm_processing": {"plugin_id": "llm.ollama"}},
        }

        result = LlmPromptContextController.llm_stage_will_run(
            runtime,
            force_run_from="service",
            stage_order=["media_convert", "transcription", "llm_processing", "service"],
        )

        self.assertFalse(result)

    def test_meeting_id_for_prompt_context_prefers_active_manifest(self) -> None:
        result = LlmPromptContextController.meeting_id_for_prompt_context(
            active_meeting_manifest=SimpleNamespace(meeting_id="manifest-id"),
            active_meeting_base_name="ignored-base",
            load_meeting_by_base=lambda _base: SimpleNamespace(meeting_id="loaded-id"),
        )
        self.assertEqual(result, "manifest-id")

    def test_save_and_load_llm_agenda_selection(self) -> None:
        settings = _SettingsStoreStub()
        controller = LlmPromptContextController(
            paths=SimpleNamespace(output_dir=Path(".")),
            settings_store=settings,
            prompt_settings_id="ui.meetings_prompt",
        )

        controller.save_llm_agenda_selection(
            meeting_id="meeting-1",
            selection={"agenda_id": "a1", "agenda_title": "Agenda", "agenda_text": "Text"},
        )
        loaded = controller.load_llm_agenda_selection(meeting_id="meeting-1")

        self.assertEqual(loaded.get("agenda_id"), "a1")
        self.assertEqual(loaded.get("agenda_title"), "Agenda")
        self.assertEqual(loaded.get("agenda_text"), "Text")
        self.assertIsNotNone(settings.saved)

    def test_load_agenda_catalog_filters_and_sorts_store_rows(self) -> None:
        fake_rows = [
            {"id": "a-old", "title": "Old", "text": "x", "updated_at": "2025-01-01T00:00:00Z"},
            {"id": "", "title": "Skip", "text": "y", "updated_at": "2025-01-03T00:00:00Z"},
            {"id": "a-new", "title": "New", "text": "z", "updated_at": "2025-01-02T00:00:00Z"},
        ]

        class _StoreStub:
            def __init__(self, _app_root: Path) -> None:
                self.closed = False

            def list_agendas(self) -> list[dict]:
                return list(fake_rows)

            def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            controller = LlmPromptContextController(
                paths=SimpleNamespace(app_root=Path(tmp), output_dir=Path(tmp)),
                settings_store=_SettingsStoreStub(),
                prompt_settings_id="ui.meetings_prompt",
            )
            with patch("aimn.ui.controllers.llm_prompt_context_controller.ManagementStore", _StoreStub):
                items = controller.load_agenda_catalog()

            self.assertEqual([entry.get("id") for entry in items], ["a-new", "a-old"])

    def test_load_agenda_catalog_prefers_management_store(self) -> None:
        fake_rows = [
            {"id": "a-old", "title": "Old", "text": "x", "updated_at": "2025-01-01T00:00:00Z"},
            {"id": "a-new", "title": "New", "text": "y", "updated_at": "2025-01-02T00:00:00Z"},
        ]

        class _StoreStub:
            def __init__(self, _app_root: Path) -> None:
                self.closed = False

            def list_agendas(self) -> list[dict]:
                return list(fake_rows)

            def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            controller = LlmPromptContextController(
                paths=SimpleNamespace(app_root=Path(tmp), output_dir=output_dir),
                settings_store=_SettingsStoreStub(),
                prompt_settings_id="ui.meetings_prompt",
            )
            with patch("aimn.ui.controllers.llm_prompt_context_controller.ManagementStore", _StoreStub):
                items = controller.load_agenda_catalog()

            self.assertEqual([entry.get("id") for entry in items], ["a-new", "a-old"])

    def test_load_agenda_catalog_returns_empty_without_app_root(self) -> None:
        controller = LlmPromptContextController(
            paths=SimpleNamespace(output_dir=Path(".")),
            settings_store=_SettingsStoreStub(),
            prompt_settings_id="ui.meetings_prompt",
        )

        self.assertEqual(controller.load_agenda_catalog(), [])

    def test_load_project_catalog_reads_store_id_key(self) -> None:
        fake_rows = [
            {"id": "project-1", "name": "Apollo", "updated_at": "2025-01-02T00:00:00Z"},
            {"id": "project-2", "name": "Zeus", "updated_at": "2025-01-01T00:00:00Z"},
        ]

        class _StoreStub:
            def __init__(self, _app_root: Path) -> None:
                pass

            def list_projects(self) -> list[dict]:
                return list(fake_rows)

            def close(self) -> None:
                return

        with tempfile.TemporaryDirectory() as tmp:
            controller = LlmPromptContextController(
                paths=SimpleNamespace(app_root=Path(tmp), output_dir=Path(tmp)),
                settings_store=_SettingsStoreStub(),
                prompt_settings_id="ui.meetings_prompt",
            )
            with patch("aimn.ui.controllers.llm_prompt_context_controller.ManagementStore", _StoreStub):
                items = controller.load_project_catalog()

        self.assertEqual([entry.get("project_id") for entry in items], ["project-1", "project-2"])

    def test_load_project_catalog_returns_empty_when_store_has_no_rows(self) -> None:
        class _StoreStub:
            def __init__(self, _app_root: Path) -> None:
                pass

            def list_projects(self) -> list[dict]:
                return []

            def close(self) -> None:
                return

        with tempfile.TemporaryDirectory() as tmp:
            controller = LlmPromptContextController(
                paths=SimpleNamespace(app_root=Path(tmp), output_dir=Path(tmp)),
                settings_store=_SettingsStoreStub(),
                prompt_settings_id="ui.meetings_prompt",
            )
            with patch("aimn.ui.controllers.llm_prompt_context_controller.ManagementStore", _StoreStub):
                items = controller.load_project_catalog()

            self.assertEqual(items, [])

    def test_apply_llm_agenda_selection_sets_and_clears_params(self) -> None:
        runtime = {
            "stages": {
                "llm_processing": {
                    "params": {"prompt_agenda_id": "old", "prompt_project_ids": "p-old", "other": "keep"}
                }
            }
        }
        LlmPromptContextController.apply_llm_prompt_selection(
            runtime,
            {
                "agenda_id": "",
                "agenda_title": "Title",
                "agenda_text": "",
                "prompt_project_ids": "p1, p2",
            },
        )
        params = runtime["stages"]["llm_processing"]["params"]
        self.assertNotIn("prompt_agenda_id", params)
        self.assertEqual(params.get("prompt_agenda_title"), "Title")
        self.assertNotIn("prompt_agenda_text", params)
        self.assertEqual(params.get("prompt_project_ids"), "p1,p2")
        self.assertEqual(params.get("other"), "keep")

    def test_parse_project_ids_normalizes_and_deduplicates(self) -> None:
        parsed = LlmPromptContextController.parse_project_ids(" p1, p2, p1 ,, ")
        self.assertEqual(parsed, ["p1", "p2"])


if __name__ == "__main__":
    unittest.main()
