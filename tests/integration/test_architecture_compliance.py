import ast
import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.fingerprinting import compute_source_fingerprint  # noqa: E402
from aimn.core.import_guard import ensure_core_does_not_import_plugins  # noqa: E402
from aimn.core.plugin_distribution import PluginDistributionResolver  # noqa: E402
from aimn.core.plugin_manifest import load_plugin_manifest  # noqa: E402
from aimn.core.plugin_services import _entrypoint_allows_core_imports  # noqa: E402
from aimn.domain.meeting import ArtifactRef  # noqa: E402


class TestArchitectureCompliance(unittest.TestCase):
    def test_ui_and_cli_use_core_facade_only(self) -> None:
        ui_root = repo_root / "src" / "aimn" / "ui"
        cli_path = repo_root / "src" / "aimn" / "cli.py"
        allowed = {"aimn.core.api", "aimn.core.contracts"}
        violations: list[str] = []

        def _check_file(path: Path) -> None:
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except Exception as exc:
                violations.append(f"{path}: parse_failed:{exc}")
                return
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name
                        if name == "aimn.pipeline_presets" or name.startswith("aimn.pipeline_presets."):
                            violations.append(f"{path}:{node.lineno} import {name} (pipeline_presets forbidden)")
                        if name == "aimn.core" or name.startswith("aimn.core."):
                            if name not in allowed and not any(name.startswith(f"{item}.") for item in allowed):
                                violations.append(f"{path}:{node.lineno} import {name} (core facade only)")
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "aimn.pipeline_presets" or module.startswith("aimn.pipeline_presets."):
                        violations.append(f"{path}:{node.lineno} from {module} import ... (pipeline_presets forbidden)")
                    if module == "aimn.core" or module.startswith("aimn.core."):
                        if module not in allowed and not any(module.startswith(f"{item}.") for item in allowed):
                            violations.append(f"{path}:{node.lineno} from {module} import ... (core facade only)")

        for path in ui_root.rglob("*.py"):
            _check_file(path)
        _check_file(cli_path)

        if violations:
            message = "Facade violations:\n" + "\n".join(violations)
            self.fail(message)
    def test_core_does_not_import_plugins(self) -> None:
        ensure_core_does_not_import_plugins(repo_root)

    def test_plugin_manifests_load(self) -> None:
        plugins_dir = repo_root / "plugins"
        manifests = list(plugins_dir.rglob("plugin.json"))
        self.assertTrue(manifests, "expected plugin.json files")
        for manifest_path in manifests:
            manifest = load_plugin_manifest(manifest_path)
            self.assertTrue(manifest.plugin_id)
            self.assertTrue(manifest.entrypoint)

    def test_production_plugin_manifest_is_colocated_with_plugin_module(self) -> None:
        plugins_dir = repo_root / "plugins"
        manifests = list(plugins_dir.rglob("plugin.json"))
        self.assertTrue(manifests, "expected plugin.json files")
        for manifest_path in manifests:
            manifest = load_plugin_manifest(manifest_path)
            parent_name = manifest_path.parent.name
            if parent_name == "schemas" or parent_name.startswith("_test_"):
                continue
            relative = manifest_path.relative_to(plugins_dir)
            self.assertEqual(
                len(relative.parts),
                3,
                f"plugin manifest must live at plugins/<group>/<package>/plugin.json: {manifest_path}",
            )
            self.assertFalse("." in parent_name, f"legacy dotted plugin dir remains: {manifest_path.parent}")
            expected_module = f"plugins.{relative.parts[0]}.{parent_name}.{parent_name}"
            module_name, _class_name = str(manifest.entrypoint).split(":", 1)
            self.assertEqual(
                module_name,
                expected_module,
                f"entrypoint must follow plugins.<group>.<package>.<package>: {manifest_path}",
            )
            self.assertTrue(
                (manifest_path.parent / f"{parent_name}.py").exists(),
                f"{parent_name}.py must be colocated with manifest: {manifest_path}",
            )

    def test_distributed_plugin_manifests_are_runtime_loadable(self) -> None:
        plugins_dir = repo_root / "plugins"
        resolver = PluginDistributionResolver(repo_root)
        violations: list[str] = []

        for manifest_path in plugins_dir.rglob("plugin.json"):
            parent_name = manifest_path.parent.name
            if parent_name == "schemas" or parent_name.startswith("_test_"):
                continue
            manifest = load_plugin_manifest(manifest_path)
            access = resolver.resolve_plugin(manifest.plugin_id, manifest.distribution, manifest_path)
            if access.source_kind != "bundled" or not access.catalog_enabled:
                continue
            module_name, _class_name = str(manifest.entrypoint).split(":", 1)
            if _entrypoint_allows_core_imports(module_name):
                continue
            relpath = manifest_path.relative_to(repo_root)
            violations.append(f"{manifest.plugin_id}: blocked entrypoint {module_name} from {relpath}")

        if violations:
            self.fail("Distributed plugin manifests blocked by runtime import policy:\n" + "\n".join(violations))

    def test_core_ui_do_not_hardcode_plugin_ids(self) -> None:
        plugin_ids: set[str] = set()
        for manifest_path in (repo_root / "plugins").rglob("plugin.json"):
            try:
                manifest = load_plugin_manifest(manifest_path)
            except Exception:
                continue
            pid = str(manifest.plugin_id or "").strip()
            if pid:
                plugin_ids.add(pid)
        self.assertTrue(plugin_ids, "expected plugin ids from manifests")

        violations: list[str] = []
        roots = [repo_root / "src" / "aimn" / "core", repo_root / "src" / "aimn" / "ui"]
        for root in roots:
            for path in root.rglob("*.py"):
                if "_legacy_quarantine" in str(path):
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    violations.append(f"{path}: parse_failed:{exc}")
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                        continue
                    text = str(node.value).strip()
                    if text in plugin_ids:
                        violations.append(f"{path}:{getattr(node, 'lineno', '?')} literal '{text}'")

        if violations:
            self.fail("Hardcoded plugin IDs found:\n" + "\n".join(violations))

    def test_artifact_paths_are_flat(self) -> None:
        with self.assertRaises(ValueError):
            ArtifactRef(kind="test", path="nested/file.txt")

    def test_fingerprint_deterministic_for_same_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "left.txt"
            right = root / "right.txt"
            left.write_text("sample", encoding="utf-8")
            right.write_text("sample", encoding="utf-8")
            self.assertEqual(compute_source_fingerprint(str(left)), compute_source_fingerprint(str(right)))


if __name__ == "__main__":
    unittest.main()
