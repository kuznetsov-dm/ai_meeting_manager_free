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


class TestLlamaCliPromptHandling(unittest.TestCase):
    def test_cancelled_run_raises_cancelled_by_user_and_stops_process(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "qwen3.5-2b-instruct-q4_k_m.gguf"
            model.write_bytes(b"")

            class _FakeProcess:
                def __init__(self) -> None:
                    self.returncode = None
                    self.terminated = False
                    self.communicate_calls = 0

                def poll(self):
                    return self.returncode

                def communicate(self, timeout=None):
                    self.communicate_calls += 1
                    if self.terminated:
                        self.returncode = -15
                        return "", ""
                    raise llama_cli.subprocess.TimeoutExpired(cmd=["llama-cli"], timeout=timeout or 0)

                def terminate(self):
                    self.terminated = True
                    self.returncode = -15

                def wait(self, timeout=None):
                    self.returncode = -15
                    return self.returncode

                def kill(self):
                    self.terminated = True
                    self.returncode = -15

            process = _FakeProcess()

            with mock.patch.object(llama_cli.subprocess, "Popen", return_value=process) as popen_mock:
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
                )
                ctx = HookContext(
                    plugin_id="llm.llama_cli",
                    meeting_id="m1",
                    alias=None,
                    input_text="hello",
                    plugin_config={},
                    cancel_requested=lambda: True,
                )
                with self.assertRaisesRegex(RuntimeError, "cancelled_by_user"):
                    plugin.run(ctx)

            popen_mock.assert_not_called()

    def test_refine_prompt_prefers_local_cache_over_hf_repo_argument(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            cache_dir = tmp_path / "models"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_model = cache_dir / "minicpm4-8b-q4_k_m.gguf"
            cached_model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "Refined prompt"
                    self.stderr = ""

            run_mock = mock.Mock(return_value=_Proc())
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                result = llama_cli.action_refine_prompt(
                    {
                        "binary_path": str(binary),
                        "model_id": "AyyYOO/MiniCPM4-8B-Q4_K_M-GGUF",
                        "model_quant": "Q4_K_M",
                        "cache_dir": str(cache_dir),
                        "allow_download": True,
                    },
                    {"prompt_text": "Improve this prompt"},
                )

            self.assertEqual(result.status, "success")
            cmd = run_mock.call_args[0][0]
            self.assertIn("-m", cmd)
            self.assertNotIn("--hf-repo", cmd)
            self.assertEqual(cmd[cmd.index("-m") + 1], str(cached_model))

    def test_long_transcript_stays_single_pass_even_with_legacy_chunk_flag(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "### Meeting topic\nPortal rollout and task review."
                    self.stderr = ""

            captured_system_prompts: list[str] = []

            def _fake_run(cmd: list[str], **_: object) -> _Proc:
                if llama_cli.os.name == "nt":
                    captured_system_prompts.append(Path(cmd[cmd.index("-sysf") + 1]).read_text(encoding="utf-8"))
                else:
                    captured_system_prompts.append(cmd[cmd.index("-sys") + 1])
                return _Proc()

            run_mock = mock.Mock(side_effect=_fake_run)
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
                    prompt_profile="custom",
                    prompt_custom="Summarize actions and decisions.",
                    max_tokens=200,
                    ctx_size=4096,
                    use_chunking=True,
                )
                ctx = HookContext(
                    plugin_id="llm.llama_cli",
                    meeting_id="m1",
                    alias=None,
                    input_text=("word " * 5000).strip(),
                    plugin_config={},
                )
                result = plugin.run(ctx)

            self.assertEqual(result.outputs[0].content, "### Meeting topic\nPortal rollout and task review.")
            self.assertEqual(run_mock.call_count, 1)
            self.assertEqual(len(captured_system_prompts), 1)
            self.assertFalse(any(w.startswith("llama_cli_chunked_input(") for w in result.warnings))
            self.assertFalse(any("This is chunk 1 of" in item for item in captured_system_prompts))
            self.assertFalse(
                any("partial summaries generated from sequential chunks" in item for item in captured_system_prompts)
            )

    def test_long_transcript_stays_single_pass_by_default(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "qwen3.5-2b-instruct-q4_k_m.gguf"
            model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "### Meeting topic\nPortal rollout and task review."
                    self.stderr = ""

            run_mock = mock.Mock(return_value=_Proc())
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
                    prompt_profile="custom",
                    prompt_custom="Summarize actions and decisions.",
                    max_tokens=200,
                    ctx_size=4096,
                )
                ctx = HookContext(
                    plugin_id="llm.llama_cli",
                    meeting_id="m1",
                    alias=None,
                    input_text=("word " * 5000).strip(),
                    plugin_config={},
                )
                result = plugin.run(ctx)

            self.assertEqual(result.outputs[0].content, "### Meeting topic\nPortal rollout and task review.")
            self.assertEqual(run_mock.call_count, 1)
            self.assertFalse(any(w.startswith("llama_cli_chunked_input(") for w in result.warnings))
            cmd = run_mock.call_args[0][0]
            self.assertEqual(cmd[cmd.index("-n") + 1], "-1")

    def test_extracts_prompt_too_long_from_stderr_tail(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 1
                    self.stdout = ""
                    self.stderr = "\n".join(
                        [
                            "ggml_vulkan: Found 2 Vulkan devices:",
                            "main: prompt is too long (5019 tokens, max 4092)",
                        ]
                    )

            run_mock = mock.Mock(return_value=_Proc())
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
                    prompt_profile="",
                )
                ctx = HookContext(
                    plugin_id="llm.llama_cli",
                    meeting_id="m1",
                    alias=None,
                    input_text="hello",
                    plugin_config={},
                )
                result = plugin.run(ctx)

            self.assertTrue(any(w == "llama_cli_prompt_too_long" for w in result.warnings))
            self.assertTrue(any(w.startswith("llama_cli_stderr_tail=") for w in result.warnings))
            self.assertTrue(any(w == "mock_fallback" for w in result.warnings))
            self.assertIn("prompt exceeds context", result.outputs[0].content.lower())

    def test_strips_reasoning_block_from_successful_output(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "<think>internal</think>\n### Meeting topic\nPortal rollout and task review."
                    self.stderr = ""

            with mock.patch.object(llama_cli.subprocess, "run", return_value=_Proc()):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
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
            self.assertIn("llama_cli_reasoning_stripped", result.warnings)
            self.assertNotIn("mock_fallback", result.warnings)

    def test_corrupted_unicode_output_falls_back_to_mock(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "### Meeting topic\n" + ("\ufffd" * 24)
                    self.stderr = ""

            with mock.patch.object(llama_cli.subprocess, "run", return_value=_Proc()):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
                )
                ctx = HookContext(
                    plugin_id="llm.llama_cli",
                    meeting_id="m1",
                    alias=None,
                    input_text="hello",
                    plugin_config={},
                )
                result = plugin.run(ctx)

            self.assertIn("llama_cli_output_corrupted", result.warnings)
            self.assertIn("mock_fallback", result.warnings)
            self.assertIn("not ready", result.outputs[0].content.lower())

    def test_phi4_uses_tokenizer_override(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "Phi-4-mini-instruct-q4_k_m.gguf"
            model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "### Meeting topic\nPortal rollout and task review."
                    self.stderr = ""

            run_mock = mock.Mock(return_value=_Proc())
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
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
            self.assertIn("llama_cli_tokenizer_pre_override(default)", result.warnings)
            cmd = run_mock.call_args[0][0]
            self.assertIn("--override-kv", cmd)
            self.assertIn("tokenizer.ggml.pre=str:default", cmd)

    def test_phi4_retries_without_tokenizer_override_after_model_load_failure(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "Phi-4-mini-instruct-q4_k_m.gguf"
            model.write_bytes(b"")

            class _ProcFail:
                def __init__(self) -> None:
                    self.returncode = 1
                    self.stdout = ""
                    self.stderr = "error: unable to load model because tokenizer.ggml.pre override is invalid"

            class _ProcOk:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "### Meeting topic\nPortal rollout and task review."
                    self.stderr = ""

            run_mock = mock.Mock(side_effect=[_ProcFail(), _ProcOk()])
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
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
            self.assertIn("llama_cli_tokenizer_pre_override(default)", result.warnings)
            self.assertIn("llama_cli_tokenizer_pre_override_disabled_after_failure", result.warnings)
            self.assertEqual(run_mock.call_count, 2)
            first_cmd = run_mock.call_args_list[0][0][0]
            second_cmd = run_mock.call_args_list[1][0][0]
            self.assertIn("--override-kv", first_cmd)
            self.assertIn("tokenizer.ggml.pre=str:default", first_cmd)
            self.assertNotIn("--override-kv", second_cmd)

    def test_gpu_backend_failure_stays_failed_without_hidden_cpu_retry(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
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

            run_mock = mock.Mock(return_value=_ProcFail())
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
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

            self.assertEqual(run_mock.call_count, 1)
            self.assertIn("llama_cli_failed(code=1)", result.warnings)
            self.assertTrue(any(w.startswith("llama_cli_stderr_tail=") for w in result.warnings))
            self.assertIn("mock_fallback", result.warnings)

    def test_disable_thinking_prefixes_qwen3_user_prompt(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")
            model = tmp_path / "Qwen3-4B-Q4_K_M.gguf"
            model.write_bytes(b"")

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "### Meeting topic\nPortal rollout and task review."
                    self.stderr = ""

            captured_user_prompt = {"value": ""}

            def _fake_run(cmd: list[str], **_: object) -> _Proc:
                if llama_cli.os.name == "nt":
                    captured_user_prompt["value"] = Path(cmd[cmd.index("-f") + 1]).read_text(encoding="utf-8")
                else:
                    captured_user_prompt["value"] = cmd[cmd.index("-p") + 1]
                return _Proc()

            with mock.patch.object(llama_cli.subprocess, "run", side_effect=_fake_run):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_path=str(model),
                    disable_thinking=True,
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
            self.assertTrue(captured_user_prompt["value"].startswith("/no_think"))


if __name__ == "__main__":
    unittest.main()

