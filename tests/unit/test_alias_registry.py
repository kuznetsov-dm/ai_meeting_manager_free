import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestAliasRegistry(unittest.TestCase):
    def test_persists_new_provider_and_model_alias(self) -> None:
        from aimn.core.alias_registry import AliasRegistry

        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            registry = AliasRegistry(app_root)
            provider = registry.provider_code("llm.super_provider")
            model = registry.model_code("llm.super_provider", "vendor/super-model-v2:free")

            self.assertEqual(provider, "su")
            self.assertTrue(model)

            reloaded = AliasRegistry(app_root)
            self.assertEqual(reloaded.provider_code("llm.super_provider"), provider)
            self.assertEqual(reloaded.model_code("llm.super_provider", "vendor/super-model-v2:free"), model)

            path = app_root / "output" / "settings" / "aliases.json"
            self.assertTrue(path.exists())

    def test_provider_collision_gets_unique_code(self) -> None:
        from aimn.core.alias_registry import AliasRegistry

        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            registry = AliasRegistry(app_root)
            first = registry.provider_code("llm.sample")
            second = registry.provider_code("llm.sampler")
            self.assertNotEqual(first, second)
            self.assertTrue(second.startswith(first))

    def test_save_failure_does_not_break_generated_aliases(self) -> None:
        from aimn.core.alias_registry import AliasRegistry

        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            registry = AliasRegistry(app_root)
            with mock.patch("aimn.core.alias_registry.atomic_write_text", side_effect=PermissionError("locked")):
                provider = registry.provider_code("llm.locked_provider")
                model = registry.model_code("llm.locked_provider", "vendor/locked-model-v1")

            self.assertEqual(provider, "lo")
            self.assertTrue(model)
            self.assertFalse((app_root / "output" / "settings" / "aliases.json").exists())

    def test_lineage_uses_registry_for_unknown_provider(self) -> None:
        from aimn.core.alias_registry import reset_alias_registry_cache_for_tests
        from aimn.core.lineage import alias_code_for_stage, stage_alias_prefix

        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            with mock.patch.dict(os.environ, {"AIMN_HOME": str(app_root)}):
                reset_alias_registry_cache_for_tests()
                code = alias_code_for_stage(
                    "llm_processing",
                    {
                        "plugin_id": "llm.custom_provider",
                        "model_id": "custom/chat-lite-v1",
                    },
                )
                self.assertTrue(code.startswith("cu"))
                alias = f"{stage_alias_prefix('llm_processing')}{code}1"
                self.assertTrue(alias.startswith("aicu"))

                registry_file = app_root / "output" / "settings" / "aliases.json"
                self.assertTrue(registry_file.exists())


if __name__ == "__main__":
    unittest.main()
