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

from aimn.ui.controllers.meeting_history_controller import MeetingHistoryController  # noqa: E402
from aimn.ui.controllers.meeting_history_refresh_controller import (  # noqa: E402
    MeetingHistoryRefreshController,
)


class TestMeetingHistoryRefreshController(unittest.TestCase):
    def test_build_payload_filters_visible_meetings_for_global_search(self) -> None:
        meetings = [
            SimpleNamespace(base_name="base-a", meeting_id="m-a", source_path="a.wav"),
            SimpleNamespace(base_name="base-b", meeting_id="m-b", source_path="b.wav"),
        ]

        payload = MeetingHistoryRefreshController.build_payload(
            meetings=meetings,
            output_dir=repo_root,
            meta_cache_snapshot={},
            global_query="launch",
            global_meeting_ids={"m-b"},
            select_base_name="",
            current_selection="",
        )

        self.assertEqual([item.base_name for item in payload.visible_meetings], ["base-b"])
        self.assertEqual(payload.fallback_first_base, "base-b")

    def test_apply_payload_prunes_cache_and_prefers_pending_files(self) -> None:
        history = MeetingHistoryController()
        payload = {
            "meetings": [SimpleNamespace(base_name="keep", meeting_id="m-1", source_path="fresh.wav")],
            "visible_meetings": [SimpleNamespace(base_name="keep", meeting_id="m-1", source_path="fresh.wav")],
            "known_bases": {"keep"},
            "pending_files": ["fresh.wav"],
            "desired_base": "keep",
            "fallback_first_base": "",
            "meta_cache": {},
        }

        applied = MeetingHistoryRefreshController.apply_payload(
            payload,
            meeting_history=history,
            meeting_payload_cache={"keep": {"ok": True}, "drop": {"stale": True}},
            ad_hoc_input_files=["adhoc.wav"],
        )

        self.assertEqual([getattr(item, "base_name", "") for item in applied.all_meetings], ["keep"])
        self.assertEqual(applied.meeting_payload_cache, {"keep": {"ok": True}})
        self.assertEqual(applied.input_files, ["fresh.wav"])
        self.assertEqual(applied.select_base_name, "keep")


if __name__ == "__main__":
    unittest.main()
