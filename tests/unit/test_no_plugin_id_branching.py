import sys
import unittest
from pathlib import Path


class TestNoPluginIdBranching(unittest.TestCase):
    def test_core_and_ui_do_not_reference_llm_plugin_ids(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        src_root = repo_root / "src"
        for path in (repo_root, src_root):
            path_str = str(path)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)

        # Core/UI must be plugin-agnostic: no branching/knowledge about concrete plugin ids.
        roots = [src_root / "aimn" / "core", src_root / "aimn" / "ui"]
        offenders: list[str] = []
        for root in roots:
            for path in root.rglob("*.py"):
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                if "llm." in text:
                    offenders.append(str(path.relative_to(repo_root)))

        self.assertFalse(
            offenders,
            "Core/UI contains LLM plugin-id knowledge (e.g. 'llm.*'). Offenders:\n"
            + "\n".join(sorted(offenders)),
        )


if __name__ == "__main__":
    unittest.main()

