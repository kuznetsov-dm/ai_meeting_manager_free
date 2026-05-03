from __future__ import annotations

import copy
import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReleaseProfile:
    profile_id: str
    manifest_path: Path | None
    payload: dict[str, Any]

    @property
    def active(self) -> bool:
        return self.profile_id != "default"

    def ui_flag(self, key: str, default: bool = True) -> bool:
        flags = self.payload.get("ui_flags")
        if not isinstance(flags, dict):
            return bool(default)
        value = flags.get(str(key))
        if isinstance(value, bool):
            return value
        return bool(default)

    def package_management_enabled(self) -> bool:
        return self.ui_flag("allow_plugin_package_install", True)

    def management_tab_visible(self) -> bool:
        return self.ui_flag("show_management_tab", True)

    def plugin_marketplace_visible(self) -> bool:
        return self.ui_flag("show_plugin_marketplace", True)

    def bundled_plugin_ids(self) -> tuple[str, ...]:
        items = self.payload.get("bundled_plugins")
        if not isinstance(items, list):
            return ()
        values = [str(item or "").strip() for item in items if str(item or "").strip()]
        return tuple(values)

    def first_run_wizard(self) -> dict[str, Any]:
        payload = self.payload.get("first_run_wizard")
        return dict(payload) if isinstance(payload, dict) else {}


def active_release_profile(app_root: Path | None = None) -> ReleaseProfile:
    raw = os.environ.get("AIMN_RELEASE_PROFILE", "").strip()
    profile_id = raw or "default"
    if profile_id == "default":
        return ReleaseProfile(profile_id="default", manifest_path=None, payload={})

    manifest_path = _repo_root() / "releases" / profile_id / "manifest.json"
    payload = _load_json_object(manifest_path)
    return ReleaseProfile(profile_id=profile_id, manifest_path=manifest_path, payload=payload)


def release_root(profile_id: str, *, repo_root: Path | None = None) -> Path | None:
    rid = str(profile_id or "").strip()
    if not rid or rid == "default":
        return None
    root = repo_root or _repo_root()
    path = root / "releases" / rid
    return path if path.exists() else None


def release_config_dir(profile_id: str, *, repo_root: Path | None = None) -> Path | None:
    root = release_root(profile_id, repo_root=repo_root)
    if root is None:
        return None
    path = root / "config"
    return path if path.exists() else None


def active_release_config_dir(*, repo_root: Path | None = None) -> Path | None:
    profile = active_release_profile()
    return release_config_dir(profile.profile_id, repo_root=repo_root)


def resolve_release_config_path(
    relative_path: str | Path,
    *,
    repo_root: Path | None = None,
    fallback_path: Path | None = None,
) -> Path:
    rel = Path(relative_path)
    profile_config_dir = active_release_config_dir(repo_root=repo_root)
    if profile_config_dir is not None:
        candidate = profile_config_dir / rel
        if candidate.exists():
            return candidate
    if fallback_path is not None:
        return fallback_path
    base = repo_root or _repo_root()
    return base / "config" / rel


def release_bundled_plugin_ids(*, repo_root: Path | None = None) -> tuple[str, ...]:
    profile = active_release_profile()
    if not profile.active:
        return ()
    manifest = _load_release_manifest(profile.profile_id, repo_root=repo_root)
    items = manifest.get("bundled_plugins")
    if not isinstance(items, list):
        return ()
    values = [str(item or "").strip() for item in items if str(item or "").strip()]
    return tuple(values)


def load_release_registry_defaults(*, repo_root: Path | None = None) -> dict[str, Any]:
    profile = active_release_profile()
    config_dir = release_config_dir(profile.profile_id, repo_root=repo_root)
    if config_dir is None:
        return {}
    path = config_dir / "plugins.toml"
    return _load_toml_object(path)


