import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestZaiModelPolicy(unittest.TestCase):
    def test_legacy_model_id_is_migrated_to_flash(self) -> None:
        import plugins.llm.zai.zai as zai

        plugin = zai.ZaiPlugin(model_id="glm-4-flash")
        self.assertEqual(plugin._resolve_model_id(), "glm-4.7-flash")

    def test_refresh_models_keeps_only_allowed_free_flash_models(self) -> None:
        import plugins.llm.zai.zai as zai

        remote_payload = [
            {"model_id": "glm-4.5-air", "product_name": "GLM 4.5 Air"},
            {"model_id": "glm-4.5-flash", "product_name": "GLM 4.5 Flash Free"},
            {"model_id": "glm-4.7-flash", "product_name": "GLM 4.7 Flash Free"},
        ]
        with mock.patch.object(zai, "_fetch_zai_models", return_value=remote_payload):
            result = zai.action_list_models(
                {
                    "models": [
                        {"model_id": "glm-4-flash", "enabled": True},
                        {"model_id": "glm-4.5-flash", "enabled": False},
                    ]
                },
                {},
            )

        self.assertEqual(result.status, "success")
        models = result.data.get("models", [])
        ids = [str(item.get("model_id", "")) for item in models]
        self.assertEqual(set(ids), {"glm-4.7-flash", "glm-4.5-flash"})
        enabled = {str(item.get("model_id", "")): bool(item.get("enabled")) for item in models}
        self.assertTrue(enabled.get("glm-4.7-flash"))

    def test_refresh_models_preserves_default_flash_models_when_remote_is_partial(self) -> None:
        import plugins.llm.zai.zai as zai

        remote_payload = [
            {"model_id": "glm-4.7-flash", "product_name": "GLM 4.7 Flash Free"},
        ]
        with mock.patch.object(zai, "_fetch_zai_models", return_value=remote_payload):
            result = zai.action_list_models(
                {
                    "models": [
                        {"model_id": "glm-4.7-flash", "enabled": True},
                        {"model_id": "glm-4.5-flash", "enabled": False},
                    ]
                },
                {},
            )

        self.assertEqual(result.status, "success")
        models = result.data.get("models", [])
        ids = [str(item.get("model_id", "")) for item in models]
        self.assertEqual(set(ids), {"glm-4.7-flash", "glm-4.5-flash"})

    def test_unsupported_model_is_rejected(self) -> None:
        import plugins.llm.zai.zai as zai

        result = zai.action_test_model({}, {"model_id": "glm-4.5-air"})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.message, "model_not_supported")

    def test_profile_mode_uses_non_empty_user_prompt(self) -> None:
        import plugins.llm.zai.zai as zai
        from aimn.plugins.api import HookContext

        plugin = zai.ZaiPlugin(api_key="k", model_id="glm-4.7-flash", prompt_profile="custom", prompt_custom="Do it")
        captured: dict[str, str] = {}

        def _fake_call(api_key: str, model_id: str, text: str, system_prompt: str | None):
            captured["text"] = text
            return "ok", ""

        with mock.patch.object(plugin, "_call_zai", side_effect=_fake_call):
            result = plugin.run(
                HookContext(
                    plugin_id="llm.zai",
                    meeting_id="m1",
                    alias=None,
                    input_text="transcript text",
                    plugin_config={},
                )
            )

        self.assertEqual(result.outputs[0].content, "ok")
        self.assertTrue(str(captured.get("text", "")).strip())

    def test_call_zai_retries_once_after_timeout(self) -> None:
        import plugins.llm.zai.zai as zai

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._data = BytesIO(zai.json.dumps(payload).encode("utf-8"))

            def read(self, size: int | None = None) -> bytes:
                return self._data.read() if size is None else self._data.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        plugin = zai.ZaiPlugin(api_key="k", model_id="glm-4.7-flash", timeout_seconds=5)
        calls = {"count": 0}

        def _flaky_urlopen(*_args, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("The read operation timed out")
            return _JsonResponse({"choices": [{"message": {"content": "ok"}}]})

        with mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", side_effect=_flaky_urlopen):
            with mock.patch("plugins.llm.zai.zai.time.sleep", return_value=None):
                content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(content, "ok")
        self.assertEqual(error, "")
        self.assertEqual(calls["count"], 2)

    def test_call_zai_sends_non_stream_payload(self) -> None:
        import plugins.llm.zai.zai as zai

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._raw = BytesIO(zai.json.dumps(payload).encode("utf-8"))

            def read(self, size: int | None = None) -> bytes:
                return self._raw.read() if size is None else self._raw.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        plugin = zai.ZaiPlugin(api_key="k", model_id="glm-4.7-flash", timeout_seconds=5)
        captured: dict = {}

        def _capture_request(request, timeout=0):  # noqa: ARG001
            captured.update(zai.json.loads((request.data or b"{}").decode("utf-8")))
            return _JsonResponse({"choices": [{"message": {"content": "ok"}}]})

        with mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", side_effect=_capture_request):
            content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(error, "")
        self.assertEqual(content, "ok")
        self.assertIn("stream", captured)
        self.assertIs(captured.get("stream"), False)

    def test_call_zai_uses_raw_text_when_postprocess_returns_empty(self) -> None:
        import plugins.llm.zai.zai as zai

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._raw = BytesIO(zai.json.dumps(payload).encode("utf-8"))

            def read(self, size: int | None = None) -> bytes:
                return self._raw.read() if size is None else self._raw.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        plugin = zai.ZaiPlugin(api_key="k", model_id="glm-4.7-flash", timeout_seconds=5)
        payload = {"choices": [{"message": {"content": "raw model text"}}]}
        with (
            mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", return_value=_JsonResponse(payload)),
            mock.patch("plugins.llm.zai.zai._postprocess_summary_text", return_value=""),
        ):
            content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(error, "")
        self.assertEqual(content, "raw model text")

    def test_call_zai_retries_with_disable_thinking_on_length_empty(self) -> None:
        import plugins.llm.zai.zai as zai

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._raw = BytesIO(zai.json.dumps(payload).encode("utf-8"))

            def read(self, size: int | None = None) -> bytes:
                return self._raw.read() if size is None else self._raw.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        plugin = zai.ZaiPlugin(api_key="k", model_id="glm-4.7-flash", timeout_seconds=5)
        requests: list[dict] = []

        def _fake_urlopen(request, timeout=0):  # noqa: ARG001
            payload = zai.json.loads((request.data or b"{}").decode("utf-8"))
            requests.append(payload)
            if payload.get("clear_thinking") is True:
                return _JsonResponse({"choices": [{"message": {"content": "final answer"}}]})
            return _JsonResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": "", "reasoning_content": ""},
                        }
                    ]
                }
            )

        with mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", side_effect=_fake_urlopen):
            content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(error, "")
        self.assertEqual(content, "final answer")
        self.assertEqual(len(requests), 3)
        self.assertFalse(bool(requests[0].get("clear_thinking", False)))
        self.assertFalse(bool(requests[1].get("clear_thinking", False)))
        self.assertEqual(int(requests[1].get("max_tokens", 0)), 8192)
        self.assertTrue(bool(requests[2].get("clear_thinking", False)))
        self.assertEqual(requests[2].get("thinking", {}).get("type"), "disabled")

    def test_call_zai_treats_short_length_finish_reason_as_retryable(self) -> None:
        import plugins.llm.zai.zai as zai

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._raw = BytesIO(zai.json.dumps(payload).encode("utf-8"))

            def read(self, size: int | None = None) -> bytes:
                return self._raw.read() if size is None else self._raw.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        plugin = zai.ZaiPlugin(api_key="k", model_id="glm-4.7-flash", timeout_seconds=5)
        requests: list[dict] = []

        def _fake_urlopen(request, timeout=0):  # noqa: ARG001
            payload = zai.json.loads((request.data or b"{}").decode("utf-8"))
            requests.append(payload)
            if len(requests) == 1:
                return _JsonResponse(
                    {
                        "choices": [
                            {
                                "finish_reason": "le",
                                "message": {"content": "", "reasoning_content": ""},
                            }
                        ]
                    }
                )
            return _JsonResponse({"choices": [{"message": {"content": "final answer"}}]})

        with mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", side_effect=_fake_urlopen):
            content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(error, "")
        self.assertEqual(content, "final answer")
        self.assertEqual(len(requests), 2)

    def test_call_zai_switches_endpoint_to_coding_on_404(self) -> None:
        import plugins.llm.zai.zai as zai

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._raw = BytesIO(zai.json.dumps(payload).encode("utf-8"))

            def read(self, size: int | None = None) -> bytes:
                return self._raw.read() if size is None else self._raw.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        plugin = zai.ZaiPlugin(
            api_key="k",
            model_id="glm-4.7-flash",
            endpoint="https://api.z.ai/api/paas/v4/chat/completions",
            timeout_seconds=5,
        )
        urls: list[str] = []

        def _fake_urlopen(request, timeout=0):  # noqa: ARG001
            url = str(getattr(request, "full_url", ""))
            urls.append(url)
            if "/api/coding/paas/v4/chat/completions" not in url:
                raise HTTPError(url, 404, "Not Found", None, BytesIO(b'{"error":"not found"}'))
            return _JsonResponse({"choices": [{"message": {"content": "ok"}}]})

        with mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", side_effect=_fake_urlopen):
            content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(error, "")
        self.assertEqual(content, "ok")
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].endswith("/api/paas/v4/chat/completions"))
        self.assertTrue(urls[1].endswith("/api/coding/paas/v4/chat/completions"))

    def test_call_zai_switches_endpoint_to_paas_on_404(self) -> None:
        import plugins.llm.zai.zai as zai

        class _JsonResponse:
            def __init__(self, payload: dict) -> None:
                self._raw = BytesIO(zai.json.dumps(payload).encode("utf-8"))

            def read(self, size: int | None = None) -> bytes:
                return self._raw.read() if size is None else self._raw.read(size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        plugin = zai.ZaiPlugin(
            api_key="k",
            model_id="glm-4.7-flash",
            endpoint="https://api.z.ai/api/coding/paas/v4/chat/completions",
            timeout_seconds=5,
        )
        urls: list[str] = []

        def _fake_urlopen(request, timeout=0):  # noqa: ARG001
            url = str(getattr(request, "full_url", ""))
            urls.append(url)
            if "/api/coding/paas/v4/chat/completions" in url:
                raise HTTPError(url, 404, "Not Found", None, BytesIO(b'{"error":"not found"}'))
            return _JsonResponse({"choices": [{"message": {"content": "ok"}}]})

        with mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", side_effect=_fake_urlopen):
            content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(error, "")
        self.assertEqual(content, "ok")
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].endswith("/api/coding/paas/v4/chat/completions"))
        self.assertTrue(urls[1].endswith("/api/paas/v4/chat/completions"))

    def test_call_zai_does_not_switch_endpoint_on_401(self) -> None:
        import plugins.llm.zai.zai as zai

        plugin = zai.ZaiPlugin(
            api_key="k",
            model_id="glm-4.7-flash",
            endpoint="https://api.z.ai/api/paas/v4/chat/completions",
            timeout_seconds=5,
        )
        calls = {"count": 0}

        def _fake_urlopen(request, timeout=0):  # noqa: ARG001
            calls["count"] += 1
            url = str(getattr(request, "full_url", ""))
            raise HTTPError(url, 401, "Unauthorized", None, BytesIO(b'{"error":{"code":10001004}}'))

        with mock.patch("plugins.llm.zai.zai.urllib.request.urlopen", side_effect=_fake_urlopen):
            content, error = plugin._call_zai("k", "glm-4.7-flash", "ping", "")

        self.assertEqual(content, "")
        self.assertIn("status=401", error)
        self.assertEqual(calls["count"], 1)

    def test_extract_message_text_ignores_reasoning_content_without_final_answer(self) -> None:
        import plugins.llm.zai.zai as zai

        payload = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning_content": "Reasoning answer"},
                }
            ]
        }

        text = zai._extract_message_text(payload)
        self.assertEqual(text, "")

    def test_extract_message_text_prefers_non_reasoning_block_from_content_list(self) -> None:
        import plugins.llm.zai.zai as zai

        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "reasoning", "text": "1. **Analyze the Request:** ..."},
                            {"type": "output_text", "text": "### Meeting topic\nПолезный итог"},
                        ]
                    }
                }
            ]
        }

        text = zai._extract_message_text(payload)
        self.assertIn("### Meeting topic", text)
        self.assertIn("Полезный итог", text)
        self.assertNotIn("Analyze the Request", text)

    def test_extract_message_text_ignores_reasoning_blocks_when_no_final_block(self) -> None:
        import plugins.llm.zai.zai as zai

        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "reasoning", "text": "1. **Analyze the Request:** ..."},
                            {"type": "thinking", "reasoning_content": "2. **Analyze the Transcript:** ..."},
                        ]
                    }
                }
            ]
        }

        text = zai._extract_message_text(payload)
        self.assertEqual(text, "")

    def test_extract_message_text_parses_json_string_to_markdown(self) -> None:
        import plugins.llm.zai.zai as zai

        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"title":"Meeting","summary":"Short summary","action_items":["A","B"]}'
                    }
                }
            ]
        }

        text = zai._extract_message_text(payload)
        self.assertIn("# Meeting", text)
        self.assertIn("Short summary", text)
        self.assertIn("- A", text)

    def test_extract_message_text_reads_nested_parts_blocks(self) -> None:
        import plugins.llm.zai.zai as zai

        payload = {
            "choices": [
                {
                    "message": {
                        "content": {
                            "parts": [
                                {"type": "reasoning", "text": "hidden"},
                                {"type": "output_text", "text": "Useful answer"},
                            ]
                        }
                    }
                }
            ]
        }

        text = zai._extract_message_text(payload)
        self.assertEqual(text, "Useful answer")

    def test_postprocess_summary_text_strips_reasoning_preamble(self) -> None:
        import plugins.llm.zai.zai as zai

        raw = "\n".join(
            [
                "1. **Analyze the Request:**",
                "2. **Analyze the Transcript:**",
                "### Meeting topic",
                "Portal rollout",
                "### Key decisions / outcomes",
                "- Add validation",
            ]
        )

        cleaned = zai._postprocess_summary_text(raw)
        self.assertTrue(cleaned.startswith("### Meeting topic"))
        self.assertNotIn("Analyze the Request", cleaned)

    def test_postprocess_summary_text_keeps_non_empty_analysis_outline(self) -> None:
        import plugins.llm.zai.zai as zai

        raw = "\n".join(
            [
                "1. **Analyze the Request:**",
                "   * Input: transcript",
                "2. **Analyze the Transcript:**",
                "   * Context: test flow",
                "3. **Drafting the Summary (Iterative Process):**",
                "   * Meeting Topic: TBD",
            ]
        )

        cleaned = zai._postprocess_summary_text(raw)
        self.assertTrue(str(cleaned).strip())
        self.assertIn("Analyze the Request", cleaned)

    def test_json_text_to_markdown_prefers_final_field(self) -> None:
        import plugins.llm.zai.zai as zai

        text = zai._json_text_to_markdown(
            '{"final":"### Meeting topic\\nPortal\\n\\n### Brief meeting summary\\nDone"}'
        )
        self.assertIn("### Meeting topic", text)
        self.assertIn("Portal", text)

    def test_fallback_diagnostics_recognizes_invalid_key_code(self) -> None:
        import plugins.llm.zai.zai as zai

        title, reason, _detail, _steps = zai.ZaiPlugin._fallback_diagnostics(
            ['zai_http_error(model=glm-4.7-flash) status=401 body={"error":{"code":10001004}}']
        )
        self.assertIn("authorization", title.lower())
        self.assertIn("invalid", reason.lower())


if __name__ == "__main__":
    unittest.main()

