import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import aimn.core.contracts as core_contracts  # noqa: E402
import aimn.plugins.api as plugin_api  # noqa: E402
import aimn.plugins.interfaces as plugin_interfaces  # noqa: E402


class TestPluginApiExports(unittest.TestCase):
    def test_legacy_management_artifact_constants_are_not_exported(self) -> None:
        for module in (plugin_api, plugin_interfaces):
            self.assertFalse(hasattr(module, "KIND_TASKS"))
            self.assertFalse(hasattr(module, "KIND_PROJECTS"))
            self.assertFalse(hasattr(module, "KIND_AGENDAS"))

    def test_legacy_management_artifact_constants_are_not_present_in_core_contracts(self) -> None:
        self.assertFalse(hasattr(core_contracts, "KIND_TASKS"))
        self.assertFalse(hasattr(core_contracts, "KIND_PROJECTS"))
        self.assertFalse(hasattr(core_contracts, "KIND_AGENDAS"))


if __name__ == "__main__":
    unittest.main()
