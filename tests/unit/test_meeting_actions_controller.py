import sys
import tempfile
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

from aimn.ui.controllers.meeting_actions_controller import MeetingActionsController


class _CatalogStub:
    def __init__(self, plugins: list[object]) -> None:
        self._plugins = plugins

    def enabled_plugins(self) -> list[object]:
        return list(self._plugins)


class _CatalogServiceStub:
    def __init__(self, plugins: list[object]) -> None:
        self._catalog = _CatalogStub(plugins)

    def load(self) -> object:
        return SimpleNamespace(catalog=self._catalog)


class _ActionServiceStub:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[tuple[str, str, dict]] = []

    def invoke_action(self, plugin_id: str, action_id: str, payload: dict) -> object:
        self.calls.append((plugin_id, action_id, dict(payload)))
        return self._result


class _SettingsStoreStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def get_settings(self, _settings_id: str, *, include_secrets: bool = False) -> dict:
        _ = include_secrets
        return dict(self._payload)


class _MeetingServiceStub:
    def __init__(self, meeting: object | None) -> None:
        self._meeting = meeting

    def load_by_base_name(self, _base_name: str) -> object | None:
        return self._meeting


class _ArtifactServiceStub:
    def __init__(self, artifacts: list[object]) -> None:
        self._artifacts = artifacts

    def list_artifacts(self, _meeting: object, *, include_internal: bool = False) -> list[object]:
        _ = include_internal
        return list(self._artifacts)


class TestMeetingActionsController(unittest.TestCase):
    def _make_controller(
        self,
        *,
        output_dir: Path,
        plugins: list[object] | None = None,
        action_result: object | None = None,
        settings_payload: dict | None = None,
        meeting: object | None = None,
        artifacts: list[object] | None = None,
    ) -> MeetingActionsController:
        return MeetingActionsController(
            paths=SimpleNamespace(output_dir=output_dir),
            meeting_service=_MeetingServiceStub(meeting),
            artifact_service=_ArtifactServiceStub(artifacts or []),
            settings_store=_SettingsStoreStub(settings_payload or {}),
            catalog_service=_CatalogServiceStub(plugins or []),
            action_service=_ActionServiceStub(action_result or SimpleNamespace(status="error", data={})),
            rename_settings_id="ui.meeting_rename",
            rename_modes={"metadata_only", "artifacts_and_manifest", "full_with_source"},
        )

    def test_default_rerun_stage_uses_first_enabled_stage(self) -> None:
        result = MeetingActionsController.default_rerun_stage(
            ["media_convert", "transcription", "llm_processing"],
            lambda stage_id: stage_id in {"media_convert"},
        )
        self.assertEqual(result, "transcription")

    def test_meeting_topic_suggestions_provider_discovers_capability_action(self) -> None:
        plugin = SimpleNamespace(
            plugin_id="service.prompt",
            capabilities={"meeting_rename": {"topic_suggestions": {"action": "topics"}}},
        )
        controller = self._make_controller(output_dir=Path("."), plugins=[plugin])

        plugin_id, action_id = controller.meeting_topic_suggestions_provider()

        self.assertEqual(plugin_id, "service.prompt")
        self.assertEqual(action_id, "topics")

    def test_meeting_topic_suggestions_normalizes_and_deduplicates(self) -> None:
        plugin = SimpleNamespace(
            plugin_id="service.prompt",
            capabilities={"meeting_rename": {"topic_suggestions": {"action": "topics"}}},
        )
        result = SimpleNamespace(
            status="ok",
            data={"suggestions": [" Release Plan ", "release   plan", {"title": "Q2 Budget"}]},
        )
        action_service = _ActionServiceStub(result)
        controller = MeetingActionsController(
            paths=SimpleNamespace(output_dir=Path(".")),
            meeting_service=_MeetingServiceStub(None),
            artifact_service=_ArtifactServiceStub([]),
            settings_store=_SettingsStoreStub({}),
            catalog_service=_CatalogServiceStub([plugin]),
            action_service=action_service,
            rename_settings_id="ui.meeting_rename",
            rename_modes={"metadata_only", "artifacts_and_manifest", "full_with_source"},
        )

        suggestions = controller.meeting_topic_suggestions("meeting-1", meeting=SimpleNamespace(meeting_id="m1"))

        self.assertEqual(suggestions, ["Release Plan", "Q2 Budget"])
        self.assertEqual(len(action_service.calls), 1)
        _, _, payload = action_service.calls[0]
        self.assertEqual(payload.get("base_name"), "meeting-1")
        self.assertEqual(payload.get("meeting_id"), "m1")

    def test_meeting_rename_policy_falls_back_to_safe_default(self) -> None:
        controller = self._make_controller(
            output_dir=Path("."),
            settings_payload={"rename_mode": "unknown", "allow_source_rename": True},
        )

        mode, allow_source = controller.meeting_rename_policy()

        self.assertEqual(mode, "artifacts_and_manifest")
        self.assertTrue(allow_source)

    def test_delete_meeting_files_removes_artifacts_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "m1__MEETING.json").write_text("{}", encoding="utf-8")
            (output_dir / "m1__summary.txt").write_text("summary", encoding="utf-8")
            (output_dir / "m1__transcript.txt").write_text("transcript", encoding="utf-8")
            meeting = SimpleNamespace(base_name="m1")
            artifacts = [
                SimpleNamespace(relpath="m1__summary.txt"),
                SimpleNamespace(relpath="m1__transcript.txt"),
            ]
            controller = self._make_controller(
                output_dir=output_dir,
                meeting=meeting,
                artifacts=artifacts,
            )

            controller.delete_meeting_files("m1")

            self.assertFalse((output_dir / "m1__MEETING.json").exists())
            self.assertFalse((output_dir / "m1__summary.txt").exists())
            self.assertFalse((output_dir / "m1__transcript.txt").exists())


if __name__ == "__main__":
    unittest.main()
