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

from aimn.ui.controllers.inspection_render_controller import InspectionRenderController


def _meeting_with_node() -> object:
    node = SimpleNamespace(
        tool=SimpleNamespace(plugin_id="llm.openrouter", version="1.0"),
        created_at="2026-02-14T10:00:00Z",
        fingerprint="abc123",
        cacheable=True,
        inputs=SimpleNamespace(parent_nodes=["t1"], source_ids=["src1"]),
        params={"model_id": "m1"},
        artifacts=[SimpleNamespace(kind="summary", path="out.md"), SimpleNamespace(kind="tasks", path="t.json")],
    )
    return SimpleNamespace(
        meeting_id="",
        nodes={"ai1": node},
        pinned_aliases={"llm_processing": "ai1"},
        active_aliases={"llm_processing": "ai1"},
    )


class TestInspectionRenderController(unittest.TestCase):
    def test_render_includes_node_details(self) -> None:
        controller = InspectionRenderController(app_root=repo_root)
        html = controller.render_inspection_html(
            _meeting_with_node(),
            stage_id="llm_processing",
            alias="ai1",
            kind="summary",
        )
        self.assertIn("llm.openrouter", html)
        self.assertIn("Fingerprint", html)
        self.assertIn("Artifacts", html)
        self.assertIn("summary", html)
        self.assertNotIn("tasks</b>", html)

    def test_render_handles_missing_node(self) -> None:
        meeting = SimpleNamespace(meeting_id="", nodes={}, pinned_aliases={}, active_aliases={})
        controller = InspectionRenderController(app_root=repo_root)
        html = controller.render_inspection_html(
            meeting,
            stage_id="llm_processing",
            alias="missing",
            kind="summary",
        )
        self.assertIn("Lineage node not found", html)


if __name__ == "__main__":
    unittest.main()
