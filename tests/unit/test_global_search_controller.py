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

from aimn.ui.controllers.global_search_controller import GlobalSearchController  # noqa: E402


class _FakeTextPanel:
    def __init__(self) -> None:
        self.modes = []
        self.status = ""
        self.results = []
        self.answer = ""
        self.highlight = ""
        self.selected_version = ()
        self.jump_target = ()

    def set_search_modes(self, modes):
        self.modes = list(modes)

    def set_global_search_status(self, value: str):
        self.status = str(value or "")

    def set_global_search_results(self, query: str, hits: list, answer: str = ""):
        self.results = list(hits)
        self.answer = str(answer or "")

    def clear_global_search_results(self):
        self.results = []

    def select_artifact_kind(self, _kind: str):
        return

    def select_version_alias(self, _alias: str):
        return

    def select_version(self, *, stage_id: str = "", alias: str = "", kind: str = ""):
        self.selected_version = (str(stage_id), str(alias), str(kind))

    def jump_to_transcript_segment(
        self,
        *,
        segment_index: int,
        start_ms: int,
        stage_id: str = "",
        alias: str = "",
        kind: str = "",
    ):
        self.jump_target = (int(segment_index), int(start_ms))
        return

    def highlight_query(self, query: str):
        self.highlight = str(query or "")


class _FakeHistoryPanel:
    def __init__(self) -> None:
        self.meetings = []
        self.selected = ""

    def set_meetings(self, meetings):
        self.meetings = list(meetings)

    def select_by_base_name(self, base_name: str):
        self.selected = str(base_name or "")


class _FakeActionService:
    def __init__(self) -> None:
        self.last_payload: dict = {}

    def invoke_action(self, _plugin_id: str, _action_id: str, payload: dict):
        self.last_payload = dict(payload or {})
        query = str(payload.get("query", "") or "")
        if not query:
            return SimpleNamespace(status="error", message="bad_query", data={})
        return SimpleNamespace(
            status="ok",
            message="",
            data={
                "hits": [
                    {"meeting_id": "m1", "kind": "summary"},
                    {"meeting_id": "m2", "kind": "transcript"},
                ],
                "answer": "synthetic answer",
            },
        )


class _FakeCatalogService:
    def __init__(self) -> None:
        self._stamp = "s1"
        self._plugins = [
            SimpleNamespace(
                plugin_id="service.search_semantic",
                capabilities={"global_search": {"mode": "semantic"}},
            ),
        ]

    def load(self):
        catalog = SimpleNamespace(enabled_plugins=lambda: list(self._plugins))
        return SimpleNamespace(stamp=self._stamp, catalog=catalog)

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        return str(plugin_id or "") in {"service.search_semantic"}


class TestGlobalSearchController(unittest.TestCase):
    def setUp(self) -> None:
        self.text_panel = _FakeTextPanel()
        self.history_panel = _FakeHistoryPanel()
        self.action_service = _FakeActionService()
        self.meetings = [
            SimpleNamespace(meeting_id="m1", base_name="meeting-one"),
            SimpleNamespace(meeting_id="m2", base_name="meeting-two"),
        ]
        self.refresh_calls: list[str] = []
        self.controller = GlobalSearchController(
            catalog_service=_FakeCatalogService(),
            action_service=self.action_service,
            text_panel=self.text_panel,
            history_panel=self.history_panel,
            all_meetings_provider=lambda: list(self.meetings),
            refresh_history=lambda base: self.refresh_calls.append(str(base or "")),
            active_meeting_base_name_provider=lambda: "meeting-one",
        )

    def test_refresh_global_search_ui_enables_modes(self) -> None:
        self.controller.refresh_global_search_ui()
        self.assertIn("local", self.text_panel.modes)
        self.assertIn("global", self.text_panel.modes)

    def test_on_global_search_requested_filters_history(self) -> None:
        self.controller.on_global_search_requested("roadmap", "global")
        self.assertEqual(self.text_panel.status, "1 matches")
        self.assertEqual(len(self.text_panel.results), 1)
        self.assertEqual(len(self.history_panel.meetings), 1)
        self.assertEqual(self.history_panel.selected, "meeting-two")
        self.assertEqual(self.controller.query, "roadmap")
        self.assertEqual(self.controller.meeting_ids, {"m2"})

    def test_clear_global_search_restores_history(self) -> None:
        self.controller.on_global_search_requested("roadmap", "global")
        self.controller.clear_global_search()
        self.assertEqual(self.text_panel.status, "")
        self.assertEqual(self.text_panel.results, [])
        self.assertTrue(self.refresh_calls)

    def test_global_search_forces_transcript_scope(self) -> None:
        self.controller.on_global_search_requested("roadmap", "global")
        self.assertEqual(self.action_service.last_payload.get("kind"), "transcript")
        self.assertNotIn("meeting_id", self.action_service.last_payload)
        self.assertNotIn("alias", self.action_service.last_payload)

    def test_on_global_search_open_uses_stage_aware_version_selection(self) -> None:
        self.controller.on_global_search_requested("roadmap", "global")
        self.controller.on_global_search_open("m1", "transcription", "a1", "transcript", 7, 1234)
        self.assertEqual(self.text_panel.selected_version, ("transcription", "a1", "transcript"))
        self.assertEqual(self.text_panel.jump_target, (7, 1234))

    def test_global_search_falls_back_to_builtin_when_semantic_hits_are_not_usable(self) -> None:
        self.controller._action_service = SimpleNamespace(  # type: ignore[attr-defined]
            invoke_action=lambda _plugin_id, _action_id, _payload: SimpleNamespace(
                status="ok",
                message="",
                data={
                    "hits": [
                        {"meeting_id": "missing", "kind": "transcript"},
                        {"meeting_id": "m1", "kind": "summary"},
                    ],
                    "answer": "semantic answer",
                },
            )
        )
        self.controller._builtin_search = SimpleNamespace(  # type: ignore[attr-defined]
            search_transcripts=lambda query, limit=80: [
                SimpleNamespace(
                    meeting_id="m1",
                    alias="a1",
                    stage_id="transcription",
                    kind="transcript",
                    relpath="m1.txt",
                    snippet="[roadmap] item",
                    score=1.0,
                    segment_index=2,
                    start_ms=1200,
                    end_ms=2200,
                    content="roadmap item",
                    context="roadmap item context",
                )
            ]
        )

        self.controller.on_global_search_requested("roadmap", "global")

        self.assertEqual(self.text_panel.status, "1 matches")
        self.assertEqual(len(self.text_panel.results), 1)
        self.assertEqual(self.text_panel.results[0]["meeting_id"], "m1")


if __name__ == "__main__":
    unittest.main()
