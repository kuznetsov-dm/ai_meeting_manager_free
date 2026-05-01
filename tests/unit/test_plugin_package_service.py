import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.app_paths import (  # noqa: E402
    get_installed_plugins_dir,
    get_installed_plugins_state_path,
)
from aimn.core.plugin_activation_service import PluginActivationService  # noqa: E402
from aimn.core.plugin_package_service import PluginPackageService  # noqa: E402


def _plugin_payload(plugin_id: str, version: str) -> dict:
    return {
        "id": plugin_id,
        "name": plugin_id,
        "product_name": plugin_id,
        "highlights": "Highlights",
        "description": "Description",
        "version": version,
        "api_version": "1",
        "entrypoint": "sample_module:Plugin",
        "hooks": [{"name": "postprocess.after_transcribe"}],
        "artifacts": ["edited"],
    }


class TestPluginPackageService(unittest.TestCase):
    def test_install_from_directory_updates_installed_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            package_root = app_root / "package_dir"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "plugin.json").write_text(
                json.dumps(_plugin_payload("text_processing.sample", "1.2.3"), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            (package_root / "sample_module.py").write_text("class Plugin:\n    pass\n", encoding="utf-8")

            service = PluginPackageService(app_root)
            result = service.install_from_path(package_root)

            self.assertEqual(result.plugin_id, "text_processing.sample")
            target_manifest = get_installed_plugins_dir(app_root) / "text_processing.sample" / "plugin.json"
            self.assertTrue(target_manifest.exists())

            state_path = get_installed_plugins_state_path(app_root)
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["plugins"]["text_processing.sample"]["installed_version"],
                "1.2.3",
            )

    def test_install_from_zip_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            source_dir = app_root / "plugin_source"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "plugin.json").write_text(
                json.dumps(_plugin_payload("service.sample", "2.0.0"), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            (source_dir / "sample_module.py").write_text("class Plugin:\n    pass\n", encoding="utf-8")
            package_zip = app_root / "service.sample.zip"
            with ZipFile(package_zip, "w") as archive:
                archive.write(source_dir / "plugin.json", arcname="service.sample/plugin.json")
                archive.write(source_dir / "sample_module.py", arcname="service.sample/sample_module.py")

            service = PluginPackageService(app_root)
            install_result = service.install_from_path(package_zip)
            self.assertEqual(install_result.plugin_id, "service.sample")

            remove_result = service.remove_installed_plugin("service.sample")
            self.assertTrue(remove_result.removed)
            self.assertFalse((get_installed_plugins_dir(app_root) / "service.sample").exists())

            payload = json.loads(get_installed_plugins_state_path(app_root).read_text(encoding="utf-8"))
            self.assertNotIn("service.sample", payload.get("plugins", {}))

    def test_update_rejects_wrong_plugin_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            package_root = app_root / "package_dir"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "plugin.json").write_text(
                json.dumps(_plugin_payload("llm.sample", "1.0.0"), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            service = PluginPackageService(app_root)
            with self.assertRaisesRegex(ValueError, "plugin_package_unexpected_id"):
                service.install_from_path(package_root, expected_plugin_id="llm.other")

    def test_install_rejects_path_traversal_plugin_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            package_root = app_root / "package_dir"
            package_root.mkdir(parents=True, exist_ok=True)
            payload = _plugin_payload("text_processing.sample", "1.0.0")
            payload["id"] = "../escape_plugin"
            (package_root / "plugin.json").write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            (package_root / "sample_module.py").write_text("class Plugin:\n    pass\n", encoding="utf-8")

            service = PluginPackageService(app_root)
            with self.assertRaises(ValueError):
                service.install_from_path(package_root)

            self.assertFalse((app_root / "config" / "escape_plugin").exists())

    def test_install_rejects_zip_slip_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            source_dir = app_root / "plugin_source"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "plugin.json").write_text(
                json.dumps(_plugin_payload("service.sample", "2.0.0"), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            (source_dir / "sample_module.py").write_text("class Plugin:\n    pass\n", encoding="utf-8")
            package_zip = app_root / "service.sample.zip"
            with ZipFile(package_zip, "w") as archive:
                archive.write(source_dir / "plugin.json", arcname="service.sample/plugin.json")
                archive.write(source_dir / "sample_module.py", arcname="service.sample/sample_module.py")
                archive.writestr("../escape.txt", "nope")

            service = PluginPackageService(app_root)
            with self.assertRaisesRegex(ValueError, "plugin_package_zip_path_invalid"):
                service.install_from_path(package_zip)

            self.assertFalse((app_root / "escape.txt").exists())

    def test_new_install_defaults_to_inactive_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            package_root = app_root / "package_dir"
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "plugin.json").write_text(
                json.dumps(_plugin_payload("service.sample", "1.0.0"), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            (package_root / "sample_module.py").write_text("class Plugin:\n    pass\n", encoding="utf-8")

            service = PluginPackageService(app_root)
            service.install_from_path(package_root)

            activation = PluginActivationService(app_root)
            self.assertEqual(activation.desired_state("service.sample"), "inactive")


if __name__ == "__main__":
    unittest.main()
