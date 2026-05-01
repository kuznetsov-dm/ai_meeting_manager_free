import unittest

from aimn.core.plugin_policy import PluginPolicy
from aimn.core.plugins_config import PluginsConfig


class TestPluginPolicy(unittest.TestCase):
    def test_enabled_overrides_other_lists(self) -> None:
        config = PluginsConfig(
            {
                "enabled": ["a", "b"],
                "allowlist": ["c"],
                "disabled": ["b"],
            }
        )
        policy = PluginPolicy(config)
        self.assertTrue(policy.is_enabled("a"))
        self.assertTrue(policy.is_enabled("b"))
        self.assertFalse(policy.is_enabled("c"))

    def test_allowlist_used_when_enabled_missing(self) -> None:
        config = PluginsConfig(
            {
                "allowlist": {"ids": ["a", "c"]},
                "disabled": ["a"],
            }
        )
        policy = PluginPolicy(config)
        self.assertTrue(policy.is_enabled("a"))
        self.assertFalse(policy.is_enabled("b"))
        self.assertTrue(policy.is_enabled("c"))

    def test_disabled_used_when_no_enabled_or_allowlist(self) -> None:
        config = PluginsConfig({"disabled": {"ids": ["b"]}})
        policy = PluginPolicy(config)
        self.assertTrue(policy.is_enabled("a"))
        self.assertFalse(policy.is_enabled("b"))


if __name__ == "__main__":
    unittest.main()