def load_release_pipeline_defaults(
    preset: str = "default",
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    profile = active_release_profile()
    config_dir = release_config_dir(profile.profile_id, repo_root=repo_root)
    if config_dir is None:
        return {}
    safe = str(preset or "").strip() or "default"
    pipeline_dir = config_dir / "settings" / "pipeline"
    path = pipeline_dir / f"{safe}.json"
    if not path.exists() and safe != "default":
        path = pipeline_dir / "default.json"
    return _load_json_object(path)


def sanitize_registry_payload(payload: dict[str, Any], *, repo_root: Path | None = None) -> dict[str, Any]:
    defaults = load_release_registry_defaults(repo_root=repo_root)
    if not defaults:
        return dict(payload) if isinstance(payload, dict) else {}
    incoming = dict(payload) if isinstance(payload, dict) else {}
    return _sanitize_release_payload(defaults, incoming)


def sanitize_pipeline_payload(
    payload: dict[str, Any],
    *,
    preset: str = "default",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    defaults = load_release_pipeline_defaults(preset, repo_root=repo_root)
    if not defaults:
        return dict(payload) if isinstance(payload, dict) else {}
    incoming = dict(payload) if isinstance(payload, dict) else {}
    sanitized = _sanitize_release_payload(defaults, incoming)
    pipeline = sanitized.get("pipeline")
    if not isinstance(pipeline, dict):
        pipeline = {}
        sanitized["pipeline"] = pipeline
    pipeline["preset"] = str(preset or "").strip() or "default"
    return sanitized


def release_supports_pipeline_preset(
    preset: str = "default",
    *,
    repo_root: Path | None = None,
    include_runtime: bool = False,
    base_dir: Path | None = None,
) -> bool:
    safe = str(preset or "").strip() or "default"
    release_defaults = load_release_pipeline_defaults(safe, repo_root=repo_root)
    if release_defaults:
        return True
    if base_dir is not None:
        local_path = Path(base_dir) / "pipeline" / f"{safe}.json"
        if local_path.exists():
            return True
        if include_runtime:
            runtime_path = Path(base_dir).parent.parent / "output" / "settings" / "pipeline" / f"{safe}.json"
            if runtime_path.exists():
                return True
    return False


def _repo_root() -> Path:
    bundle_root = os.environ.get("AIMN_BUNDLE_ROOT", "").strip()
    if bundle_root:
        return Path(bundle_root).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def _load_release_manifest(profile_id: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    manifest_path = root / "releases" / str(profile_id or "").strip() / "manifest.json"
    return _load_json_object(manifest_path)


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _load_toml_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _sanitize_release_payload(defaults: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(defaults if isinstance(defaults, dict) else {})
    if not isinstance(incoming, dict) or not incoming:
        return result

    result["allowlist"] = _copy_allowlist(defaults)
    result["disabled"] = {"ids": []}
    result.pop("enabled", None)

    incoming_pipeline = incoming.get("pipeline")
    if isinstance(incoming_pipeline, dict):
        target_pipeline = result.get("pipeline")
        if not isinstance(target_pipeline, dict):
            target_pipeline = {}
            result["pipeline"] = target_pipeline
        retries = incoming_pipeline.get("optional_stage_retries")
        if isinstance(retries, int):
            target_pipeline["optional_stage_retries"] = max(0, retries)

    incoming_global = incoming.get("global_settings")
    if isinstance(incoming_global, dict):
        current = result.get("global_settings")
        base = dict(current) if isinstance(current, dict) else {}
        base.update(copy.deepcopy(incoming_global))
        result["global_settings"] = base

    incoming_plugin_config = incoming.get("plugin_config")
    default_plugin_config = result.get("plugin_config")
    if isinstance(incoming_plugin_config, dict):
        merged_plugin_config = dict(default_plugin_config) if isinstance(default_plugin_config, dict) else {}
        allowed_plugin_ids = set(_allowlist_ids(result))
        for plugin_id, value in incoming_plugin_config.items():
            pid = str(plugin_id or "").strip()
            if not pid or pid not in allowed_plugin_ids or not isinstance(value, dict):
                continue
            existing = merged_plugin_config.get(pid)
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(copy.deepcopy(value))
            merged_plugin_config[pid] = merged
        if merged_plugin_config:
            result["plugin_config"] = merged_plugin_config

    default_stages = result.get("stages")
    incoming_stages = incoming.get("stages")
    if isinstance(default_stages, dict) and isinstance(incoming_stages, dict):
        merged_stages: dict[str, Any] = {}
        for stage_id, default_stage in default_stages.items():
            sid = str(stage_id or "").strip()
            if not sid:
                continue
            merged_stages[sid] = _merge_stage_overrides(
                default_stage if isinstance(default_stage, dict) else {},
                incoming_stages.get(stage_id),
            )
        result["stages"] = merged_stages

    return result


def _copy_allowlist(defaults: dict[str, Any]) -> dict[str, list[str]]:
    ids = _allowlist_ids(defaults)
    return {"ids": ids}


def _allowlist_ids(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("allowlist") if isinstance(payload, dict) else None
    ids = raw.get("ids") if isinstance(raw, dict) else raw
    if not isinstance(ids, list):
        return []
    return [str(item or "").strip() for item in ids if str(item or "").strip()]


def _merge_stage_overrides(default_stage: dict[str, Any], incoming_stage: object) -> dict[str, Any]:
    result = copy.deepcopy(default_stage if isinstance(default_stage, dict) else {})
    if not isinstance(incoming_stage, dict):
        return result
    incoming_params = incoming_stage.get("params")
    if isinstance(incoming_params, dict):
        target = result.get("params")
        base = dict(target) if isinstance(target, dict) else {}
        base.update(copy.deepcopy(incoming_params))
        result["params"] = base
    for key in ("plugin_ids", "variants"):
        if key in result and key not in incoming_stage:
            continue
    return result
