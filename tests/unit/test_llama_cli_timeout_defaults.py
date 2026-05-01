import json
import sys
import tomllib
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from plugins.llm.llama_cli.llama_cli import _DEFAULT_TIMEOUT_SECONDS  # noqa: E402


class TestLlamaCliTimeoutDefaults(unittest.TestCase):
    def test_timeout_default_is_canonical_in_code_and_not_duplicated_in_pipeline_presets(self) -> None:
        expected = int(_DEFAULT_TIMEOUT_SECONDS)
        self.assertFalse(self._pipeline_default_has_timeout())
        self.assertFalse(self._plugins_toml_has_timeout(repo_root / "config" / "plugins.toml"))
        self.assertFalse(
            self._pipeline_default_has_timeout(
                repo_root / "releases" / "core_free" / "config" / "settings" / "pipeline" / "default.json"
            )
        )
        self.assertFalse(
            self._plugins_toml_has_timeout(repo_root / "releases" / "core_free" / "config" / "plugins.toml")
        )
        self.assertEqual(expected, 300)

    def _pipeline_default_has_timeout(self, path: Path | None = None) -> bool:
        path = path or (repo_root / "config" / "settings" / "pipeline" / "default.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        plugin_config = data.get("plugin_config", {})
        if not isinstance(plugin_config, dict):
            return False
        plugin_payload = plugin_config.get("llm.llama_cli", {})
        return isinstance(plugin_payload, dict) and "timeout_seconds" in plugin_payload

    def _plugins_toml_has_timeout(self, path: Path) -> bool:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        llm_stage = data["stages"]["llm_processing"]
        direct_plugin_id = str(llm_stage.get("plugin_id", "")).strip()
        if direct_plugin_id == "llm.llama_cli":
            params = llm_stage.get("params", {})
            return isinstance(params, dict) and "timeout_seconds" in params
        variants = llm_stage.get("variants", [])
        for item in variants:
            if str(item.get("plugin_id", "")).strip() != "llm.llama_cli":
                continue
            params = item.get("params", {})
            return isinstance(params, dict) and "timeout_seconds" in params
        return False


if __name__ == "__main__":
    unittest.main()
