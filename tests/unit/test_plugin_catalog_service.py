import sys
import unittest
import uuid
import shutil
from pathlib import Path
from types import SimpleNamespace


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.plugin_catalog_service import PluginCatalogService  # noqa: E402


class TestPluginCatalogService(unittest.TestCase):
    def test_catalog_stamp_returns_stamp_and_manifest_count(self) -> None:
        temp_root = repo_root / "apps" / "ai_meeting_manager" / "logs" / f"test_plugin_catalog_{uuid.uuid4().hex}"
        try:
            app_root = temp_root
            plugin_dir = app_root / "plugins" / "demo" / "sample"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "plugin.json").write_text("{}", encoding="utf-8")

            service = PluginCatalogService(app_root)
            registry = SimpleNamespace(payload={}, stamp="registry-stamp")
            service._registry = SimpleNamespace(stamp=lambda _registry: "registry-stamp")  # type: ignore[attr-defined]

            stamp, manifest_count = service._catalog_stamp(registry)  # type: ignore[attr-defined]

            self.assertIn("registry-stamp", stamp)
            self.assertGreaterEqual(manifest_count, 1)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
