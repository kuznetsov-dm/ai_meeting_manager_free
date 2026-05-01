import os
import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_manager import PluginManager  # noqa: E402
from aimn.core.plugins_config import PluginsConfig  # noqa: E402


def _live_enabled() -> bool:
    return str(os.getenv("AIMN_LIVE_TESTS", "")).strip().lower() in {"1", "true", "yes", "on"}


class TestAiPluginsLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not _live_enabled():
            raise unittest.SkipTest("Set AIMN_LIVE_TESTS=1 to run live AI plugin tests.")
        cls.plugin_manager = PluginManager(
            repo_root,
            PluginsConfig(
                {
                    "enabled": [
                        "llm.openrouter",
                        "llm.zai",
                        "llm.deepseek",
                        "llm.ollama",
                    ]
                }
            ),
        )
        cls.plugin_manager.load()

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "plugin_manager", None):
            cls.plugin_manager.shutdown()

    def _settings(self, plugin_id: str) -> dict:
        return self.plugin_manager.get_settings(plugin_id, include_secrets=True)

    def test_openrouter_free_model(self) -> None:
        settings = self._settings("llm.openrouter")
        if not str(settings.get("api_key", "")).strip():
            self.skipTest("OpenRouter key missing in secrets.toml/env")

        models = self.plugin_manager.invoke_action("llm.openrouter", "list_models", {})
        self.assertEqual(models.status, "success", models.message)
        raw = (models.data or {}).get("models")
        self.assertIsInstance(raw, list)

        free = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            mid = str(entry.get("model_id", "")).strip()
            if mid.endswith(":free"):
                free.append(entry)
        if not free:
            self.skipTest("No :free models returned by llm.openrouter list_models")

        enabled = [m for m in free if bool(m.get("enabled"))]
        candidate = enabled[0] if enabled else free[0]
        model_id = str(candidate.get("model_id", "")).strip()
        self.assertTrue(model_id.endswith(":free"), f"expected free OpenRouter model, got {model_id!r}")

        override = dict(settings)
        override["model_id"] = model_id
        result = self.plugin_manager.invoke_action(
            "llm.openrouter",
            "test_model",
            {"model_id": model_id},
            settings_override=override,
        )
        self.assertEqual(result.status, "success", result.message)

    def test_zai_model(self) -> None:
        settings = self._settings("llm.zai")
        if not str(settings.get("api_key", "")).strip():
            self.skipTest("Z.ai key missing in secrets.toml/env")

        models = self.plugin_manager.invoke_action("llm.zai", "list_models", {})
        self.assertEqual(models.status, "success", models.message)
        raw = (models.data or {}).get("models")
        self.assertIsInstance(raw, list)
        if not raw:
            self.skipTest("No models returned by llm.zai list_models")

        enabled = [m for m in raw if isinstance(m, dict) and bool(m.get("enabled"))]
        candidate = enabled[0] if enabled else next((m for m in raw if isinstance(m, dict)), None)
        if not candidate:
            self.skipTest("No usable models returned by llm.zai list_models")

        model_id = str(candidate.get("model_id", "")).strip()
        self.assertTrue(model_id)

        override = dict(settings)
        override["model_id"] = model_id
        connection = self.plugin_manager.invoke_action(
            "llm.zai", "test_connection", {}, settings_override=override
        )
        self.assertEqual(connection.status, "success", connection.message)

        result = self.plugin_manager.invoke_action(
            "llm.zai", "test_model", {"model_id": model_id}, settings_override=override
        )
        self.assertEqual(result.status, "success", result.message)

    def test_deepseek_connection(self) -> None:
        settings = self._settings("llm.deepseek")
        if not str(settings.get("api_key", "")).strip():
            self.skipTest("DeepSeek key missing in secrets.toml/env")
        result = self.plugin_manager.invoke_action("llm.deepseek", "test_connection", {})
        self.assertEqual(result.status, "success", result.message)

    def test_ollama_installed_models(self) -> None:
        connection = self.plugin_manager.invoke_action("llm.ollama", "test_connection", {})
        if connection.status != "success":
            self.skipTest(f"Ollama not reachable: {connection.message}")

        models = self.plugin_manager.invoke_action("llm.ollama", "list_models", {})
        self.assertEqual(models.status, "success", models.message)
        raw = (models.data or {}).get("models")
        self.assertIsInstance(raw, list)
        if not raw:
            self.skipTest("No installed Ollama models to test")
        installed = [
            m
            for m in raw
            if isinstance(m, dict)
            and bool(m.get("installed"))
            and str(m.get("model_id", "")).strip()
        ]
        first = installed[0] if installed else next(
            (m for m in raw if isinstance(m, dict) and str(m.get("model_id", "")).strip()),
            None,
        )
        if not first:
            self.skipTest("No valid installed Ollama model entries")
        model_id = str(first.get("model_id", "")).strip()

        result = self.plugin_manager.invoke_action("llm.ollama", "test_model", {"model_id": model_id})
        self.assertEqual(result.status, "success", result.message)


if __name__ == "__main__":
    unittest.main()
