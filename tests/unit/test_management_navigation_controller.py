# ruff: noqa: E402

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

from aimn.ui.controllers.management_navigation_controller import ManagementNavigationController


class _TextPanelStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def select_artifact_kind(self, kind: str) -> None:
        self.calls.append(("kind", kind))

    def select_version(self, **kwargs) -> None:
        self.calls.append(("version", dict(kwargs)))

    def jump_to_transcript_segment(self, **kwargs) -> None:
        self.calls.append(("jump", dict(kwargs)))

    def highlight_query(self, query: str) -> None:
        self.calls.append(("query", query))


class TestManagementNavigationController(unittest.TestCase):
    def test_build_pending_navigation_normalizes_payload(self) -> None:
        payload = ManagementNavigationController.build_pending_navigation(
            {
                "meeting_id": "m-1",
                "source_kind": "summary",
                "source_alias": "A7",
                "query": "launch memo",
                "segment_index": 3,
                "start_ms": 210000,
            },
            resolve_meeting_base=lambda key: f"base::{key}",
        )

        self.assertEqual(
            payload,
            {
                "base_name": "base::m-1",
                "kind": "summary",
                "alias": "A7",
                "query": "launch memo",
                "segment_index": 3,
                "start_ms": 210000,
            },
        )

    def test_build_pending_navigation_rejects_missing_base(self) -> None:
        payload = ManagementNavigationController.build_pending_navigation(
            {"meeting_id": ""},
            resolve_meeting_base=lambda _key: "",
        )

        self.assertIsNone(payload)

    def test_apply_pending_navigation_runs_text_panel_actions(self) -> None:
        panel = _TextPanelStub()

        applied = ManagementNavigationController.apply_pending_navigation(
            {
                "base_name": "m-base",
                "kind": "transcript",
                "alias": "T1",
                "query": "launch memo",
                "segment_index": 4,
                "start_ms": 3000,
            },
            selected_base="m-base",
            text_panel=panel,
        )

        self.assertTrue(applied)
        self.assertEqual(
            panel.calls,
            [
                ("kind", "transcript"),
                ("version", {"alias": "T1", "kind": "transcript"}),
                (
                    "jump",
                    {"segment_index": 4, "start_ms": 3000, "alias": "T1", "kind": "transcript"},
                ),
                ("query", "launch memo"),
            ],
        )

    def test_apply_pending_navigation_skips_mismatched_base(self) -> None:
        panel = _TextPanelStub()

        applied = ManagementNavigationController.apply_pending_navigation(
            {"base_name": "other"},
            selected_base="m-base",
            text_panel=panel,
        )

        self.assertFalse(applied)
        self.assertEqual(panel.calls, [])

    def test_route_navigation_request_applies_immediately_for_active_meeting(self) -> None:
        calls: list[tuple[str, str]] = []

        pending = ManagementNavigationController.route_navigation_request(
            {"meeting_id": "m-base", "source_kind": "summary"},
            resolve_meeting_base=lambda key: key,
            active_meeting_base_name="m-base",
            has_active_manifest=True,
            select_history=lambda base: calls.append(("history", base)),
            apply_pending=lambda base: calls.append(("apply", base)),
            select_meeting=lambda base: calls.append(("select", base)),
        )

        self.assertEqual(str(pending.get("base_name", "")), "m-base")
        self.assertEqual(calls, [("history", "m-base"), ("apply", "m-base")])

    def test_route_navigation_request_selects_meeting_when_not_active(self) -> None:
        calls: list[tuple[str, str]] = []

        pending = ManagementNavigationController.route_navigation_request(
            {"meeting_id": "m-base"},
            resolve_meeting_base=lambda key: key,
            active_meeting_base_name="other",
            has_active_manifest=False,
            select_history=lambda base: calls.append(("history", base)),
            apply_pending=lambda base: calls.append(("apply", base)),
            select_meeting=lambda base: calls.append(("select", base)),
        )

        self.assertEqual(str(pending.get("base_name", "")), "m-base")
        self.assertEqual(calls, [("history", "m-base"), ("select", "m-base")])


if __name__ == "__main__":
    unittest.main()
