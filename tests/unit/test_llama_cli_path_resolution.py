import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestLlamaCliPathResolution(unittest.TestCase):
    def test_resolve_path_prefers_aimn_home_for_relative_binary(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            bin_dir = app_root / "bin" / "llama"
            bin_dir.mkdir(parents=True, exist_ok=True)
            binary_name = "llama-cli.exe" if os.name == "nt" else "llama-cli"
            binary = bin_dir / binary_name
            binary.write_text("stub", encoding="utf-8")

            with mock.patch.dict(os.environ, {"AIMN_HOME": str(app_root)}, clear=False):
                resolved = llama_cli._resolve_path("bin/llama/llama-cli", "AIMN_LLAMA_CLI_PATH")

        self.assertEqual(Path(resolved), binary)


if __name__ == "__main__":
    unittest.main()

