# ruff: noqa: E402

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

from aimn.ui.controllers.artifact_kind_bar_view_controller import ArtifactKindBarViewController


class _RowStub:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}

    def set_row(self, **kwargs) -> None:
        self.payload = dict(kwargs)


class TestArtifactKindBarViewController(unittest.TestCase):
    def test_rebuild_rows_builds_rows_and_resolves_active_kind(self) -> None:
        added: list[object] = []
        connected: list[object] = []

        rows, active_kind, visible = ArtifactKindBarViewController.rebuild_rows(
            kinds=["summary", "transcript"],
            current_active_kind="",
            kind_titles={"summary": "Summary", "transcript": "Transcript"},
            artifacts_by_kind={
                "summary": [SimpleNamespace(alias="S1")],
                "transcript": [SimpleNamespace(alias="T1")],
            },
            pinned_aliases={"transcription": "T1"},
            create_row=_RowStub,
            add_row=lambda row: added.append(row),
            connect_row_signals=lambda row: connected.append(row),
        )

        self.assertTrue(visible)
        self.assertEqual(active_kind, "transcript")
        self.assertEqual(list(rows.keys()), ["transcript", "summary"])
        self.assertEqual(len(added), 2)
        self.assertEqual(len(connected), 2)
        self.assertEqual(rows["transcript"].payload["title"], "Transcript")


if __name__ == "__main__":
    unittest.main()
