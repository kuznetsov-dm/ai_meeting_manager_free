from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from aimn.core.release_profile import resolve_release_config_path

_UI_PATH_PREFERENCES_SETTINGS_ID = "ui.path_preferences"


def get_repo_root() -> Path:
    bundle_root = os.environ.get("AIMN_BUNDLE_ROOT", "").strip()
    if bundle_root:
        return Path(bundle_root).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def get_app_root() -> Path:
    raw = os.environ.get("AIMN_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return get_repo_root()


def get_output_dir(app_root: Path | None = None) -> Path:
    raw = os.environ.get("AIMN_OUTPUT_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    root = app_root or get_app_root()
    configured = _configured_directory(root, "default_output_dir")
    return configured or (root / "output")


def get_default_input_dir(app_root: Path | None = None) -> Path | None:
    raw = os.environ.get("AIMN_INPUT_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    root = app_root or get_app_root()
    return _configured_directory(root, "default_input_dir")


def is_input_monitoring_enabled(app_root: Path | None = None) -> bool:
    root = app_root or get_app_root()
    payload = _load_path_preferences(root)
    value = payload.get("monitor_input_dir")
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def get_config_dir(app_root: Path | None = None) -> Path:
    root = app_root or get_app_root()
    return root / "config"


def get_plugins_dir(app_root: Path | None = None) -> Path:
    raw = os.environ.get("AIMN_PLUGINS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    root = app_root or get_app_root()
    return root / "plugins"


def get_installed_plugins_dir(app_root: Path | None = None) -> Path:
    raw = os.environ.get("AIMN_INSTALLED_PLUGINS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    root = app_root or get_app_root()
    return get_config_dir(root) / "plugins_installed"


def get_plugin_distribution_path(app_root: Path | None = None) -> Path:
    local_path = get_config_dir(app_root) / "plugin_distribution.json"
    return _protected_release_config_path("plugin_distribution.json", local_path)


def get_plugin_entitlements_path(app_root: Path | None = None) -> Path:
    local_path = get_config_dir(app_root) / "plugin_entitlements.json"
    if local_path.exists():
        return local_path
    return resolve_release_config_path("plugin_entitlements.json", fallback_path=local_path)


def get_plugin_remote_catalog_path(app_root: Path | None = None) -> Path:
    local_path = get_config_dir(app_root) / "plugin_catalog.json"
    if local_path.exists():
        return local_path
    return resolve_release_config_path("plugin_catalog.json", fallback_path=local_path)


def get_plugin_trust_policy_path(app_root: Path | None = None) -> Path:
    local_path = get_config_dir(app_root) / "plugin_trust_policy.json"
    return _protected_release_config_path("plugin_trust_policy.json", local_path)


def get_plugin_sync_config_path(app_root: Path | None = None) -> Path:
    return get_config_dir(app_root) / "plugin_sync.json"


def get_installed_plugins_state_path(app_root: Path | None = None) -> Path:
    return get_config_dir(app_root) / "installed_plugins.json"


def get_plugin_activation_path(app_root: Path | None = None) -> Path:
    return get_config_dir(app_root) / "plugin_activation.json"


def _protected_release_config_path(relative_path: str, local_path: Path) -> Path:
    release_path = resolve_release_config_path(relative_path, fallback_path=local_path)
    if release_path != local_path and release_path.exists():
        return release_path
    return local_path


def get_plugin_roots(app_root: Path | None = None) -> tuple[Path, ...]:
    roots = [get_installed_plugins_dir(app_root), get_plugins_dir(app_root)]
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return tuple(unique)


def _configured_directory(app_root: Path, key: str) -> Path | None:
    payload = _load_path_preferences(app_root)
    raw = str(payload.get(str(key), "") or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (app_root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _load_path_preferences(app_root: Path) -> dict[str, object]:
    path = get_config_dir(app_root) / "settings" / "plugins" / f"{_UI_PATH_PREFERENCES_SETTINGS_ID}.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


@dataclass(frozen=True)
class AppPaths:
    app_root: Path
    repo_root: Path
    config_dir: Path
    output_dir: Path
    plugins_dir: Path
    installed_plugins_dir: Path

    @classmethod
    def resolve(cls, app_root: Path | None = None) -> AppPaths:
        root = app_root or get_app_root()
        return cls(
            app_root=root,
            repo_root=get_repo_root(),
            config_dir=get_config_dir(root),
            output_dir=get_output_dir(root),
            plugins_dir=get_plugins_dir(root),
            installed_plugins_dir=get_installed_plugins_dir(root),
        )
