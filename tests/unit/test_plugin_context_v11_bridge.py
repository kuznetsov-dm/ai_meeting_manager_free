import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestPluginContextV11Bridge(unittest.TestCase):
    def test_plugin_context_exposes_storage_secret_and_services(self) -> None:
        from aimn.core.plugin_services import PluginContext, PluginRegistry, PluginSettingsService

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = PluginRegistry()
            settings = PluginSettingsService(root, registry)
            ctx = PluginContext(registry, settings, "service.test_bridge")

            ctx.register_service("echo", lambda: {"ok": True})
            self.assertEqual(ctx.get_service("echo"), {"ok": True})

            storage = Path(ctx.get_storage_path())
            self.assertTrue(storage.exists())
            self.assertTrue(storage.is_dir())

            ctx.set_secret("api_key", "secret-123")
            self.assertEqual(ctx.get_secret("api_key"), "secret-123")
            plain_settings = settings.get_settings("service.test_bridge", include_secrets=False)
            self.assertNotIn("api_key", plain_settings)

    def test_hook_context_helpers_and_artifacts_facade(self) -> None:
        from aimn.core.contracts import (
            Artifact,
            ArtifactMeta,
            ArtifactSchema,
            HookContext,
            PluginLogLevel,
        )

        meta = ArtifactMeta(kind="summary", path="summary.md", content_type="text/markdown", user_visible=True)
        artifact = Artifact(meta=meta, content="hello")
        ctx = HookContext(
            plugin_id="text_processing.test_bridge",
            meeting_id="m-1",
            alias="demo",
            input_text="source text",
            plugin_config={"max_items": 5, "token": "fallback-token"},
            _storage_dir="C:/tmp/plugin_state/test_bridge",
            _get_artifact=lambda kind: artifact if kind == "summary" else None,
            _list_artifacts=lambda: [meta],
            _get_secret=lambda key: "secret-token" if key == "token" else None,
            _resolve_service=lambda name: {"name": "svc"} if name == "svc" else None,
            _schema_resolver=lambda kind: (
                ArtifactSchema(content_type="text/plain", user_visible=True) if kind == "edited" else None
            ),
        )

        self.assertEqual(ctx.get_setting("max_items"), 5)
        self.assertEqual(ctx.settings.get("max_items"), 5)
        self.assertEqual(ctx.get_secret("token"), "secret-token")
        self.assertEqual(ctx.storage_path, "C:/tmp/plugin_state/test_bridge")
        self.assertEqual(ctx.get_service("svc"), {"name": "svc"})
        self.assertEqual(ctx.get_artifact("summary").content, "hello")
        self.assertEqual(len(ctx.list_artifacts()), 1)

        # Logging helper should be a no-op from API perspective (no exception expected).
        ctx.log(PluginLogLevel.INFO, "bridge test")
        ctx.log("WARNING", "bridge test")

        view = ctx.artifacts
        self.assertEqual(view.get_artifact("summary").content, "hello")
        self.assertEqual(len(view.list_artifacts()), 1)
        view.save_artifact("edited", "ok", content_type="text/plain")
        result = ctx.build_result()
        self.assertEqual(len(result.outputs), 1)
        self.assertEqual(result.outputs[0].kind, "edited")
        self.assertEqual(result.outputs[0].content, "ok")

    def test_plugin_loader_adds_repo_root_and_plugins_dir_to_sys_path(self) -> None:
        from aimn.core.plugin_services import PluginLoader, PluginRegistry, PluginSettingsService
        from aimn.core.plugins_config import PluginsConfig

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = PluginsConfig({})
            registry = PluginRegistry()
            settings = PluginSettingsService(root, registry)

            repo_path = str(root.resolve())
            plugins_path = str((root / "plugins").resolve())
            original = list(sys.path)
            try:
                while repo_path in sys.path:
                    sys.path.remove(repo_path)
                while plugins_path in sys.path:
                    sys.path.remove(plugins_path)

                PluginLoader(root, config, registry, settings)

                self.assertIn(repo_path, sys.path)
                self.assertIn(plugins_path, sys.path)
            finally:
                sys.path[:] = original


if __name__ == "__main__":
    unittest.main()
