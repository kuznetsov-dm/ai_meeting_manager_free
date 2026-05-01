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

from aimn.ui.management_tab_v2 import ManagementTabV2  # noqa: E402


class TestManagementTabV2(unittest.TestCase):
    def test_filtered_suggestions_for_view_returns_all_without_meeting_focus(self) -> None:
        suggestions = [
            {"id": "s1", "source_meeting_id": "m1"},
            {"id": "s2", "source_meeting_id": "m2"},
        ]
        filtered = ManagementTabV2._filtered_suggestions_for_view(
            suggestions,
            focus_type="project",
            focus_id="p1",
        )
        self.assertEqual([row["id"] for row in filtered], ["s1", "s2"])

    def test_filtered_suggestions_for_view_limits_to_focused_meeting(self) -> None:
        suggestions = [
            {"id": "s1", "source_meeting_id": "m1"},
            {"id": "s2", "source_meeting_id": "m2"},
            {"id": "s3", "source_meeting_id": "m1"},
        ]
        filtered = ManagementTabV2._filtered_suggestions_for_view(
            suggestions,
            focus_type="meeting",
            focus_id="m1",
        )
        self.assertEqual([row["id"] for row in filtered], ["s1", "s3"])

    def test_obvious_merge_target_prefers_single_exact_normalized_match(self) -> None:
        target_id = ManagementTabV2._obvious_merge_target_id(
            "project",
            {"title": "Website refresh", "normalized_key": "website refresh"},
            {
                "p1": {"name": "Website refresh"},
                "p2": {"name": "Mobile app redesign"},
            },
        )
        self.assertEqual(target_id, "p1")

    def test_obvious_merge_target_rejects_ambiguous_exact_match(self) -> None:
        target_id = ManagementTabV2._obvious_merge_target_id(
            "task",
            {"title": "Send recap", "normalized_key": "send recap"},
            {
                "t1": {"title": "Send recap"},
                "t2": {"title": "send recap"},
            },
        )
        self.assertEqual(target_id, "")

    def test_obvious_merge_target_rejects_non_obvious_similarity(self) -> None:
        target_id = ManagementTabV2._obvious_merge_target_id(
            "agenda",
            {"title": "Budget review and risks", "normalized_key": "budget review and risks"},
            {
                "a1": {"title": "Budget review"},
                "a2": {"title": "Risk planning"},
            },
        )
        self.assertEqual(target_id, "")

    def test_entity_provenance_badges_show_mixed_and_merged(self) -> None:
        fake = SimpleNamespace(
            _rows={
                "task": {
                    "t1": {
                        "manual_mentions": 1,
                        "ai_mentions": 2,
                        "mention_count": 3,
                        "meetings": ["m1", "m2"],
                    }
                }
            },
            _tr=lambda _key, default: default,
        )
        item = SimpleNamespace(entity_type="task", entity_id="t1")
        badges = ManagementTabV2._entity_provenance_badges(fake, item)
        self.assertEqual(badges, [("Mixed", "warning"), ("Merged", "success")])

    def test_open_suggestion_evidence_prefers_evidence_source_and_alias(self) -> None:
        emitted: list[dict] = []
        fake = SimpleNamespace(evidenceOpenRequested=SimpleNamespace(emit=lambda payload: emitted.append(payload)))
        row = {
            "source_meeting_id": "m1",
            "source_kind": "edited",
            "source_alias": "A10",
            "evidence": [
                {
                    "source": "transcript",
                    "alias": "T10",
                    "text": "Please prepare launch memo by Friday",
                    "segment_index": 3,
                    "start_ms": 125000,
                }
            ],
        }
        ManagementTabV2._open_suggestion_evidence(fake, row)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["source_kind"], "transcript")
        self.assertEqual(emitted[0]["source_alias"], "T10")
        self.assertEqual(emitted[0]["segment_index"], 3)
        self.assertEqual(emitted[0]["start_ms"], 125000)


if __name__ == "__main__":
    unittest.main()
