import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from aimn.core import action_cli
from aimn.plugins.interfaces import ActionResult


class _DummyManager:
    last_call = None

    def __init__(self, repo_root: Path, config) -> None:
        self.repo_root = repo_root
        self.config = config

    def load(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def invoke_action(self, plugin_id: str, action_id: str, params: dict, *, settings_override=None):
        _DummyManager.last_call = (plugin_id, action_id, params, settings_override)
        return ActionResult(status="success", message="ok")


class TestActionCliPayload(unittest.TestCase):
    def test_action_cli_uses_request_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            payload = {
                "repo_root": str(repo_root),
                "plugin_id": "llm.openrouter",
                "action_id": "test_connection",
                "params": {"foo": "bar"},
                "settings_override": {"auth_mode": "user_key"},
            }
            stdin = io.StringIO(json.dumps(payload))
            stdout = io.StringIO()
            with mock.patch.object(action_cli, "PluginManager", _DummyManager), mock.patch.object(
                action_cli, "load_registry_payload", return_value=({}, "missing", None)
            ), mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout):
                exit_code = action_cli.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            _DummyManager.last_call,
            ("llm.openrouter", "test_connection", {"foo": "bar"}, {"auth_mode": "user_key"}),
        )
