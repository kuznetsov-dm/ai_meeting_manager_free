import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _workspace_tmpdir() -> Path:
    root = repo_root / "logs" / "_test_tmp"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"llama_cli_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestLlamaCliRuntimeBacklog(unittest.TestCase):
    def test_local_model_id_path_is_treated_as_local_gguf_not_hf_repo(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        tmp_path = _workspace_tmpdir()
        try:
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            local_model = tmp_path / "local-model.gguf"
            local_model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "### Meeting topic\nPortal rollout and task review."
                    self.stderr = ""

            run_mock = mock.Mock(return_value=_Proc())
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_id=str(local_model),
                    allow_download=True,
                )
                ctx = HookContext(
                    plugin_id="llm.llama_cli",
                    meeting_id="m1",
                    alias=None,
                    input_text="hello",
                    plugin_config={},
                )
                result = plugin.run(ctx)

            self.assertEqual(result.outputs[0].content, "### Meeting topic\nPortal rollout and task review.")
            cmd = run_mock.call_args[0][0]
            self.assertIn("-m", cmd)
            self.assertNotIn("--hf-repo", cmd)
            self.assertEqual(cmd[cmd.index("-m") + 1], str(local_model))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_invalid_hf_repo_format_returns_explicit_marker_instead_of_generic_load_failure(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        tmp_path = _workspace_tmpdir()
        try:
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")

            plugin = llama_cli.LlamaCliPlugin(
                binary_path=str(binary),
                model_id="bad-model-id",
                model_quant="Q4_K_M",
                allow_download=True,
                cache_dir=str(tmp_path / "cache"),
            )
            ctx = HookContext(
                plugin_id="llm.llama_cli",
                meeting_id="m1",
                alias=None,
                input_text="hello",
                plugin_config={},
            )
            result = plugin.run(ctx)

            self.assertIn("llama_cli_invalid_hf_repo_format", result.warnings)
            self.assertNotIn("llama_cli_failed(code=1)", result.warnings)
            self.assertIn("valid Hugging Face repo id", result.outputs[0].content)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_gpu_model_load_failure_surfaces_specific_marker(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        tmp_path = _workspace_tmpdir()
        try:
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "Qwen3-4B-Q4_K_M.gguf"
            model.write_bytes(b"")

            class _ProcFail:
                def __init__(self) -> None:
                    self.returncode = 1
                    self.stdout = ""
                    self.stderr = "\n".join(
                        [
                            "ggml_vulkan: Found 1 Vulkan devices:",
                            "error: unable to load model",
                        ]
                    )

            with mock.patch.object(llama_cli.subprocess, "run", return_value=_ProcFail()):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
                    gpu_layers=-1,
                )
                ctx = HookContext(
                    plugin_id="llm.llama_cli",
                    meeting_id="m1",
                    alias=None,
                    input_text="hello",
                    plugin_config={},
                )
                result = plugin.run(ctx)

            self.assertIn("llama_cli_failed(code=1)", result.warnings)
            self.assertIn("llama_cli_model_load_failed", result.warnings)
            self.assertTrue(any(w.startswith("llama_cli_stderr_digest=") for w in result.warnings))
            self.assertTrue(any(w.startswith("llama_cli_stderr_chunk[") for w in result.warnings))
            self.assertIn("mock_fallback", result.warnings)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
