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

from aimn.ui.controllers.meeting_version_controller import MeetingVersionController


class _ArtifactServiceStub:
    def __init__(self, meeting: object) -> None:
        self.meeting = meeting
        self.saved: list[object] = []

    def load_meeting(self, _base_name: str) -> object:
        return self.meeting

    def save_meeting(self, meeting: object) -> None:
        self.saved.append(meeting)


class _MeetingServiceStub:
    def __init__(self) -> None:
        self.touched: list[object] = []

    def touch_updated(self, meeting: object) -> None:
        self.touched.append(meeting)


class TestMeetingVersionController(unittest.TestCase):
    def test_pin_alias_updates_manifest_and_persists(self) -> None:
        meeting = SimpleNamespace(pinned_aliases={})
        artifact_service = _ArtifactServiceStub(meeting)
        meeting_service = _MeetingServiceStub()
        controller = MeetingVersionController(
            artifact_service=artifact_service,
            meeting_service=meeting_service,
        )

        result = controller.pin_alias(base_name="meeting-1", stage_id="llm_processing", alias="v2")

        self.assertIs(result, meeting)
        self.assertEqual(meeting.pinned_aliases.get("llm_processing"), "v2")
        self.assertEqual(len(meeting_service.touched), 1)
        self.assertEqual(len(artifact_service.saved), 1)

    def test_unpin_alias_removes_existing_pin(self) -> None:
        meeting = SimpleNamespace(pinned_aliases={"service": "latest"})
        artifact_service = _ArtifactServiceStub(meeting)
        meeting_service = _MeetingServiceStub()
        controller = MeetingVersionController(
            artifact_service=artifact_service,
            meeting_service=meeting_service,
        )

        result = controller.unpin_alias(base_name="meeting-1", stage_id="service")

        self.assertIs(result, meeting)
        self.assertNotIn("service", meeting.pinned_aliases)
        self.assertEqual(len(meeting_service.touched), 1)
        self.assertEqual(len(artifact_service.saved), 1)

    def test_set_active_alias_skips_when_alias_unchanged(self) -> None:
        meeting = SimpleNamespace(active_aliases={"transcription": "v1"})
        artifact_service = _ArtifactServiceStub(meeting)
        meeting_service = _MeetingServiceStub()
        controller = MeetingVersionController(
            artifact_service=artifact_service,
            meeting_service=meeting_service,
        )

        result = controller.set_active_alias(
            base_name="meeting-1",
            stage_id="transcription",
            alias="v1",
        )

        self.assertIsNone(result)
        self.assertEqual(len(meeting_service.touched), 0)
        self.assertEqual(len(artifact_service.saved), 0)

    def test_set_active_alias_updates_and_persists(self) -> None:
        meeting = SimpleNamespace(active_aliases={})
        artifact_service = _ArtifactServiceStub(meeting)
        meeting_service = _MeetingServiceStub()
        controller = MeetingVersionController(
            artifact_service=artifact_service,
            meeting_service=meeting_service,
        )

        result = controller.set_active_alias(
            base_name="meeting-1",
            stage_id="transcription",
            alias="v2",
        )

        self.assertIs(result, meeting)
        self.assertEqual(meeting.active_aliases.get("transcription"), "v2")
        self.assertEqual(len(meeting_service.touched), 0)
        self.assertEqual(len(artifact_service.saved), 1)


if __name__ == "__main__":
    unittest.main()
