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

from aimn.ui.controllers.meeting_selection_controller import MeetingSelectionController


class TestMeetingSelectionController(unittest.TestCase):
    def test_load_selection_payload_propagates_load_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "boom"):
            MeetingSelectionController.load_selection_payload(
                base_name="meeting-1",
                load_meeting=lambda _base: (_ for _ in ()).throw(RuntimeError("boom")),
                list_artifacts=lambda _meeting, _internal: [],
                all_meetings=[],
                stage_order=["media_convert", "transcription"],
            )

    def test_load_selection_payload_builds_artifacts_and_search_context(self) -> None:
        meeting = SimpleNamespace(
            meeting_id="mid-1",
            audio_relpath="audio.wav",
            pinned_aliases={"llm_processing": "v2"},
            active_aliases={"transcription": "latest"},
            nodes={
                "a1": SimpleNamespace(stage_id="transcription"),
                "a2": SimpleNamespace(stage_id="llm_processing"),
            },
        )
        artifacts = [
            SimpleNamespace(kind="transcript", user_visible=True, alias="a1", stage_id="transcription", relpath="t.txt"),
            SimpleNamespace(kind="segments", user_visible=False, alias="a1", stage_id="transcription", relpath="s.json"),
            SimpleNamespace(kind="summary", user_visible=True, alias="a2", stage_id="llm_processing", relpath="sum.md"),
            SimpleNamespace(kind="internal", user_visible=True, alias="", stage_id="", relpath="i.bin"),
        ]
        all_meetings = [
            SimpleNamespace(meeting_id="mid-1", base_name="base-1"),
            SimpleNamespace(meeting_id="mid-2", base_name="base-2"),
            SimpleNamespace(meeting_id="", base_name="skip"),
        ]
        payload = MeetingSelectionController.load_selection_payload(
            base_name="base-1",
            load_meeting=lambda _base: meeting,
            list_artifacts=lambda _meeting, _internal: artifacts,
            load_management_suggestions=lambda meeting_id: [{"id": "s1", "source_meeting_id": meeting_id}],
            all_meetings=all_meetings,
            stage_order=["media_convert", "transcription", "llm_processing"],
        )

        self.assertIs(payload.get("meeting"), meeting)
        active = payload.get("active_artifacts", [])
        self.assertEqual([item.kind for item in active], ["transcript", "summary"])
        self.assertEqual(payload.get("preferred_kind"), "transcript")
        self.assertEqual(payload.get("management_suggestions"), [{"id": "s1", "source_meeting_id": "mid-1"}])
        segments = payload.get("segments_relpaths", {})
        self.assertEqual(segments.get("a1"), "s.json")
        self.assertEqual(segments.get("transcription:a1"), "s.json")
        search = payload.get("search_context", {})
        self.assertEqual(search.get("current_meeting_id"), "mid-1")
        self.assertEqual(search.get("meetings"), [("mid-1", "base-1"), ("mid-2", "base-2")])
        self.assertEqual(search.get("stages"), ["llm_processing", "transcription"])
        self.assertEqual(search.get("aliases"), ["a1", "a2"])
        self.assertEqual(search.get("kinds"), ["summary", "transcript"])


if __name__ == "__main__":
    unittest.main()
