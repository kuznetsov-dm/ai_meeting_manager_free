import importlib
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.plugin_catalog_service import PluginCatalogService  # noqa: E402


def _coerce_installed(entry: dict) -> bool | None:
    value = entry.get("installed")
    if isinstance(value, bool):
        return value
    status = str(entry.get("status", "") or "").strip().lower()
    if status in {"installed", "enabled", "ready"}:
        return True
    if status in {"not_installed", "missing", "available"}:
        return False
    return None


def _load_default_settings(plugin_id: str) -> dict:
    path = repo_root / "config" / "settings" / "plugins" / f"{plugin_id}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


class TestModelListActionContract(unittest.TestCase):
    def test_list_models_action_returns_models_payload(self) -> None:
        catalog = PluginCatalogService(repo_root).load().catalog
        failures: list[str] = []

        # Make model listing deterministic and offline-safe for unit tests.
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            for plugin in catalog.all_plugins():
                caps = plugin.capabilities if isinstance(plugin.capabilities, dict) else {}
                models_caps = caps.get("models") if isinstance(caps, dict) else None
                if not isinstance(models_caps, dict):
                    continue
                managed = models_caps.get("managed_actions")
                if not isinstance(managed, dict):
                    continue
                list_action = str(managed.get("list", "") or "").strip()
                if not list_action:
                    continue

                module_name = str(plugin.module or "").strip()
                if not module_name:
                    failures.append(f"{plugin.plugin_id}: managed_actions.list={list_action} but module is empty")
                    continue
                try:
                    module = importlib.import_module(module_name)
                except Exception as exc:
                    failures.append(f"{plugin.plugin_id}: import {module_name} failed: {exc}")
                    continue
                if not hasattr(module, "action_descriptors"):
                    failures.append(f"{plugin.plugin_id}: {module_name} has no action_descriptors()")
                    continue

                try:
                    descriptors = list(module.action_descriptors())  # type: ignore[attr-defined]
                except Exception as exc:
                    failures.append(f"{plugin.plugin_id}: action_descriptors() failed: {exc}")
                    continue
                desc = next((d for d in descriptors if getattr(d, "action_id", "") == list_action), None)
                if desc is None:
                    failures.append(f"{plugin.plugin_id}: action {list_action} not registered in action_descriptors()")
                    continue

                handler = getattr(desc, "handler", None)
                if not callable(handler):
                    failures.append(f"{plugin.plugin_id}: action {list_action} has no callable handler")
                    continue

                settings = _load_default_settings(plugin.plugin_id)
                try:
                    result = handler(settings, {})
                except Exception as exc:
                    failures.append(f"{plugin.plugin_id}: {list_action} handler raised: {exc}")
                    continue

                data = getattr(result, "data", None)
                if not isinstance(data, dict):
                    failures.append(f"{plugin.plugin_id}: {list_action} returned data={type(data).__name__}, expected dict")
                    continue
                models = data.get("models")
                if not isinstance(models, list):
                    failures.append(f"{plugin.plugin_id}: {list_action} returned data.models={type(models).__name__}")
                    continue

                storage = str(models_caps.get("storage", "") or "").strip().lower()
                for entry in models:
                    if not isinstance(entry, dict):
                        failures.append(f"{plugin.plugin_id}: model entry is {type(entry).__name__}, expected dict")
                        continue
                    model_id = str(entry.get("model_id", "") or "").strip()
                    if not model_id:
                        failures.append(f"{plugin.plugin_id}: model entry missing model_id")
                        continue

                    if entry.get("selectable") is False:
                        # Managed download-only rows may not support enable/installed semantics.
                        continue

                    enabled = entry.get("enabled")
                    if not isinstance(enabled, bool):
                        failures.append(f"{plugin.plugin_id}:{model_id}: enabled is {type(enabled).__name__}, expected bool")

                    availability_status = str(entry.get("availability_status", "") or "").strip().lower()
                    if availability_status not in {"ready", "needs_setup", "unknown", "limited", "unavailable"}:
                        failures.append(
                            f"{plugin.plugin_id}:{model_id}: availability_status={availability_status!r} is not normalized"
                        )

                    if storage == "local":
                        installed = _coerce_installed(entry)
                        if installed is None:
                            failures.append(
                                f"{plugin.plugin_id}:{model_id}: installed is missing/unknown for local storage"
                            )

        self.assertFalse(
            failures,
            "Model list action contract violations:\n" + "\n".join(f"- {item}" for item in failures),
        )


if __name__ == "__main__":
    unittest.main()
