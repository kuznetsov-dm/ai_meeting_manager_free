import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_discovery import PluginDiscovery  # noqa: E402


def _payload(plugin_id: str, entrypoint: str) -> dict:
    return {
        "id": plugin_id,
        "name": plugin_id,
        "product_name": plugin_id,
        "highlights": "",
        "description": "",
        "version": "1.0.0",
        "api_version": "1",
        "entrypoint": entrypoint,
        "hooks": [],
        "artifacts": [],
    }


class TestPluginDiscoveryDuplicates(unittest.TestCase):
    def test_discovery_ignores_duplicate_plugin_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "plugins" / "a"
            second = root / "plugins" / "b"
            first.mkdir(parents=True, exist_ok=True)
            second.mkdir(parents=True, exist_ok=True)
            (first / "plugin.json").write_text(
                json.dumps(_payload("service.dup", "plugins.a.plugin:Plugin"), ensure_ascii=True),
                encoding="utf-8",
            )
            (second / "plugin.json").write_text(
                json.dumps(_payload("service.dup", "plugins.b.plugin:Plugin"), ensure_ascii=True),
                encoding="utf-8",
            )

            discovery = PluginDiscovery(root / "plugins")
            manifests = discovery.discover()

        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0].plugin_id, "service.dup")
        self.assertEqual(manifests[0].entrypoint, "plugins.a.plugin:Plugin")


if __name__ == "__main__":
    unittest.main()
