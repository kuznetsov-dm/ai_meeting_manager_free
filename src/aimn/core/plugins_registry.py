from __future__ import annotations

import json
import logging
import tomllib
from collections.abc import Iterable
from pathlib import Path

from aimn.core.plugins_config import PluginsConfig
from aimn.core.release_profile import resolve_release_config_path, sanitize_registry_payload


def ensure_plugins_enabled(payload: dict, plugin_ids: Iterable[str]) -> dict:
    data = dict(payload) if isinstance(payload, dict) else {}
    ids = {str(pid) for pid in plugin_ids if str(pid)}
    if not ids:
        return data
    for plugin_id in sorted(ids):
        data = set_plugin_enabled(data, plugin_id, True)
    return data


def set_plugin_enabled(payload: dict, plugin_id: str, enabled: bool) -> dict:
    data = dict(payload) if isinstance(payload, dict) else {}
    pid = str(plugin_id or "").strip()
    if not pid:
        return data

    enabled_ids, enabled_wrapped = _extract_ids(data.get("enabled"))
    if enabled_ids or enabled_wrapped:
        current = set(enabled_ids)
        if enabled:
            current.add(pid)
        else:
            current.discard(pid)
        merged = sorted(current)
        data["enabled"] = {"ids": merged} if enabled_wrapped else merged
        return data

    allowlist, allowlist_wrapped = _extract_ids(data.get("allowlist"))
    if allowlist or allowlist_wrapped:
        current = set(allowlist)
        if enabled:
            current.add(pid)
        else:
            current.discard(pid)
        merged = sorted(current)
        data["allowlist"] = {"ids": merged} if allowlist_wrapped else merged
        return data

    disabled, disabled_wrapped = _extract_ids(data.get("disabled"))
    current = set(disabled)
    if enabled:
        current.discard(pid)
    else:
        current.add(pid)
    merged = sorted(current)
    data["disabled"] = {"ids": merged} if disabled_wrapped else merged
    return data


def _extract_ids(value: object) -> tuple[list[str], bool]:
    if isinstance(value, dict):
        ids = value.get("ids")
        if isinstance(ids, list):
            return [str(item) for item in ids if str(item)], True
        return [], True
    if isinstance(value, list):
        return [str(item) for item in value if str(item)], False
    return [], False


def load_registry_payload(repo_root: Path) -> tuple[dict, str, Path | None]:
    runtime_path, user_path, default_path = _registry_paths(repo_root)
    logger = logging.getLogger("aimn.registry")

    for path, source in (
        (runtime_path, "runtime"),
        (user_path, "user"),
    ):
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("registry_parse_failed path=%s error=%s", path, exc)
            continue
        payload = raw if isinstance(raw, dict) else {}
        return sanitize_registry_payload(payload, repo_root=repo_root), source, path

    if default_path.exists():
        try:
            raw = tomllib.loads(default_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("registry_parse_failed path=%s error=%s", default_path, exc)
            return {}, "invalid", default_path
        payload = raw if isinstance(raw, dict) else {}
        return sanitize_registry_payload(payload, repo_root=repo_root), "default", default_path

    return {}, "missing", None


def load_registry_config(repo_root: Path) -> PluginsConfig:
    payload, _source, _path = load_registry_payload(repo_root)
    return PluginsConfig(payload)


def registry_write_path(repo_root: Path) -> Path:
    runtime_path, _user_path, _default_path = _registry_paths(repo_root)
    return runtime_path


def _registry_paths(repo_root: Path) -> tuple[Path, Path, Path]:
    runtime_path = repo_root / "output" / "settings" / "plugins.json"
    user_path = repo_root / "plugins.json"
    default_path = resolve_release_config_path(
        "plugins.toml",
        repo_root=repo_root,
        fallback_path=repo_root / "config" / "plugins.toml",
    )
    return runtime_path, user_path, default_path
