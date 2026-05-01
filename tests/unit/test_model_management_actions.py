import json
import sys
import time
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.ui.pipeline_worker import _format_stage_error  # noqa: E402
from plugins.llm.llama_cli import llama_cli as llama_mod  # noqa: E402
from plugins.llm.ollama import ollama as ollama_mod  # noqa: E402
from plugins.transcription.whisper_advanced import whisper_advanced as whisper_mod  # noqa: E402


class TestModelManagementActions(unittest.TestCase):
    def test_llama_cli_list_models_reports_installed(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            installed_file = cache_dir / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
            installed_file.write_bytes(b"gguf")
            settings = {
                "cache_dir": str(cache_dir),
                "models": [
                    {
                        "model_id": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                        "product_name": "TinyLlama",
                        "quant": "Q4_K_M",
                        "file": installed_file.name,
                        "enabled": True,
                    },
                    {
                        "model_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
                        "product_name": "Qwen 1.5B",
                        "quant": "Q4_K_M",
                        "file": "",
                        "enabled": True,
                    },
                ],
            }
            result = llama_mod.action_list_models(settings, {})
            self.assertEqual(result.status, "success")
            self.assertIsInstance(result.data, dict)
            rows = result.data.get("models", [])
            self.assertTrue(isinstance(rows, list) and rows)
            by_id = {str(item.get("model_id", "")): item for item in rows if isinstance(item, dict)}
            self.assertTrue(by_id["TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"]["installed"])
            self.assertFalse(by_id["Qwen/Qwen2.5-1.5B-Instruct-GGUF"]["installed"])

    def test_llama_cli_list_models_ignores_partial_download_files(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            partial_file = cache_dir / "phi-4-mini-instruct-q4_k_m.gguf.part"
            partial_file.write_bytes(b"partial")
            settings = {
                "cache_dir": str(cache_dir),
                "models": [
                    {
                        "model_id": "alpacapilot/Phi-4-mini-instruct-Q4_K_M-GGUF",
                        "product_name": "Phi-4 Mini Instruct (GGUF)",
                        "quant": "Q4_K_M",
                        "file": "phi-4-mini-instruct-q4_k_m.gguf",
                        "enabled": True,
                    }
                ],
            }

            result = llama_mod.action_list_models(settings, {})

            self.assertEqual(result.status, "success")
            self.assertIsInstance(result.data, dict)
            rows = result.data.get("models", [])
            self.assertTrue(isinstance(rows, list) and rows)
            by_id = {str(item.get("model_id", "")): item for item in rows if isinstance(item, dict)}
            self.assertFalse(by_id["alpacapilot/Phi-4-mini-instruct-Q4_K_M-GGUF"]["installed"])

    def test_llama_cli_list_models_does_not_mark_other_instruct_model_as_installed(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            installed_file = cache_dir / "phi-4-mini-instruct-q4_k_m.gguf"
            installed_file.write_bytes(b"gguf")
            settings = {
                "cache_dir": str(cache_dir),
                "models": [
                    {
                        "model_id": "Qwen/Qwen3-4B-GGUF",
                        "product_name": "Qwen3 4B",
                        "quant": "Q4_K_M",
                        "file": "",
                        "enabled": True,
                    }
                ],
            }

            result = llama_mod.action_list_models(settings, {})

            self.assertEqual(result.status, "success")
            self.assertIsInstance(result.data, dict)
            rows = {str(item.get("model_id", "")): item for item in result.data.get("models", []) if isinstance(item, dict)}
            self.assertIn("Qwen/Qwen3-4B-GGUF", rows)
            self.assertFalse(rows["Qwen/Qwen3-4B-GGUF"]["installed"])
            self.assertEqual(rows["Qwen/Qwen3-4B-GGUF"]["file"], "Qwen3-4B-Q4_K_M.gguf")

    def test_llama_cli_builtin_catalog_includes_observed_success_models(self) -> None:
        rows = llama_mod._builtin_model_rows()  # noqa: SLF001
        by_id = {str(item.get("id", "")): item for item in rows if isinstance(item, dict)}

        self.assertIn("unsloth/Qwen3-0.6B-GGUF", by_id)
        self.assertIn("Qwen/Qwen3-1.7B-GGUF", by_id)

    def test_llama_cli_download_model_uses_known_file_and_direct_url_before_starting_job(self) -> None:
        settings = {
            "cache_dir": "models/llama",
            "models": [
                {
                    "model_id": "Qwen/Qwen3-4B-GGUF",
                    "product_name": "Qwen3 4B",
                    "quant": "Q4_K_M",
                    "file": "Qwen3-4B-Q4_K_M.gguf",
                    "download_url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
                    "enabled": True,
                }
            ],
        }
        params = {"model_id": "Qwen/Qwen3-4B-GGUF", "quant": "Q4_K_M"}

        with patch("plugins.llm.llama_cli.llama_cli._start_download_job",
            return_value="job-123",
        ) as start_job:
            result = llama_mod.action_download_model(settings, params)

        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.job_id, "job-123")
        self.assertIsInstance(result.data, dict)
        self.assertEqual(result.data.get("file"), "Qwen3-4B-Q4_K_M.gguf")
        start_job.assert_called_once_with(
            "Qwen/Qwen3-4B-GGUF",
            "Q4_K_M",
            "models/llama",
            download_url="https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
            file_name="Qwen3-4B-Q4_K_M.gguf",
            hf_token="",
        )

    def test_llama_cli_download_model_uses_hf_token_for_filename_resolution(self) -> None:
        settings = {
            "cache_dir": "models/llama",
            "hf_token": "hf_test_token",
            "models": [
                {
                    "model_id": "Qwen/Qwen3-4B-GGUF",
                    "product_name": "Qwen3 4B",
                    "quant": "Q4_K_M",
                    "enabled": True,
                }
            ],
        }
        params = {"model_id": "Qwen/Qwen3-4B-GGUF", "quant": "Q4_K_M"}

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._stream = BytesIO(json.dumps(payload).encode("utf-8"))
                self.headers = {}

            def read(self, size: int | None = None) -> bytes:
                return self._stream.read() if size is None else self._stream.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def _urlopen(request, timeout=None):
            self.assertEqual(
                getattr(request, "full_url", ""),
                "https://huggingface.co/api/models/Qwen/Qwen3-4B-GGUF",
            )
            self.assertEqual(request.get_header("Authorization"), "Bearer hf_test_token")
            return _JsonResponse({"siblings": [{"rfilename": "Qwen3-4B-Q4_K_M.gguf"}]})

        with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen), patch(
            "plugins.llm.llama_cli.llama_cli._start_download_job",
            return_value="job-123",
        ) as start_job:
            result = llama_mod.action_download_model(settings, params)

        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.job_id, "job-123")
        self.assertEqual(result.data.get("file"), "Qwen3-4B-Q4_K_M.gguf")
        start_job.assert_called_once_with(
            "Qwen/Qwen3-4B-GGUF",
            "Q4_K_M",
            "models/llama",
            download_url="",
            file_name="Qwen3-4B-Q4_K_M.gguf",
            hf_token="hf_test_token",
        )

    def test_llama_cli_resolve_hf_filename_retries_without_proxy_for_hf_requests(self) -> None:
        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._stream = BytesIO(json.dumps(payload).encode("utf-8"))
                self.headers = {}

            def read(self, size: int | None = None) -> bytes:
                return self._stream.read() if size is None else self._stream.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def _urlopen(_request, timeout=None):
            raise urllib.error.URLError("[WinError 10061] No connection could be made because the target machine actively refused it 127.0.0.1:9")

        opener = unittest.mock.Mock()
        opener.open.return_value = _JsonResponse({"siblings": [{"rfilename": "Qwen3-4B-Q4_K_M.gguf"}]})

        with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen), patch(
            "plugins.llm.llama_cli.llama_cli.urllib.request.getproxies",
            return_value={"https": "http://127.0.0.1:9"},
        ), patch(
            "plugins.llm.llama_cli.llama_cli.urllib.request.build_opener",
            return_value=opener,
        ):
            resolved = llama_mod._resolve_hf_filename("Qwen/Qwen3-4B-GGUF", "Q4_K_M")  # noqa: SLF001

        self.assertEqual(resolved, "Qwen3-4B-Q4_K_M.gguf")
        opener.open.assert_called_once()

    def test_llama_cli_download_model_reports_hf_auth_error_for_gated_repo(self) -> None:
        settings = {
            "cache_dir": "models/llama",
            "models": [
                {
                    "model_id": "meta-llama/Llama-4-1.5B-Instruct-GGUF",
                    "product_name": "Llama 4 1.5B",
                    "quant": "Q4_K_M",
                    "enabled": True,
                }
            ],
        }
        params = {"model_id": "meta-llama/Llama-4-1.5B-Instruct-GGUF", "quant": "Q4_K_M"}

        def _urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                getattr(request, "full_url", "https://huggingface.co"),
                401,
                "Unauthorized",
                hdrs={},
                fp=BytesIO(b""),
            )

        with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen), patch(
            "plugins.llm.llama_cli.llama_cli._start_download_job"
        ) as start_job:
            result = llama_mod.action_download_model(settings, params)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "model_file_resolution_failed")
        self.assertIn("Hugging Face access denied (401)", str(result.data.get("error", "")))
        self.assertIn("HUGGINGFACE_HUB_TOKEN", str(result.data.get("error", "")))
        start_job.assert_not_called()

    def test_llama_cli_validate_hf_token_uses_auth_header(self) -> None:
        settings = {"hf_token": "hf_test_token"}

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._stream = BytesIO(json.dumps(payload).encode("utf-8"))
                self.headers = {}

            def read(self, size: int | None = None) -> bytes:
                return self._stream.read() if size is None else self._stream.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def _urlopen(request, timeout=None):
            self.assertEqual(getattr(request, "full_url", ""), "https://huggingface.co/api/whoami-v2")
            self.assertEqual(request.get_header("Authorization"), "Bearer hf_test_token")
            self.assertEqual(timeout, 15)
            return _JsonResponse({"name": "demo-user"})

        with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen):
            result = llama_mod.action_validate_hf_token(settings, {})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "hf_token_valid")
        self.assertEqual(result.data.get("account"), "demo-user")

    def test_llama_cli_validate_hf_token_reports_invalid_token(self) -> None:
        settings = {"hf_token": "hf_test_token"}

        def _urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                getattr(request, "full_url", "https://huggingface.co/api/whoami-v2"),
                401,
                "Unauthorized",
                hdrs={},
                fp=BytesIO(b""),
            )

        with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen):
            result = llama_mod.action_validate_hf_token(settings, {})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "hf_token_invalid")
        self.assertIn("Hugging Face access denied (401)", str(result.data.get("error", "")))

    def test_whisper_actions_list_pull_remove(self) -> None:
        with TemporaryDirectory() as tmp:
            models_dir = Path(tmp)
            settings = {"models_dir": str(models_dir), "models": []}

            listed = whisper_mod.action_list_models(settings, {})
            self.assertEqual(listed.status, "success")
            self.assertIsInstance(listed.data, dict)
            rows = listed.data.get("models", [])
            self.assertTrue(any(str(item.get("model_id", "")) == "tiny" for item in rows if isinstance(item, dict)))
            ids = {str(item.get("model_id", "")) for item in rows if isinstance(item, dict)}
            self.assertIn("large-v3-turbo-q5_0", ids)
            self.assertNotIn("large", ids)
            tiny_row = next(item for item in rows if isinstance(item, dict) and item.get("model_id") == "tiny")
            self.assertEqual(
                tiny_row.get("download_url"),
                "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
            )

            tiny_path = models_dir / whisper_mod._MODEL_FILES["tiny"]  # noqa: SLF001

            def _fake_download(
                model: str,
                models_dir_arg: str | None,
                model_url: str | None = None,
                progress_cb=None,
            ):
                self.assertEqual(model, "tiny")
                path = tiny_path
                path.parent.mkdir(parents=True, exist_ok=True)
                if callable(progress_cb):
                    progress_cb(25)
                    progress_cb(100)
                path.write_bytes(b"model")
                return path

            with patch("plugins.transcription.whisper_advanced.whisper_advanced.download_model", _fake_download):
                pulled = whisper_mod.action_pull_model(settings, {"model_id": "tiny"})
                self.assertEqual(pulled.status, "accepted")
                self.assertTrue(bool(pulled.job_id))
                self.assertEqual(pulled.data.get("file"), whisper_mod._MODEL_FILES["tiny"])  # noqa: SLF001

                status = None
                for _ in range(200):
                    status = whisper_mod._get_job_status(pulled.job_id)  # noqa: SLF001
                    if isinstance(status, dict) and str(status.get("status", "")) in {"success", "error"}:
                        break
                    time.sleep(0.01)

            self.assertTrue(tiny_path.exists())
            self.assertIsInstance(status, dict)
            self.assertEqual(status.get("status"), "success")
            self.assertEqual(status.get("message"), "downloaded")

            removed = whisper_mod.action_remove_model(settings, {"model_id": "tiny"})
            self.assertEqual(removed.status, "success")
            self.assertEqual(removed.message, "model_removed")
            self.assertEqual(removed.data.get("model_id"), "tiny")
            self.assertEqual(removed.data.get("file"), "ggml-tiny.bin")
            self.assertFalse(tiny_path.exists())

    def test_ollama_list_models_returns_empty_list_when_server_unavailable(self) -> None:
        settings = {"ollama_url": "http://127.0.0.1:11434", "auto_start_server": False}

        with patch.object(
            ollama_mod.OllamaServerManager,
            "check_server",
            return_value=ollama_mod.OllamaServerStatus(running=False, url="http://127.0.0.1:11434", error="down"),
        ):
            result = ollama_mod.action_list_models(settings, {})

        self.assertEqual(result.status, "error")
        self.assertIsInstance(result.data, dict)
        rows = result.data.get("models", [])
        self.assertEqual(rows, [])

    def test_ollama_list_models_merges_catalog_and_installed(self) -> None:
        settings = {"ollama_url": "http://127.0.0.1:11434", "auto_start_server": False}
        installed = [ollama_mod.OllamaInstalledModel(name="llama3.2")]

        with (
            patch.object(
                ollama_mod.OllamaServerManager,
                "check_server",
                return_value=ollama_mod.OllamaServerStatus(running=True, url="http://127.0.0.1:11434"),
            ),
            patch.object(ollama_mod.OllamaModelManager, "list_models", return_value=installed),
        ):
            result = ollama_mod.action_list_models(settings, {})

        self.assertEqual(result.status, "success")
        self.assertIsInstance(result.data, dict)
        rows = result.data.get("models", [])
        self.assertTrue(isinstance(rows, list) and rows)
        by_id = {str(item.get("model_id", "")): item for item in rows if isinstance(item, dict)}
        self.assertIn("llama3.2", by_id)
        self.assertTrue(bool(by_id["llama3.2"].get("installed")))

    def test_ollama_list_models_keeps_exact_installed_tag_and_enriches_from_passport(self) -> None:
        settings = {"ollama_url": "http://127.0.0.1:11434", "auto_start_server": False}
        installed = [ollama_mod.OllamaInstalledModel(name="gemma2:2b:latest")]

        with (
            patch.object(
                ollama_mod.OllamaServerManager,
                "check_server",
                return_value=ollama_mod.OllamaServerStatus(running=True, url="http://127.0.0.1:11434"),
            ),
            patch.object(ollama_mod.OllamaModelManager, "list_models", return_value=installed),
        ):
            result = ollama_mod.action_list_models(settings, {})

        self.assertEqual(result.status, "success")
        rows = result.data.get("models", [])
        by_id = {str(item.get("model_id", "")): item for item in rows if isinstance(item, dict)}
        self.assertIn("gemma2:2b:latest", by_id)
        self.assertTrue(bool(by_id["gemma2:2b:latest"].get("installed")))
        self.assertEqual(by_id["gemma2:2b:latest"].get("installed_model_id"), "gemma2:2b:latest")
        self.assertEqual(by_id["gemma2:2b:latest"].get("product_name"), "Gemma 2 2B")

    def test_ollama_list_models_includes_passport_metadata_for_installed_model(self) -> None:
        settings = {"ollama_url": "http://127.0.0.1:11434", "auto_start_server": False}
        installed = [ollama_mod.OllamaInstalledModel(name="llama3.2")]

        with (
            patch.object(
                ollama_mod.OllamaServerManager,
                "check_server",
                return_value=ollama_mod.OllamaServerStatus(running=True, url="http://127.0.0.1:11434"),
            ),
            patch.object(ollama_mod.OllamaModelManager, "list_models", return_value=installed),
        ):
            result = ollama_mod.action_list_models(settings, {})

        self.assertEqual(result.status, "success")
        rows = result.data.get("models", [])
        by_id = {str(item.get("model_id", "")): item for item in rows if isinstance(item, dict)}
        self.assertEqual(by_id["llama3.2"].get("source_url"), "https://ollama.com/library/llama3.2")
        self.assertEqual(by_id["llama3.2"].get("size_hint"), "~2GB")
        self.assertIn("Summaries", str(by_id["llama3.2"].get("highlights", "")))

    def test_ollama_catalog_includes_observed_success_models(self) -> None:
        by_id = {model.model_id: model for model in ollama_mod.load_models()}

        self.assertIn("gemma2:2b", by_id)
        self.assertIn("gemini-3-flash-preview:latest", by_id)

    def test_pipeline_worker_formats_llm_variant_failure_for_ui(self) -> None:
        text = _format_stage_error(
            "llm_processing",
            "no_real_llm_artifacts:llm.llama_cli:Qwen3-4B-Q4_K_M.gguf:llama_cli_timeout",
        )
        self.assertIn("All LLM variants fell back or failed", text)
        self.assertIn("llama_cli_timeout", text)

    def test_ollama_get_model_info_normalizes_latest_tag(self) -> None:
        manager = ollama_mod.OllamaModelManager(ollama_mod.OllamaServerManager())
        installed = [ollama_mod.OllamaInstalledModel(name="phi3:mini")]
        with patch.object(ollama_mod.OllamaModelManager, "list_models", return_value=installed):
            info = manager.get_model_info("phi3:mini:latest")
        self.assertIsNotNone(info)
        self.assertEqual(info.name, "phi3:mini")

    def test_ollama_generator_does_not_auto_pull_missing_model_by_default(self) -> None:
        server_manager = ollama_mod.OllamaServerManager()
        model_manager = ollama_mod.OllamaModelManager(server_manager)
        generator = ollama_mod.OllamaSummaryGenerator(
            server_manager=server_manager,
            model_manager=model_manager,
            model_id="phi3:mini",
            auto_pull_model=False,
        )

        with (
            patch.object(
                ollama_mod.OllamaServerManager,
                "check_server",
                return_value=ollama_mod.OllamaServerStatus(running=True, url="http://127.0.0.1:11434"),
            ),
            patch.object(ollama_mod.OllamaModelManager, "get_model_info", return_value=None),
            patch.object(ollama_mod.OllamaModelManager, "pull_model") as pull_mock,
            patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    "http://127.0.0.1:11434/api/chat",
                    404,
                    "Not Found",
                    hdrs={},
                    fp=BytesIO(b'{"error":"model not found"}'),
                ),
            ),
        ):
            summary, warnings = generator.generate_summary("hello", None)  # type: ignore[arg-type]

        pull_mock.assert_not_called()
        self.assertIn("not available", summary.lower())
        self.assertTrue(any("not listed in ollama tags" in str(item).lower() for item in warnings))

    def test_ollama_generator_rejects_model_not_listed_in_tags(self) -> None:
        server_manager = ollama_mod.OllamaServerManager()
        model_manager = ollama_mod.OllamaModelManager(server_manager)
        generator = ollama_mod.OllamaSummaryGenerator(
            server_manager=server_manager,
            model_manager=model_manager,
            model_id="qwen3-vl:235b-cloud",
            auto_pull_model=False,
        )

        class _Response:
            def read(self):
                return json.dumps({"message": {"content": "# Summary\n\nok"}}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        with (
            patch.object(
                ollama_mod.OllamaServerManager,
                "check_server",
                return_value=ollama_mod.OllamaServerStatus(running=True, url="http://127.0.0.1:11434"),
            ),
            patch.object(ollama_mod.OllamaModelManager, "get_model_info", return_value=None),
            patch.object(ollama_mod.OllamaModelManager, "pull_model") as pull_mock,
        ):
            summary, warnings = generator.generate_summary("hello", None)  # type: ignore[arg-type]

        pull_mock.assert_not_called()
        self.assertIn("not available", summary.lower())
        self.assertTrue(any("not listed in ollama tags" in str(item).lower() for item in warnings))

    def test_ollama_generator_builds_prompt_with_language_rule(self) -> None:
        server_manager = ollama_mod.OllamaServerManager()
        model_manager = ollama_mod.OllamaModelManager(server_manager)
        generator = ollama_mod.OllamaSummaryGenerator(
            server_manager=server_manager,
            model_manager=model_manager,
            model_id="phi3:mini",
            system_prompt="Summarize the meeting in markdown.",
            auto_pull_model=False,
        )

        payload_holder: dict[str, object] = {}

        class _Response:
            def read(self):
                return json.dumps({"message": {"content": "# Summary\n\nok"}}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        def _capture_request(request, timeout=None):
            payload_holder["timeout"] = timeout
            payload_holder["body"] = json.loads((request.data or b"{}").decode("utf-8"))
            return _Response()

        with (
            patch.object(
                ollama_mod.OllamaServerManager,
                "check_server",
                return_value=ollama_mod.OllamaServerStatus(running=True, url="http://127.0.0.1:11434"),
            ),
            patch.object(
                ollama_mod.OllamaModelManager,
                "get_model_info",
                return_value=ollama_mod.OllamaInstalledModel(name="phi3:mini"),
            ),
            patch("urllib.request.urlopen", side_effect=_capture_request),
        ):
            summary, warnings = generator.generate_summary("Привет мир", None)  # type: ignore[arg-type]

        self.assertEqual(summary, "# Summary\n\nok")
        self.assertEqual(warnings, [])
        body = payload_holder["body"]
        self.assertIsInstance(body, dict)
        messages = body.get("messages", []) if isinstance(body, dict) else []
        self.assertEqual(messages[1]["content"], "Summarize according to the system instructions.")
        self.assertIn("language of the transcript", messages[0]["content"])
        self.assertIn("FINAL LANGUAGE RULE", messages[0]["content"])

if __name__ == "__main__":
    unittest.main()

