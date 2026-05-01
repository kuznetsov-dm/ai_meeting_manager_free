import shutil
import sys
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
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


class TestLlamaCliPrefersLocalCache(unittest.TestCase):
    def test_filtered_params_replaces_uninstalled_selected_model_with_installed_favorite(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        filtered = llama_cli._filtered_params(  # noqa: SLF001
            {
                "model_id": "Lumia101/NVIDIA-Nemotron-Nano-9B-v2-Q4_K_M-GGUF",
                "model_quant": "Q4_K_M",
                "models": [
                    {
                        "model_id": "Lumia101/NVIDIA-Nemotron-Nano-9B-v2-Q4_K_M-GGUF",
                        "quant": "Q4_K_M",
                        "installed": False,
                    },
                    {
                        "model_id": "Qwen/Qwen3-1.7B-GGUF",
                        "quant": "Q8_0",
                        "installed": True,
                        "favorite": True,
                    },
                    {
                        "model_id": "unsloth/Qwen3-0.6B-GGUF",
                        "quant": "Q4_K_M",
                        "installed": True,
                    },
                ],
            }
        )

        self.assertEqual(filtered["model_id"], "Qwen/Qwen3-1.7B-GGUF")
        self.assertEqual(filtered["model_quant"], "Q8_0")
        self.assertEqual(filtered["model_path"], "")

    def test_pick_local_gguf_prefers_best_variant_match(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        tmp_path = _workspace_tmpdir()
        try:
            for name in (
                "Qwen3-0.6B-Q4_K_M.gguf",
                "Qwen3-4B-Q4_K_M.gguf",
                "Qwen3.5-0.8B-Q4_K_M.gguf",
                "Qwen3.5-2B-Q4_K_M.gguf",
                "Qwen3.5-4B-Q4_K_M.gguf",
            ):
                (tmp_path / name).write_bytes(b"GGUF")

            picked = llama_cli._maybe_pick_local_gguf_from_cache(  # noqa: SLF001
                str(tmp_path),
                "unsloth/Qwen3.5-4B-GGUF",
                "Q4_K_M",
            )
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

        self.assertEqual(Path(picked).name, "Qwen3.5-4B-Q4_K_M.gguf")

    def test_pick_local_gguf_does_not_replace_model_id_match_with_quant_only_match(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        tmp_path = _workspace_tmpdir()
        try:
            for name in (
                "Qwen3-0.6B-Q4_K_M.gguf",
                "Qwen3-1.7B-Q8_0.gguf",
            ):
                (tmp_path / name).write_bytes(b"GGUF")

            picked = llama_cli._maybe_pick_local_gguf_from_cache(  # noqa: SLF001
                str(tmp_path),
                "Qwen/Qwen3-1.7B-GGUF",
                "Q4_K_M",
            )
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

        self.assertEqual(Path(picked).name, "Qwen3-1.7B-Q8_0.gguf")

    def test_plugin_run_uses_model_id_matched_file_even_when_quant_matches_other_file(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        tmp_path = _workspace_tmpdir()
        try:
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"binary")
            for name in (
                "Qwen3-0.6B-Q4_K_M.gguf",
                "Qwen3-1.7B-Q8_0.gguf",
            ):
                (tmp_path / name).write_bytes(b"GGUFdemo")

            ctx = HookContext(
                plugin_id="llm.llama_cli",
                meeting_id="m1",
                alias=None,
                input_text="hello",
                plugin_config={},
            )

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "OK"
                    self.stderr = ""

            run_mock = mock.Mock(return_value=_Proc())
            with mock.patch.object(llama_cli, "_run_command_with_cancel", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_id="Qwen/Qwen3-1.7B-GGUF",
                    model_quant="Q4_K_M",
                    allow_download=False,
                    cache_dir=str(tmp_path),
                )
                result = plugin.run(ctx)

            self.assertEqual(result.outputs[0].content, "OK")
            cmd = run_mock.call_args.args[0]
            self.assertIn("-m", cmd)
            self.assertEqual(cmd[cmd.index("-m") + 1], str(tmp_path / "Qwen3-1.7B-Q8_0.gguf"))
            self.assertNotIn("--hf-repo", cmd)
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

    def test_uses_local_gguf_when_present(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli
        from aimn.plugins.api import HookContext

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / ("llama-cli.exe" if llama_cli.os.name == "nt" else "llama-cli")
            binary.write_bytes(b"")

            gguf = tmp_path / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            gguf.write_bytes(b"")

            ctx = HookContext(
                plugin_id="llm.llama_cli",
                meeting_id="m1",
                alias=None,
                input_text="hello",
                plugin_config={},
            )

            class _Proc:
                def __init__(self) -> None:
                    self.returncode = 0
                    self.stdout = "OK"
                    self.stderr = ""

            run_mock = mock.Mock(return_value=_Proc())
            with mock.patch.object(llama_cli.subprocess, "run", run_mock):
                plugin = llama_cli.LlamaCliPlugin(
                    binary_path=str(binary),
                    model_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                    model_quant="Q4_K_M",
                    allow_download=True,
                    cache_dir=str(tmp_path),
                )
                result = plugin.run(ctx)

            self.assertEqual(result.outputs[0].content, "OK")
            self.assertEqual(run_mock.call_count, 1)
            cmd = run_mock.call_args[0][0]
            self.assertIn("-m", cmd)
            self.assertNotIn("--hf-repo", cmd)
            self.assertIn(str(gguf), cmd)

    def test_remove_model_resolves_relative_cache_dir_from_app_root(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_root = tmp_path / "models" / "llama"
            cache_root.mkdir(parents=True, exist_ok=True)
            gguf = cache_root / "qwen2.5-3b-instruct-q4_k_m.gguf"
            gguf.write_bytes(b"gguf")

            settings = {
                "cache_dir": "models/llama",
                "models": [
                    {
                        "model_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
                        "product_name": "Qwen2.5 3B Instruct (GGUF)",
                        "quant": "Q4_K_M",
                        "file": gguf.name,
                        "enabled": True,
                    }
                ],
            }
            params = {
                "model_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
                "quant": "Q4_K_M",
                "file": gguf.name,
            }

            with mock.patch.dict(llama_cli.os.environ, {"AIMN_HOME": str(tmp_path)}, clear=False):
                result = llama_cli.action_remove_model(settings, params)

            self.assertEqual(result.status, "success")
            self.assertEqual(result.message, "model_removed")
            self.assertFalse(gguf.exists())
            self.assertIsInstance(result.data, dict)
            models = result.data.get("models")
            self.assertIsInstance(models, list)
            self.assertFalse(models[0].get("installed"))

    def test_remove_model_resolves_exact_filename_when_filename_is_missing(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_root = tmp_path / "models" / "llama"
            cache_root.mkdir(parents=True, exist_ok=True)
            gguf = cache_root / "Qwen3-4B-Q4_K_M.gguf"
            gguf.write_bytes(b"gguf")

            settings = {"cache_dir": "models/llama", "models": []}
            params = {
                "model_id": "Qwen/Qwen3-4B-GGUF",
                "quant": "Q4_K_M",
            }

            with mock.patch.dict(llama_cli.os.environ, {"AIMN_HOME": str(tmp_path)}, clear=False), mock.patch.object(
                llama_cli, "_resolve_hf_filename", return_value=gguf.name
            ):
                result = llama_cli.action_remove_model(settings, params)

            self.assertEqual(result.status, "success")
            self.assertEqual(result.message, "model_removed")
            self.assertFalse(gguf.exists())

    def test_list_models_returns_empty_when_settings_models_are_empty(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.dict(llama_cli.os.environ, {"AIMN_HOME": str(tmp_path)}, clear=False):
                result = llama_cli.action_list_models({"cache_dir": "models/llama", "models": []}, {})

        self.assertEqual(result.status, "success")
        self.assertIsInstance(result.data, dict)
        model_ids = {str(entry.get("model_id", "")) for entry in result.data.get("models", [])}
        self.assertEqual(model_ids, set())

    def test_list_models_keeps_user_added_models_without_injecting_starter_rows(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = {
                "cache_dir": "models/llama",
                "models": [
                    {
                        "model_id": "custom/local-demo",
                        "product_name": "Custom Local Demo",
                        "download_url": "https://example.test/custom-local-demo.gguf",
                        "file": "custom-local-demo.gguf",
                        "user_added": True,
                    }
                ],
            }
            with mock.patch.dict(llama_cli.os.environ, {"AIMN_HOME": str(tmp_path)}, clear=False):
                result = llama_cli.action_list_models(settings, {})

        self.assertEqual(result.status, "success")
        self.assertIsInstance(result.data, dict)
        rows = {str(entry.get("model_id", "")): entry for entry in result.data.get("models", [])}
        self.assertIn("custom/local-demo", rows)
        self.assertTrue(bool(rows["custom/local-demo"].get("user_added", False)))

    def test_builtin_model_rows_prefer_passport_over_legacy_content(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        rows = llama_cli._builtin_model_rows()  # noqa: SLF001

        ids = {str(entry.get("id", "") or entry.get("model_id", "")).strip() for entry in rows if isinstance(entry, dict)}
        self.assertIn("unsloth/Qwen3-0.6B-GGUF", ids)
        self.assertIn("Qwen/Qwen3-1.7B-GGUF", ids)
        self.assertEqual(len(ids), 2)


if __name__ == "__main__":
    unittest.main()

