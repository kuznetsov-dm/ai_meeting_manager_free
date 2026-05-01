import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestCloudModelCards(unittest.TestCase):
    def test_cloud_primary_action_prefers_model_test_for_untested_model(self) -> None:
        from aimn.ui.widgets.model_cards import ModelCardsPanel

        label, action_id, payload, tooltip = ModelCardsPanel._cloud_primary_action_spec(
            status_raw="",
            failure_code="",
            model_id="google/gemini-2.0-flash-exp:free",
            has_test_model=True,
            has_test_connection=True,
        )

        self.assertEqual(label, "Check availability")
        self.assertEqual(action_id, "test_model")
        self.assertEqual(payload, {"model_id": "google/gemini-2.0-flash-exp:free"})
        self.assertIn("availability check", tooltip.lower())

    def test_cloud_primary_action_uses_connection_check_for_auth_issue(self) -> None:
        from aimn.ui.widgets.model_cards import ModelCardsPanel

        label, action_id, payload, _tooltip = ModelCardsPanel._cloud_primary_action_spec(
            status_raw="auth_error",
            failure_code="auth_error",
            model_id="google/gemini-2.0-flash-exp:free",
            has_test_model=True,
            has_test_connection=True,
        )

        self.assertEqual(label, "Check availability")
        self.assertEqual(action_id, "test_connection")
        self.assertEqual(payload, {})

    def test_cloud_primary_action_hides_button_for_ready_model(self) -> None:
        from aimn.ui.widgets.model_cards import ModelCardsPanel

        label, action_id, payload, tooltip = ModelCardsPanel._cloud_primary_action_spec(
            status_raw="ready",
            failure_code="",
            model_id="google/gemini-2.0-flash-exp:free",
            has_test_model=True,
            has_test_connection=True,
        )

        self.assertEqual((label, action_id, payload, tooltip), ("", "", {}, ""))

    def test_cloud_entry_sort_keeps_testing_near_top(self) -> None:
        from aimn.ui.widgets.model_cards import ModelCardsPanel, ModelEntry

        ready_key = ModelCardsPanel._cloud_entry_sort_key(
            ModelEntry(model_id="m-ready", title="Ready", status_label="Ready", status_bg="", status_fg="", meta_lines=[])
        )
        testing_key = ModelCardsPanel._cloud_entry_sort_key(
            ModelEntry(
                model_id="m-testing",
                title="Testing",
                status_label="Testing...",
                status_bg="",
                status_fg="",
                meta_lines=[],
            )
        )
        needs_test_key = ModelCardsPanel._cloud_entry_sort_key(
            ModelEntry(
                model_id="m-needs",
                title="Unknown",
                status_label="Unknown",
                status_bg="",
                status_fg="",
                meta_lines=[],
            )
        )

        self.assertLess(ready_key, testing_key)
        self.assertLess(testing_key, needs_test_key)

    def test_cloud_failure_code_from_probe_message_maps_auth(self) -> None:
        from aimn.ui.widgets.model_cards import _cloud_failure_code_from_probe_message

        code = _cloud_failure_code_from_probe_message("openrouter_http_error(model=x) status=401 body=unauthorized")

        self.assertEqual(code, "auth_error")

    def test_cloud_failure_code_from_probe_message_maps_provider_block(self) -> None:
        from aimn.ui.widgets.model_cards import _cloud_failure_code_from_probe_message

        code = _cloud_failure_code_from_probe_message("Blocked by Google AI Studio")

        self.assertEqual(code, "provider_blocked")

    def test_openrouter_capacity_error_is_classified_as_rate_limited(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        code, selectable, cooldown = openrouter._classify_openrouter_error(
            'openrouter_http_error(model=qwen/test) status=403 body={"error":{"metadata":{"raw":"Venice.ai is at capacity."}}}'
        )

        self.assertEqual(code, "rate_limited")
        self.assertFalse(selectable)
        self.assertGreater(cooldown, 0)

    def test_openrouter_list_models_includes_card_metadata(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        result = openrouter.action_list_models({"models": []}, {})

        self.assertEqual(result.status, "success")
        rows = {str(item.get("model_id", "")): item for item in result.data.get("models", [])}
        self.assertIn("qwen/qwen3-next-80b-a3b-instruct:free", rows)
        self.assertIn("qwen/qwen3-coder:free", rows)
        self.assertEqual(
            rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("source_url"),
            "https://openrouter.ai/models/qwen/qwen3-next-80b-a3b-instruct:free",
        )
        self.assertIn(
            "free qwen model",
            str(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("description", "")).lower(),
        )
        self.assertIn("Cloud API", str(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("size_hint", "")))
        self.assertIn("selectable", rows["qwen/qwen3-next-80b-a3b-instruct:free"])
        self.assertEqual(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("availability_status"), "unknown")

    def test_openrouter_list_models_excludes_rate_limited_rows_from_selectable_options(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        cooldown_until = int(time.time()) + 600
        result = openrouter.action_list_models(
            {
                "models": [
                    {
                        "model_id": "qwen/qwen3-next-80b-a3b-instruct:free",
                        "product_name": "Qwen3 Next",
                        "enabled": True,
                        "status": "rate_limited",
                        "failure_code": "rate_limited",
                        "cooldown_until": cooldown_until,
                        "selectable": False,
                    }
                ]
            },
            {},
        )

        self.assertEqual(result.status, "success")
        rows = {str(item.get("model_id", "")): item for item in result.data.get("models", [])}
        self.assertFalse(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("selectable"))
        self.assertEqual(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("availability_status"), "limited")
        options = {str(item.get("value", "")) for item in result.data.get("options", [])}
        self.assertNotIn("qwen/qwen3-next-80b-a3b-instruct:free", options)

    def test_openrouter_list_models_releases_rate_limited_row_after_cooldown_expires(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        result = openrouter.action_list_models(
            {
                "models": [
                    {
                        "model_id": "qwen/qwen3-next-80b-a3b-instruct:free",
                        "product_name": "Qwen3 Next",
                        "enabled": True,
                        "status": "rate_limited",
                        "failure_code": "rate_limited",
                        "availability_status": "limited",
                        "cooldown_until": 1,
                        "selectable": False,
                    }
                ]
            },
            {},
        )

        self.assertEqual(result.status, "success")
        rows = {str(item.get("model_id", "")): item for item in result.data.get("models", [])}
        self.assertTrue(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("selectable"))
        self.assertEqual(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("availability_status"), "unknown")
        options = {str(item.get("value", "")) for item in result.data.get("options", [])}
        self.assertIn("qwen/qwen3-next-80b-a3b-instruct:free", options)

    def test_openrouter_list_models_marks_untested_rows_selectable_after_key_probe(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        with patch.object(openrouter, "_probe_openrouter_api_key", return_value=(True, "", {"models_count": 3})):
            result = openrouter.action_list_models({"api_key": "test-key", "models": []}, {})

        self.assertEqual(result.status, "success")
        rows = {str(item.get("model_id", "")): item for item in result.data.get("models", [])}
        self.assertTrue(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("selectable"))
        self.assertEqual(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("status"), "ready")
        self.assertEqual(rows["qwen/qwen3-next-80b-a3b-instruct:free"].get("availability_status"), "ready")
        options = {str(item.get("value", "")) for item in result.data.get("options", [])}
        self.assertIn("qwen/qwen3-next-80b-a3b-instruct:free", options)

    def test_openrouter_fetch_live_models_keeps_only_free_qwen_and_selected_manual_model(self) -> None:
        import json
        import plugins.llm.openrouter.openrouter as openrouter

        payload = {
            "data": [
                {"id": "qwen/qwen-3-32b:free", "name": "Qwen 3 32B Free"},
                {"id": "qwen/qwen-3-235b", "name": "Qwen 3 235B"},
                {"id": "google/gemini-2.5-flash:free", "name": "Gemini 2.5 Flash Free"},
                {"id": "anthropic/claude-3.7-sonnet", "name": "Claude 3.7 Sonnet"},
            ]
        }

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with patch.object(openrouter.urllib.request, "urlopen", return_value=_Response()):
            models = openrouter._fetch_openrouter_models(
                endpoint="https://openrouter.ai/api/v1/chat/completions",
                api_key="test-key",
                enabled_or_selected={"anthropic/claude-3.7-sonnet"},
            )

        ids = [str(item.get("model_id", "")) for item in models]
        self.assertIn("qwen/qwen-3-32b:free", ids)
        self.assertNotIn("qwen/qwen-3-235b", ids)
        self.assertNotIn("google/gemini-2.5-flash:free", ids)
        self.assertIn("anthropic/claude-3.7-sonnet", ids)

    def test_openrouter_fetch_live_models_without_manual_selection_keeps_only_free_qwen(self) -> None:
        import json
        import plugins.llm.openrouter.openrouter as openrouter

        payload = {
            "data": [
                {"id": "qwen/qwen-3-32b:free", "name": "Qwen 3 32B Free"},
                {"id": "google/gemini-2.5-flash:free", "name": "Gemini 2.5 Flash Free"},
                {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B Free"},
            ]
        }

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with patch.object(openrouter.urllib.request, "urlopen", return_value=_Response()):
            models = openrouter._fetch_openrouter_models(
                endpoint="https://openrouter.ai/api/v1/chat/completions",
                api_key="test-key",
                enabled_or_selected=set(),
            )

        ids = [str(item.get("model_id", "")) for item in models]
        self.assertEqual(ids, ["qwen/qwen-3-32b:free"])

    def test_deepseek_list_models_includes_card_metadata(self) -> None:
        import plugins.llm.deepseek.deepseek as deepseek

        result = deepseek.action_list_models({"models": []}, {})

        self.assertEqual(result.status, "success")
        rows = {str(item.get("model_id", "")): item for item in result.data.get("models", [])}
        self.assertIn("deepseek-chat", rows)
        self.assertIn("deepseek-reasoner", rows)
        self.assertIn("128k", str(rows["deepseek-chat"].get("size_hint", "")))
        self.assertIn("контекстное окно 128k", str(rows["deepseek-chat"].get("description", "")))
        self.assertIn("Chain-of-Thought", str(rows["deepseek-reasoner"].get("description", "")))
        self.assertEqual(rows["deepseek-chat"].get("source_url"), "https://api.deepseek.com")
        self.assertEqual(rows["deepseek-chat"].get("availability_status"), "unknown")

    def test_zai_list_models_includes_card_metadata(self) -> None:
        import plugins.llm.zai.zai as zai

        result = zai.action_list_models({"models": []}, {})

        self.assertEqual(result.status, "success")
        rows = {str(item.get("model_id", "")): item for item in result.data.get("models", [])}
        self.assertIn("glm-4.5-flash", rows)
        self.assertIn("glm-4.7-flash", rows)
        self.assertEqual(rows["glm-4.5-flash"].get("product_name"), "Z.ai 4.5 Flash")
        self.assertIn("Free API", str(rows["glm-4.5-flash"].get("size_hint", "")))
        self.assertIn("128k", str(rows["glm-4.5-flash"].get("description", "")))
        self.assertIn("200k+", str(rows["glm-4.7-flash"].get("description", "")))
        self.assertEqual(
            rows["glm-4.5-flash"].get("source_url"),
            "https://docs.z.ai/guides/llm/glm-4.5glm-4-5-flash",
        )
        self.assertEqual(
            rows["glm-4.7-flash"].get("source_url"),
            "https://docs.z.ai/guides/llm/glm-4.7glm-4-7-flash",
        )
        self.assertEqual(rows["glm-4.5-flash"].get("availability_status"), "unknown")

    def test_openrouter_test_model_returns_normalized_availability_status(self) -> None:
        import plugins.llm.openrouter.openrouter as openrouter

        with patch.object(
            openrouter.OpenRouterPlugin,
            "_call_openrouter",
            return_value=("", "openrouter_http_error(model=x) status=429 body=rate limit"),
        ):
            result = openrouter.action_test_model({"api_key": "k"}, {"model_id": "google/gemini-2.0-flash-exp:free"})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.data.get("failure_code"), "rate_limited")
        self.assertEqual(result.data.get("availability_status"), "limited")

    def test_deepseek_test_model_returns_normalized_availability_status(self) -> None:
        import plugins.llm.deepseek.deepseek as deepseek

        with patch.object(
            deepseek.DeepSeekPlugin,
            "_call_deepseek",
            return_value=("", "status=429 rate limit reached"),
        ):
            result = deepseek.action_test_model({"api_key": "k"}, {"model_id": "deepseek-chat"})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.data.get("failure_code"), "rate_limited")
        self.assertEqual(result.data.get("availability_status"), "limited")

    def test_zai_test_model_returns_normalized_availability_status(self) -> None:
        import plugins.llm.zai.zai as zai

        with patch.object(
            zai.ZaiPlugin,
            "_call_zai",
            return_value=("", "SSL: UNEXPECTED_EOF_WHILE_READING"),
        ):
            result = zai.action_test_model({"api_key": "k"}, {"model_id": "glm-4.7-flash"})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.data.get("failure_code"), "transport_error")
        self.assertEqual(result.data.get("availability_status"), "unavailable")


if __name__ == "__main__":
    unittest.main()

