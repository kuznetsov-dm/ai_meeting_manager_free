import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


from aimn.core.stages.base import PluginStageAdapter  # noqa: E402


class TestStageBaseArtifactResolution(unittest.TestCase):
    def test_get_artifact_prefers_active_alias_for_kind(self) -> None:
        output_dir = repo_root / ".codex_tmp_test" / "artifact_resolution"
        output_dir.mkdir(parents=True, exist_ok=True)
        newer = output_dir / "newer.edited.md"
        active = output_dir / "active.edited.md"
        newer.write_text("semantic refiner", encoding="utf-8")
        active.write_text("minutes output", encoding="utf-8")

        meeting = SimpleNamespace(
            active_aliases={"text_processing": "sgen1"},
            nodes={
                "sgen1": SimpleNamespace(
                    created_at="2026-04-24T10:00:00Z",
                    artifacts=[SimpleNamespace(kind="edited", path="active.edited.md", content_type="text/markdown", user_visible=True)],
                ),
                "sgen2": SimpleNamespace(
                    created_at="2026-04-24T10:01:00Z",
                    artifacts=[SimpleNamespace(kind="edited", path="newer.edited.md", content_type="text/markdown", user_visible=True)],
                ),
            },
        )
        context = SimpleNamespace(output_dir=str(output_dir), meeting=meeting)

        artifact = PluginStageAdapter._get_artifact(context, "edited")

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.meta.path, "active.edited.md")
        self.assertEqual(artifact.content, "minutes output")


if __name__ == "__main__":
    unittest.main()
