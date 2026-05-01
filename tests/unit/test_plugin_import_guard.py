import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.plugin_services import _entrypoint_allows_core_imports  # noqa: E402


class TestPluginImportGuard(unittest.TestCase):
    def test_detects_core_import_in_package_tree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "pkgtest"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "entry.py").write_text("value = 1\n", encoding="utf-8")
            (pkg / "helper.py").write_text("import aimn.core\n", encoding="utf-8")

            sys.path.insert(0, str(root))
            try:
                allowed = _entrypoint_allows_core_imports("pkgtest.entry")
            finally:
                sys.path.remove(str(root))
            self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
