from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from aimn.core.atomic_io import atomic_write_text
from aimn.core.release_profile import (
    release_supports_pipeline_preset,
    resolve_release_config_path,
    sanitize_pipeline_payload,
)

class PipelineSettingsStore:
    def __init__(self, base_dir: Path, *, repo_root: Path | None = None) -> None:
        self._pipeline_dir = base_dir / "pipeline"
        self._runtime_dir = base_dir.parent.parent / "output" / "settings" / "pipeline"
        self._active_path = self._pipeline_dir / "active.json"
        self._repo_root = repo_root

    def load(self, preset: str = "default") -> Dict[str, object]:
        data, _source, _path = self.load_with_source(preset)
        return data

    def load_with_source(self, preset: str = "default") -> tuple[Dict[str, object], str, Path | None]:
        data, source, path, _overrides = self.load_with_overrides(preset)
        return data, source, path

    def load_with_overrides(
        self, preset: str = "default"
    ) -> tuple[Dict[str, object], str, Path | None, list[str]]:
        safe_preset = self._normalize_preset_id(preset)
        config_path = self._path_for(safe_preset)
        if not config_path.exists():
            config_path = resolve_release_config_path(
                Path("settings") / "pipeline" / f"{safe_preset}.json",
                repo_root=self._repo_root,
                fallback_path=config_path,
            )
        runtime_path = self._runtime_path_for(safe_preset)
        runtime_data, runtime_status = _read_json(runtime_path)
        config_data, config_status = _read_json(config_path)
        sanitized_config = sanitize_pipeline_payload(config_data or {}, preset=safe_preset, repo_root=self._repo_root)
        sanitized_runtime = sanitize_pipeline_payload(runtime_data or {}, preset=safe_preset, repo_root=self._repo_root)

        if runtime_status == "ok":
            overrides = _diff_paths(sanitized_config or {}, sanitized_runtime or {}) if config_status == "ok" else []
            return sanitized_runtime or {}, "runtime", runtime_path, overrides
        if runtime_status == "invalid":
            return {}, "invalid", runtime_path, []
        if config_status == "ok":
            return sanitized_config or {}, "config", config_path, []
        if config_status == "invalid":
            return {}, "invalid", config_path, []
        return {}, "missing", None, []

    def save(self, preset: str, data: Dict[str, object]) -> None:
        self._pipeline_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(preset)
        payload = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)
        atomic_write_text(path, payload)

    def load_active_preset(self) -> str:
        active_path = self._active_path
        if not active_path.exists():
            active_path = resolve_release_config_path(
                Path("settings") / "pipeline" / "active.json",
                repo_root=self._repo_root,
                fallback_path=self._active_path,
            )
            if not active_path.exists():
                return "default"
        try:
            raw = json.loads(active_path.read_text(encoding="utf-8"))
        except Exception:
            return "default"
        if isinstance(raw, dict):
            preset = str(raw.get("preset", "")).strip()
            return self._normalize_preset_id(preset)
        if isinstance(raw, str):
            return self._normalize_preset_id(raw)
        return "default"

    def save_active_preset(self, preset: str) -> None:
        self._pipeline_dir.mkdir(parents=True, exist_ok=True)
        value = preset.strip() or "default"
        payload = json.dumps({"preset": value}, ensure_ascii=True, indent=2, sort_keys=True)
        atomic_write_text(self._active_path, payload)

    def _path_for(self, preset: str) -> Path:
        safe = preset.strip() or "default"
        return self._pipeline_dir / f"{safe}.json"

    def _runtime_path_for(self, preset: str) -> Path:
        safe = preset.strip() or "default"
        return self._runtime_dir / f"{safe}.json"

    def _normalize_preset_id(self, preset: str) -> str:
        safe = str(preset or "").strip() or "default"
        if release_supports_pipeline_preset(
            safe,
            repo_root=self._repo_root,
            include_runtime=True,
            base_dir=self._pipeline_dir.parent,
        ):
            return safe
        return "default"


def _read_json(path: Path) -> tuple[Dict[str, object] | None, str]:
    if not path.exists():
        return None, "missing"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, "invalid"
    return (raw if isinstance(raw, dict) else {}), "ok"


def _diff_paths(base: Dict[str, object], override: Dict[str, object], prefix: str = "") -> list[str]:
    diffs: list[str] = []
    keys = set(base.keys()) | set(override.keys())
    for key in sorted(keys):
        path = f"{prefix}.{key}" if prefix else str(key)
        left = base.get(key)
        right = override.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            diffs.extend(_diff_paths(left, right, path))
        else:
            if left != right:
                diffs.append(path)
    return diffs
