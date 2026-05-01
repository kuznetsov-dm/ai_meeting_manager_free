import sys
import unittest
from pathlib import Path
from unittest import mock

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestLlmFallbackMessages(unittest.TestCase):
    def test_openrouter_fallback_shows_http_429_reason(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        result = openrouter.OpenRouterPlugin._mock_result(
            [
                "openrouter_http_error(model=meta-llama/llama-3.3-70b-instruct:free) status=429 body=rate_limited",
                "openrouter_request_failed",
            ]
        )
        text = result.outputs[0].content.lower()
        self.assertIn("429", text)
        self.assertIn("rate limit", text)

    def test_openrouter_fallback_handles_detailed_empty_warning(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        result = openrouter.OpenRouterPlugin._mock_result(
            [
                "openrouter_empty_response details={\"choices_count\":1}",
                "openrouter_request_failed",
            ]
        )
        text = result.outputs[0].content.lower()
        self.assertIn("empty response", text)
        self.assertIn("detail:", text)

    def test_zai_fallback_shows_http_400_detail(self) -> None:
        import plugins.llm.zai.zai as zai

        result = zai.ZaiPlugin._mock_result(
            [
                "zai_http_error(model=glm-4.7-flash) status=400 body={\"error\":{\"code\":\"1213\"}}",
            ]
        )
        text = result.outputs[0].content.lower()
        self.assertIn("reason:", text)
        self.assertIn("400", text)
        self.assertIn("bad request", text)
        self.assertIn("detail:", text)

    def test_zai_fallback_handles_detailed_empty_warning(self) -> None:
        import plugins.llm.zai.zai as zai

        result = zai.ZaiPlugin._mock_result(
            [
                "zai_empty_response details={\"choices_count\":1}",
            ]
        )
        text = result.outputs[0].content.lower()
        self.assertIn("empty response", text)
        self.assertIn("detail:", text)

    def test_llama_cli_fallback_contains_actionable_reason(self) -> None:
        import plugins.llm.llama_cli.llama_cli as llama_cli

        text = llama_cli.LlamaCliPlugin._fallback_summary_text(["llama_cli_model_missing"])
        self.assertIn("Reason:", text)
        self.assertIn("model path/model id is not configured", text)

    def test_openrouter_profile_mode_uses_non_empty_user_prompt(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter
        from aimn.plugins.api import HookContext

        plugin = openrouter.OpenRouterPlugin(
            api_key="k",
            model_id="meta-llama/llama-3.3-70b-instruct:free",
            prompt_profile="custom",
            prompt_custom="Do it",
        )
        captured: dict[str, str] = {}

        def _fake_call(api_key: str, model_id: str, text: str, system_prompt: str | None):
            captured["text"] = text
            return "ok", ""

        with mock.patch.object(plugin, "_call_openrouter", side_effect=_fake_call):
            result = plugin.run(
                HookContext(
                    plugin_id="llm.openrouter",
                    meeting_id="m1",
                    alias=None,
                    input_text="transcript text",
                    plugin_config={},
                )
            )
        self.assertEqual(result.outputs[0].content, "ok")
        self.assertTrue(str(captured.get("text", "")).strip())

    def test_deepseek_profile_mode_uses_non_empty_user_prompt(self) -> None:
        import plugins.llm.deepseek.deepseek as deepseek
        from aimn.plugins.api import HookContext

        plugin = deepseek.DeepSeekPlugin(
            api_key="k",
            model_id="deepseek-chat",
            prompt_profile="custom",
            prompt_custom="Do it",
        )
        captured: dict[str, str] = {}

        def _fake_call(api_key: str, model_id: str, text: str, system_prompt: str | None):
            captured["text"] = text
            return "ok", ""

        with mock.patch.object(plugin, "_call_deepseek", side_effect=_fake_call):
            result = plugin.run(
                HookContext(
                    plugin_id="llm.deepseek",
                    meeting_id="m1",
                    alias=None,
                    input_text="transcript text",
                    plugin_config={},
                )
            )
        self.assertEqual(result.outputs[0].content, "ok")
        self.assertTrue(str(captured.get("text", "")).strip())

    def test_openrouter_without_profile_uses_default_standard_prompt(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        plugin = openrouter.OpenRouterPlugin(
            api_key="k",
            model_id="meta-llama/llama-3.3-70b-instruct:free",
            prompt_profile="",
            prompt_custom="",
        )
        rendered = plugin._resolve_prompt("transcript text")
        self.assertIn("SYSTEM INSTRUCTIONS", rendered)
        self.assertIn("REQUEST BODY:", rendered)

    def test_openrouter_refine_prompt_action_refines_existing_text(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        captured: dict[str, str] = {}

        class _FakePlugin:
            def _resolve_api_key(self):
                return "k", "ok"

            def _resolve_model_id(self):
                return "meta-llama/llama-3.3-70b-instruct:free"

            def _call_openrouter(self, api_key: str, model_id: str, text: str, system_prompt: str | None):
                captured["text"] = text
                captured["system"] = str(system_prompt or "")
                return "```text\nRefined prompt body\n```", ""

        with mock.patch.object(openrouter, "_plugin_from_settings", return_value=_FakePlugin()):
            result = openrouter.action_refine_prompt({}, {"prompt_text": "My custom prompt"})
        self.assertEqual(str(getattr(result, "status", "")), "success")
        data = getattr(result, "data", {}) if result is not None else {}
        self.assertEqual(str(data.get("prompt", "")), "Refined prompt body")
        self.assertIn("My custom prompt", captured.get("text", ""))
        self.assertIn("prompt engineer", captured.get("system", "").lower())

    def test_deepseek_refine_prompt_action_requires_prompt_text(self) -> None:
        import plugins.llm.deepseek.deepseek as deepseek

        result = deepseek.action_refine_prompt({}, {"prompt_text": ""})
        self.assertEqual(str(getattr(result, "status", "")), "error")
        self.assertEqual(str(getattr(result, "message", "")), "prompt_text_missing")


if __name__ == "__main__":
    unittest.main()

