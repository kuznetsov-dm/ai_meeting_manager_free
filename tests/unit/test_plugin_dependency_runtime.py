import json
import os
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


def _write_plugin_manifest(path: Path, plugin_id: str, dependencies: list[str]) -> None:
    payload = {
        "id": plugin_id,
        "name": "Test plugin",
        "product_name": "Test plugin",
        "highlights": "h",
        "description": "d",
        "version": "1.0.0",
        "api_version": "1",
        "entrypoint": "plugins.test.plugin:Plugin",
        "hooks": [],
        "artifacts": [],
        "dependencies": dependencies,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


class TestPluginDependencyRuntime(unittest.TestCase):
    def test_resolver_uses_existing_plugin_venv(self) -> None:
        from aimn.core.plugin_dependency_runtime import resolve_plugin_python

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_id = "service.dep_test"
            plugin_dir = root / "plugins" / plugin_id
            plugin_dir.mkdir(parents=True, exist_ok=True)
            _write_plugin_manifest(plugin_dir / "plugin.json", plugin_id, [])

            env_root = root / "config" / "plugin_envs" / plugin_id
            if os.name == "nt":
                python_path = env_root / "venv" / "Scripts" / "python.exe"
            else:
                python_path = env_root / "venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_bytes(b"")

            resolved = resolve_plugin_python(root, plugin_id)
            self.assertEqual(Path(resolved), python_path)

    def test_resolver_falls_back_when_auto_install_disabled(self) -> None:
        from aimn.core.plugin_dependency_runtime import resolve_plugin_python

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_id = "service.dep_req"
            plugin_dir = root / "plugins" / plugin_id
            plugin_dir.mkdir(parents=True, exist_ok=True)
            _write_plugin_manifest(plugin_dir / "plugin.json", plugin_id, ["requests==2.32.3"])

            previous = os.environ.get("AIMN_PLUGIN_AUTO_INSTALL_DEPS")
            os.environ["AIMN_PLUGIN_AUTO_INSTALL_DEPS"] = "0"
            try:
                resolved = resolve_plugin_python(root, plugin_id)
            finally:
                if previous is None:
                    os.environ.pop("AIMN_PLUGIN_AUTO_INSTALL_DEPS", None)
                else:
                    os.environ["AIMN_PLUGIN_AUTO_INSTALL_DEPS"] = previous
            self.assertEqual(Path(resolved), Path(sys.executable))


if __name__ == "__main__":
    unittest.main()

