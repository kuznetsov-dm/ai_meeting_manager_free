import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.controllers.meeting_inspection_controller import MeetingInspectionController  # noqa: E402


class TestMeetingInspectionController(unittest.TestCase):
    def test_should_render_selection_requires_base_stage_and_alias(self) -> None:
        self.assertFalse(
            MeetingInspectionController.should_render_selection(
                active_meeting_base_name="",
                stage_id="llm_processing",
                alias="A1",
            )
        )
        self.assertFalse(
            MeetingInspectionController.should_render_selection(
                active_meeting_base_name="m-base",
                stage_id="",
                alias="A1",
            )
        )
        self.assertTrue(
            MeetingInspectionController.should_render_selection(
                active_meeting_base_name="m-base",
                stage_id="llm_processing",
                alias="A1",
            )
        )

    def test_resolve_inspection_meeting_falls_back_to_loader(self) -> None:
        loaded = object()
        result = MeetingInspectionController.resolve_inspection_meeting(
            active_meeting_base_name="m-base",
            active_meeting_manifest=None,
            load_meeting=lambda _base: loaded,
        )
        self.assertIs(result, loaded)

    def test_resolve_inspection_meeting_returns_none_on_load_error(self) -> None:
        result = MeetingInspectionController.resolve_inspection_meeting(
            active_meeting_base_name="m-base",
            active_meeting_manifest=None,
            load_meeting=lambda _base: (_ for _ in ()).throw(FileNotFoundError("gone")),
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
