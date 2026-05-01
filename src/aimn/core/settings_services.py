from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aimn.core.pipeline_presets import offline_preset_config
from aimn.core.pipeline_settings import PipelineSettingsStore
from aimn.core.settings_store import SettingsStore


@dataclass
class PipelinePresetSnapshot:
    preset_id: str
    config_data: dict
    source: str
    path: Path | None
    overrides: list[str]


class PipelinePresetService:
    def __init__(self, config_dir: Path, *, repo_root: Path) -> None:
        self._store = PipelineSettingsStore(config_dir, repo_root=repo_root)
        self._repo_root = repo_root

    def active_preset(self) -> str:
        return self._store.load_active_preset()

    def load(self, preset_id: str) -> PipelinePresetSnapshot:
        config_data, source, path, overrides = self._store.load_with_overrides(preset_id)
        return PipelinePresetSnapshot(
            preset_id=preset_id,
            config_data=config_data,
            source=str(source or ""),
            path=path,
            overrides=overrides if isinstance(overrides, list) else [],
        )

    def save(self, preset_id: str, config_data: dict) -> None:
        self._store.save(preset_id, config_data)

    def save_active_preset(self, preset_id: str) -> None:
        self._store.save_active_preset(preset_id)

    def offline_config(self, optional_stage_retries: int = 1) -> dict:
        return offline_preset_config(self._repo_root, optional_stage_retries)


class SettingsService:
    def __init__(self, settings_dir: Path, *, repo_root: Path) -> None:
        self._store = SettingsStore(settings_dir, repo_root=repo_root)

    def get_settings(self, plugin_id: str, *, include_secrets: bool = True) -> dict:
        payload = self._store.get_settings(plugin_id, include_secrets=include_secrets)
        return payload if isinstance(payload, dict) else {}

    def set_settings(
        self,
        plugin_id: str,
        values: dict,
        *,
        secret_fields: list[str] | None = None,
        preserve_secrets: list[str] | None = None,
    ) -> None:
        self._store.set_settings(
            plugin_id,
            values,
            secret_fields=secret_fields or [],
            preserve_secrets=preserve_secrets or [],
        )

    def read(self, plugin_id: str, key: str, *, default: Any = None) -> Any:
        payload = self.get_settings(plugin_id, include_secrets=True)
        return payload.get(key, default)

    def get_secret_flags(self, plugin_id: str) -> dict[str, bool]:
        payload = self._store.get_secret_flags(plugin_id)
        return payload if isinstance(payload, dict) else {}

    def get_secret(self, plugin_id: str, key: str, *, default: str | None = None) -> str | None:
        payload = self.get_settings(plugin_id, include_secrets=True)
        value = payload.get(str(key or "").strip())
        if value is None:
            return default
        return str(value)

    def set_secret(self, plugin_id: str, key: str, value: str | None) -> None:
        field = str(key or "").strip()
        if not field:
            return
        payload = self.get_settings(plugin_id, include_secrets=False)
        if value is None or not str(value).strip():
            payload[field] = ""
        else:
            payload[field] = str(value)
        self._store.set_settings(
            plugin_id,
            payload,
            secret_fields=[field],
            preserve_secrets=[],
        )
