import sys
import tempfile
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from plugins.llm.deepseek import deepseek as deepseek_mod  # noqa: E402
from plugins.llm.llama_cli import llama_cli as llama_mod  # noqa: E402
from plugins.llm.openrouter import openrouter as openrouter_mod  # noqa: E402


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._data = BytesIO(openrouter_mod.json.dumps(payload).encode("utf-8"))
        self.headers = {}

    def read(self, size: int | None = None) -> bytes:
        return self._data.read() if size is None else self._data.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _StreamResponse:
    def __init__(self, payload: bytes, total_size: int | None = None) -> None:
        self._data = BytesIO(payload)
        self.headers = {"Content-Length": str(total_size or len(payload))}

    def read(self, size: int | None = None) -> bytes:
        return self._data.read() if size is None else self._data.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestPluginActions(unittest.TestCase):
    def test_openrouter_actions(self) -> None:
        settings = {"api_key": "test-key", "model_id": "model-a"}

        def _urlopen(request, timeout=None):
            url = getattr(request, "full_url", str(request))
            if url.endswith("/models"):
                return _JsonResponse({"data": [{"id": "model-a"}]})
            return _JsonResponse({"choices": [{"message": {"content": "ok"}}]})

        with patch("plugins.llm.openrouter.openrouter.urllib.request.urlopen", _urlopen):
            connection = openrouter_mod.action_test_connection(settings, {})
            self.assertEqual(connection.status, "success")
            model_check = openrouter_mod.action_test_model(settings, {"model_id": "model-a"})
            self.assertEqual(model_check.status, "success")

        models = openrouter_mod.action_list_models(settings, {})
        self.assertEqual(models.status, "success")
        self.assertTrue(models.data and models.data.get("models"))

    def test_deepseek_test_connection(self) -> None:
        settings = {"api_key": "test-key", "model_id": "deepseek-chat"}

        def _urlopen(_request, timeout=None):
            return _JsonResponse({"choices": [{"message": {"content": "ok"}}]})

        with patch("plugins.llm.deepseek.deepseek.urllib.request.urlopen", _urlopen):
            result = deepseek_mod.action_test_connection(settings, {})
            self.assertEqual(result.status, "success")

    def test_llama_cli_download_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {"cache_dir": temp_dir}

            def _urlopen(request, timeout=None):
                url = getattr(request, "full_url", str(request))
                if "api/models" in url:
                    payload = {"siblings": [{"rfilename": "model.Q4_K_M.gguf"}]}
                    return _JsonResponse(payload)
                return _StreamResponse(b"data", total_size=4)

            with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen):
                result = llama_mod.action_download_model(settings, {"model_id": "org/model", "quant": "Q4_K_M"})
                self.assertEqual(result.status, "accepted")
                job_id = result.job_id
                self.assertTrue(job_id)

                status = None
                for _ in range(50):
                    status = llama_mod._get_job_status(job_id)
                    current = None
                    if isinstance(status, dict):
                        current = status.get("status")
                    elif status:
                        current = status.status
                    if current in {"success", "error"}:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(status)
                if isinstance(status, dict):
                    self.assertEqual(status.get("status"), "success")
                else:
                    self.assertEqual(status.status, "success")

                model_file = Path(temp_dir) / "model.Q4_K_M.gguf"
                self.assertTrue(model_file.exists())

                removed = llama_mod.action_remove_model(
                    settings, {"model_id": "org/model", "quant": "Q4_K_M", "file": "model.Q4_K_M.gguf"}
                )
                self.assertEqual(removed.status, "success")
                self.assertFalse(model_file.exists())

    def test_llama_cli_download_job_supports_direct_download_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {
                "cache_dir": temp_dir,
                "models": [
                    {
                        "model_id": "custom/direct-model",
                        "product_name": "Direct Model",
                        "quant": "Q4_K_M",
                        "file": "direct-model.Q4_K_M.gguf",
                        "download_url": "https://example.test/direct-model.Q4_K_M.gguf",
                        "enabled": True,
                    }
                ],
            }

            def _urlopen(request, timeout=None):
                url = getattr(request, "full_url", str(request))
                self.assertEqual(url, "https://example.test/direct-model.Q4_K_M.gguf")
                return _StreamResponse(b"direct", total_size=6)

            with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen):
                result = llama_mod.action_download_model(settings, {"model_id": "custom/direct-model", "quant": "Q4_K_M"})
                self.assertEqual(result.status, "accepted")
                job_id = result.job_id
                self.assertTrue(job_id)

                status = None
                for _ in range(50):
                    status = llama_mod._get_job_status(job_id)
                    current = None
                    if isinstance(status, dict):
                        current = status.get("status")
                    elif status:
                        current = status.status
                    if current in {"success", "error"}:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(status)
                if isinstance(status, dict):
                    self.assertEqual(status.get("status"), "success")
                else:
                    self.assertEqual(status.status, "success")

                model_file = Path(temp_dir) / "direct-model.Q4_K_M.gguf"
                self.assertTrue(model_file.exists())

    def test_llama_cli_download_job_sends_hf_auth_header_for_direct_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {
                "cache_dir": temp_dir,
                "hf_token": "hf_test_token",
                "models": [
                    {
                        "model_id": "meta-llama/Llama-4-1.5B-Instruct-GGUF",
                        "product_name": "Llama 4 1.5B",
                        "quant": "Q4_K_M",
                        "file": "llama-4-1.5b-instruct-q4_k_m.gguf",
                        "download_url": (
                            "https://huggingface.co/meta-llama/Llama-4-1.5B-Instruct-GGUF/resolve/main/"
                            "llama-4-1.5b-instruct-q4_k_m.gguf"
                        ),
                        "enabled": True,
                    }
                ],
            }

            def _urlopen(request, timeout=None):
                self.assertEqual(
                    getattr(request, "full_url", ""),
                    (
                        "https://huggingface.co/meta-llama/Llama-4-1.5B-Instruct-GGUF/resolve/main/"
                        "llama-4-1.5b-instruct-q4_k_m.gguf"
                    ),
                )
                self.assertEqual(request.get_header("Authorization"), "Bearer hf_test_token")
                return _StreamResponse(b"gated", total_size=5)

            with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen):
                result = llama_mod.action_download_model(
                    settings, {"model_id": "meta-llama/Llama-4-1.5B-Instruct-GGUF", "quant": "Q4_K_M"}
                )
                self.assertEqual(result.status, "accepted")
                job_id = result.job_id
                self.assertTrue(job_id)

                status = None
                for _ in range(50):
                    status = llama_mod._get_job_status(job_id)
                    current = None
                    if isinstance(status, dict):
                        current = status.get("status")
                    elif status:
                        current = status.status
                    if current in {"success", "error"}:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(status)
                if isinstance(status, dict):
                    self.assertEqual(status.get("status"), "success")
                else:
                    self.assertEqual(status.status, "success")

                model_file = Path(temp_dir) / "llama-4-1.5b-instruct-q4_k_m.gguf"
                self.assertTrue(model_file.exists())

    def test_llama_cli_download_job_uses_partial_file_until_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {
                "cache_dir": temp_dir,
                "models": [
                    {
                        "model_id": "alpacapilot/Phi-4-mini-instruct-Q4_K_M-GGUF",
                        "product_name": "Phi-4 Mini Instruct (GGUF)",
                        "quant": "Q4_K_M",
                        "file": "phi-4-mini-instruct-q4_k_m.gguf",
                        "download_url": (
                            "https://huggingface.co/alpacapilot/Phi-4-mini-instruct-Q4_K_M-GGUF/resolve/main/"
                            "phi-4-mini-instruct-q4_k_m.gguf"
                        ),
                        "enabled": True,
                    }
                ],
            }
            second_read_started = threading.Event()
            allow_finish = threading.Event()

            class _SlowStreamResponse:
                def __init__(self) -> None:
                    self.headers = {"Content-Length": "8"}
                    self._reads = 0

                def read(self, size: int | None = None) -> bytes:
                    self._reads += 1
                    if self._reads == 1:
                        return b"data"
                    if self._reads == 2:
                        second_read_started.set()
                        allow_finish.wait(timeout=2)
                        return b"more"
                    return b""

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def _urlopen(request, timeout=None):
                url = getattr(request, "full_url", str(request))
                self.assertEqual(
                    url,
                    (
                        "https://huggingface.co/alpacapilot/Phi-4-mini-instruct-Q4_K_M-GGUF/resolve/main/"
                        "phi-4-mini-instruct-q4_k_m.gguf"
                    ),
                )
                return _SlowStreamResponse()

            with patch("plugins.llm.llama_cli.llama_cli.urllib.request.urlopen", _urlopen):
                result = llama_mod.action_download_model(
                    settings,
                    {"model_id": "alpacapilot/Phi-4-mini-instruct-Q4_K_M-GGUF", "quant": "Q4_K_M"},
                )
                self.assertEqual(result.status, "accepted")
                job_id = result.job_id
                self.assertTrue(job_id)
                self.assertTrue(second_read_started.wait(timeout=1))

                partial_file = Path(temp_dir) / "phi-4-mini-instruct-q4_k_m.gguf.part"
                final_file = Path(temp_dir) / "phi-4-mini-instruct-q4_k_m.gguf"
                self.assertTrue(partial_file.exists())
                self.assertFalse(final_file.exists())

                listed = llama_mod.action_list_models(settings, {})
                rows = listed.data.get("models", []) if isinstance(listed.data, dict) else []
                by_id = {str(item.get("model_id", "")): item for item in rows if isinstance(item, dict)}
                self.assertFalse(by_id["alpacapilot/Phi-4-mini-instruct-Q4_K_M-GGUF"]["installed"])

                allow_finish.set()

                status = None
                for _ in range(50):
                    status = llama_mod._get_job_status(job_id)
                    current = None
                    if isinstance(status, dict):
                        current = status.get("status")
                    elif status:
                        current = status.status
                    if current in {"success", "error"}:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(status)
                if isinstance(status, dict):
                    self.assertEqual(status.get("status"), "success")
                else:
                    self.assertEqual(status.status, "success")
                self.assertTrue(final_file.exists())
                self.assertFalse(partial_file.exists())


if __name__ == "__main__":
    unittest.main()

