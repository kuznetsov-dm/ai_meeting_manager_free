import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest import mock


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


@unittest.skipUnless(os.name == "nt", "Windows-only: checks 0xC0000135 caching path")
class TestLlamaCliMissingDllCache(unittest.TestCase):
    def test_skips_repeated_runs_after_missing_dll(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            binary = Path(tmp) / "llama-cli.exe"
            binary.write_bytes(b"")

            ctx = HookContext(
                plugin_id="llm.llama_cli",
                meeting_id="m1",
                alias=None,
                input_text="hello",
                plugin_config={},
            )

            class _Proc:
                def __init__(self, returncode: int) -> None:
                    self.returncode = returncode
                    self.stdout = ""
                    self.stderr = ""

            with llama_cli._BROKEN_BINARIES_LOCK:
                llama_cli._BROKEN_BINARIES.clear()

            run_mock = mock.Mock(return_value=_Proc(3221225781))
            with (
                mock.patch.object(llama_cli, "_windows_dll_diagnostics", return_value={"platform": "windows", "missing": ["vcruntime140.dll"]}),
                mock.patch.object(llama_cli, "_run_command_with_cancel", run_mock),
            ):
                p1 = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                    allow_download=True,
                    cache_dir=str(Path(tmp) / "cache"),
                )
                r1 = p1.run(ctx)

                p2 = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                    allow_download=True,
                    cache_dir=str(Path(tmp) / "cache"),
                )
                r2 = p2.run(ctx)

            self.assertEqual(run_mock.call_count, 1)
            self.assertTrue(any(w.startswith("llama_cli_missing_dll_dependencies(0xC0000135") for w in r1.warnings))
            self.assertTrue(any(w.startswith("llama_cli_missing_dll_dependencies(0xC0000135") for w in r2.warnings))

    def test_does_not_reuse_missing_dll_cache_when_diagnostics_are_clear(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            binary = Path(tmp) / "llama-cli.exe"
            binary.write_bytes(b"")
            cache_dir = str(Path(tmp) / "cache")

            ctx = HookContext(
                plugin_id="llm.llama_cli",
                meeting_id="m1",
                alias=None,
                input_text="hello",
                plugin_config={},
            )

            first = llama_cli._CommandRunResult(returncode=3221225781, stdout="", stderr="")
            second = llama_cli._CommandRunResult(
                returncode=0,
                stdout="### Meeting topic\nStatus update and actions reviewed.",
                stderr="",
            )
            run_mock = mock.Mock(side_effect=[first, second])

            with llama_cli._BROKEN_BINARIES_LOCK:
                llama_cli._BROKEN_BINARIES.clear()

            with mock.patch.object(llama_cli, "_run_command_with_cancel", run_mock):
                with mock.patch.object(
                    llama_cli,
                    "_windows_dll_diagnostics",
                    side_effect=[
                        {"platform": "windows", "missing": []},
                        {"platform": "windows", "missing": []},
                    ],
                ):
                    p1 = llama_cli.LlamaCliPlugin(
                        binary_path=str(binary),
                        model_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                        allow_download=True,
                        cache_dir=cache_dir,
                    )
                    r1 = p1.run(ctx)
                    p2 = llama_cli.LlamaCliPlugin(
                        binary_path=str(binary),
                        model_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                        allow_download=True,
                        cache_dir=cache_dir,
                    )
                    r2 = p2.run(ctx)

            self.assertEqual(run_mock.call_count, 2)
            self.assertIn("llama_cli_missing_dll_dependencies(0xC0000135)", r1.warnings)
            self.assertNotIn("mock_fallback", r2.warnings)
            self.assertEqual(r2.outputs[0].content, "### Meeting topic\nStatus update and actions reviewed.")


if __name__ == "__main__":
    unittest.main()


