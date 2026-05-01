import asyncio
import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


class TestPluginRuntimeAsync(unittest.TestCase):
    def test_async_hook_handler_is_awaited(self) -> None:
        from aimn.core.contracts import HookContext, PluginResult
        from aimn.core.plugin_manifest import HookSpec, PluginManifest
        from aimn.core.plugin_services import PluginRegistry, PluginRuntime
        from aimn.core.plugins_config import PluginsConfig

        registry = PluginRegistry()
        runtime = PluginRuntime(registry, PluginsConfig({}))
        plugin_id = "text_processing.async_test"
        manifest = PluginManifest(
            plugin_id=plugin_id,
            name="Async Test",
            version="1.0.0",
            api_version="1",
            entrypoint="plugins.text_processing.async_test:Plugin",
            hooks=[HookSpec(name="postprocess.after_transcribe")],
            artifacts=[],
            product_name="Async Test",
            highlights="",
            description="",
        )
        registry.add_manifest(manifest)

        async def _handler(_ctx: HookContext) -> PluginResult:
            await asyncio.sleep(0.01)
            return PluginResult(outputs=[], warnings=["async_ok"])

        registry.register_hook_handler(
            plugin_id=plugin_id,
            hook_name="postprocess.after_transcribe",
            handler=_handler,
        )
        ctx = HookContext(
            plugin_id=plugin_id,
            meeting_id="m1",
            alias=None,
            input_text="hello",
            plugin_config={},
        )
        runs = runtime.execute_connector(
            "postprocess.after_transcribe",
            ctx,
            allowed_plugin_ids=[plugin_id],
        )

        self.assertEqual(len(runs), 1)
        self.assertIsNotNone(runs[0].result)
        self.assertEqual(runs[0].result.warnings, ["async_ok"])


if __name__ == "__main__":
    unittest.main()

