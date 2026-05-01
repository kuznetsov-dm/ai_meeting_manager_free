from __future__ import annotations

import json
import sys
from pathlib import Path

from aimn.core.plugin_manager import PluginManager
from aimn.core.plugins_config import PluginsConfig
from aimn.core.plugins_registry import load_registry_payload


def main() -> int:
    raw = sys.stdin.read()
    request = json.loads(raw or "{}")
    repo_root = Path(request.get("repo_root", "")).resolve()
    if not repo_root.exists():
        print(json.dumps({"status": "error", "message": "repo_root_missing"}, ensure_ascii=True))
        return 1
    registry_payload, _source, _path = load_registry_payload(repo_root)
    config = PluginsConfig(registry_payload)
    manager = PluginManager(repo_root, config)
    manager.load()
    try:
        result = manager.invoke_action(
            str(request.get("plugin_id", "")),
            str(request.get("action_id", "")),
            request.get("params") or {},
            settings_override=request.get("settings_override"),
        )
        print(json.dumps(result.to_dict(), ensure_ascii=True))
        return 0
    finally:
        manager.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
