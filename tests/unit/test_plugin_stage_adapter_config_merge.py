import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.plugins_config import PluginsConfig  # noqa: E402
from aimn.core.stages.base import PluginStageAdapter  # noqa: E402


class _AdapterForTest(PluginStageAdapter):
    def run(self, context):  # pragma: no cover
        raise NotImplementedError


class TestPluginStageAdapterConfigMerge(unittest.TestCase):
    def test_plugin_config_overrides_plugin_settings_but_stage_params_win(self) -> None:
        adapter = _AdapterForTest(
            stage_id="llm_processing",
            policy=SimpleNamespace(stage_id="llm_processing"),
            config=PluginsConfig(
                {
                    "plugin_config": {
                        "llm.llama_cli": {
                            "timeout_seconds": 300,
                            "api_key": "",
                        }
                    }
                }
            ),
        )
        plugin_manager = SimpleNamespace(
            get_settings=lambda _plugin_id, include_secrets=False: {"timeout_seconds": 120, "api_key": ""},
            get_settings_with_secrets=lambda _plugin_id: {"timeout_seconds": 120, "api_key": "secret-token"},
        )
        context = SimpleNamespace(plugin_manager=plugin_manager)

        public_params, run_params = adapter._resolve_plugin_params(
            context,
            "llm.llama_cli",
            {"timeout_seconds": 450, "binary_path": "bin/llama/llama-cli", "api_key": ""},
        )

        self.assertEqual(public_params["timeout_seconds"], 450)
        self.assertEqual(public_params["binary_path"], "bin/llama/llama-cli")
        self.assertEqual(run_params["timeout_seconds"], 450)
        self.assertEqual(run_params["api_key"], "secret-token")

    def test_plugin_config_is_used_when_stage_params_do_not_override(self) -> None:
        adapter = _AdapterForTest(
            stage_id="llm_processing",
            policy=SimpleNamespace(stage_id="llm_processing"),
            config=PluginsConfig({"plugin_config": {"llm.llama_cli": {"timeout_seconds": 300}}}),
        )
        plugin_manager = SimpleNamespace(
            get_settings=lambda _plugin_id, include_secrets=False: {"timeout_seconds": 120},
            get_settings_with_secrets=lambda _plugin_id: {"timeout_seconds": 120},
        )
        context = SimpleNamespace(plugin_manager=plugin_manager)

        public_params, run_params = adapter._resolve_plugin_params(context, "llm.llama_cli", {"model_id": "qwen"})

        self.assertEqual(public_params["timeout_seconds"], 300)
        self.assertEqual(run_params["timeout_seconds"], 300)
        self.assertEqual(public_params["model_id"], "qwen")

    def test_stable_fingerprint_ignores_runtime_model_inventory_fields(self) -> None:
        params = {
            "model_id": "Qwen/Qwen3-1.7B-GGUF",
            "temperature": 0.2,
            "hidden_model_ids": ["unsloth/Qwen3-0.6B-GGUF", "Qwen/Qwen3-1.7B-GGUF"],
            "hidden_model_files": ["Qwen3-0.6B-Q4_K_M.gguf", "Qwen3-1.7B-Q8_0.gguf"],
            "models": [{"id": "Qwen/Qwen3-1.7B-GGUF"}],
        }

        stable = _AdapterForTest._stable_fingerprint_params(params)

        self.assertEqual(
            stable,
            {
                "model_id": "Qwen/Qwen3-1.7B-GGUF",
                "temperature": 0.2,
            },
        )


if __name__ == "__main__":
    unittest.main()
