import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.contracts import PluginDescriptor, PluginSetting, PluginUiSchema  # noqa: E402
from aimn.ui.widgets.credentials_hub import build_credentials_hub_specs, _validation_cache_status  # noqa: E402


class _FakeCatalog:
    def __init__(self, plugins: list[PluginDescriptor], schemas: dict[str, PluginUiSchema]) -> None:
        self._plugins = list(plugins)
        self._schemas = dict(schemas)

    def all_plugins(self) -> list[PluginDescriptor]:
        return list(self._plugins)

    def schema_for(self, plugin_id: str) -> PluginUiSchema | None:
        return self._schemas.get(str(plugin_id))

    def display_name(self, plugin_id: str) -> str:
        for plugin in self._plugins:
            if plugin.plugin_id == plugin_id:
                return plugin.product_name or plugin.name or plugin.plugin_id
        return str(plugin_id)


class TestCredentialsHub(unittest.TestCase):
    def test_validation_cache_status_reads_success_payload(self) -> None:
        state, text = _validation_cache_status(
            {"_credentials_validation": {"state": "ok", "text": "Connection verified."}}
        )

        self.assertEqual(state, "ok")
        self.assertEqual(text, "Connection verified.")

    def test_build_credentials_hub_specs_uses_custom_metadata(self) -> None:
        plugin = PluginDescriptor(
            plugin_id="llm.llama_cli",
            stage_id="llm_processing",
            name="Llama (CLI)",
            product_name="Llama.cpp Local LLM",
            provider_name="Llama.cpp",
            module="plugins.llm.llama_cli.llama_cli",
            class_name="Plugin",
            capabilities={
                "credentials_hub": {
                    "description": "Token is optional and only needed for gated repos.",
                    "validate_action": "validate_hf_token",
                    "links": [{"label": "Docs", "url": "https://huggingface.co/docs/hub/security-tokens"}],
                    "fields": [
                        {
                            "key": "hf_token",
                            "label": "Hugging Face Token",
                            "placeholder": "hf_...",
                            "help_text": "Needed only for gated/private repos.",
                        }
                    ],
                }
            },
        )
        schema = PluginUiSchema(
            plugin_id=plugin.plugin_id,
            stage_id=plugin.stage_id,
            settings=[
                PluginSetting(key="hf_token", label="HF Token", value=""),
                PluginSetting(key="endpoint", label="Endpoint", value=""),
            ],
        )
        catalog = _FakeCatalog([plugin], {plugin.plugin_id: schema})

        specs = build_credentials_hub_specs(
            catalog,
            action_ids_by_plugin={plugin.plugin_id: {"download_model"}},
            stage_label=lambda stage_id: f"stage:{stage_id}",
        )

        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec.plugin_id, plugin.plugin_id)
        self.assertEqual(spec.validate_action_id, "validate_hf_token")
        self.assertEqual(spec.description, "Token is optional and only needed for gated repos.")
        self.assertEqual(spec.links, (("Docs", "https://huggingface.co/docs/hub/security-tokens"),))
        self.assertEqual(len(spec.fields), 1)
        self.assertEqual(spec.fields[0].key, "hf_token")
        self.assertEqual(spec.fields[0].placeholder, "hf_...")
        self.assertEqual(spec.fields[0].help_text, "Needed only for gated/private repos.")

    def test_build_credentials_hub_specs_falls_back_to_secret_schema_fields(self) -> None:
        plugin = PluginDescriptor(
            plugin_id="llm.openrouter",
            stage_id="llm_processing",
            name="OpenRouter",
            provider_name="OpenRouter",
            module="plugins.llm.openrouter.openrouter",
            class_name="Plugin",
        )
        schema = PluginUiSchema(
            plugin_id=plugin.plugin_id,
            stage_id=plugin.stage_id,
            settings=[
                PluginSetting(key="api_key", label="API Key", value=""),
                PluginSetting(key="endpoint", label="Endpoint", value="https://openrouter.ai/api/v1"),
            ],
        )
        catalog = _FakeCatalog([plugin], {plugin.plugin_id: schema})

        specs = build_credentials_hub_specs(
            catalog,
            action_ids_by_plugin={plugin.plugin_id: {"test_connection"}},
            stage_label=lambda stage_id: stage_id,
        )

        self.assertEqual(len(specs), 1)
        spec = specs[0]
        self.assertEqual(spec.validate_action_id, "test_connection")
        self.assertEqual([field.key for field in spec.fields], ["api_key"])


if __name__ == "__main__":
    unittest.main()

