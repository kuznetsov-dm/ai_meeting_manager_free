from __future__ import annotations

import json
import logging
import os
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Dict

from aimn.core.atomic_io import atomic_write_text
from aimn.core.release_profile import resolve_release_config_path
from aimn.core.secret_crypto import decrypt_secret, encrypt_secret


class SettingsStore:
    def __init__(self, base_dir: Path, *, repo_root: Path | None = None) -> None:
        self._base_dir = base_dir
        self._settings_dir = base_dir / "plugins"
        self._secrets_dir = base_dir / "secrets"
        resolved_root = repo_root or base_dir.parent.parent
        self._secrets_store = SecretsStore(resolved_root)
        self._legacy_settings_dir = resolved_root / "output" / "settings" / "plugins"

    def get_settings(self, plugin_id: str, *, include_secrets: bool = False) -> Dict[str, object]:
        path = self._settings_path(plugin_id)
        if not path.exists():
            release_default = resolve_release_config_path(
                Path("settings") / "plugins" / f"{plugin_id}.json",
                fallback_path=path,
            )
            if release_default.exists() and release_default != path:
                path = release_default
            else:
                legacy = self._legacy_settings_dir / f"{plugin_id}.json"
                if legacy.exists():
                    path = legacy
                else:
                    settings = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logging.getLogger("aimn.settings").warning(
                    "settings_parse_failed path=%s error=%s", path, exc
                )
                raw = {}
            settings = raw if isinstance(raw, dict) else {}
        else:
            settings = {}
        if include_secrets:
            settings = dict(settings)
            settings.update(self._read_secrets(plugin_id))
        return settings

    def get_secret_flags(self, plugin_id: str) -> Dict[str, bool]:
        secrets = self._read_secrets(plugin_id)
        return {key: True for key in secrets}

    def set_settings(
        self,
        plugin_id: str,
        settings: Dict[str, object],
        *,
        secret_fields: Iterable[str],
        preserve_secrets: Iterable[str],
    ) -> None:
        secret_keys = {str(key) for key in secret_fields}
        preserve = {str(key) for key in preserve_secrets}
        secrets = self._read_secrets(plugin_id)
        plain: Dict[str, object] = {}

        for key, value in settings.items():
            if key in secret_keys:
                if value:
                    secrets[key] = str(value)
                elif key not in preserve and key in secrets:
                    del secrets[key]
            else:
                plain[key] = value

        self._settings_dir.mkdir(parents=True, exist_ok=True)
        path = self._settings_path(plugin_id)
        atomic_write_text(
            path,
            json.dumps(plain, ensure_ascii=True, indent=2, sort_keys=True),
        )

        self._secrets_store.set_plugin_secrets(
            plugin_id,
            secrets,
            secret_fields=secret_keys,
            preserve_secrets=preserve,
        )

    def _settings_path(self, plugin_id: str) -> Path:
        return self._settings_dir / f"{plugin_id}.json"

    def _secrets_path(self, plugin_id: str) -> Path:
        return self._secrets_dir / f"{plugin_id}.json"

    def _read_secrets(self, plugin_id: str) -> Dict[str, str]:
        secrets = self._secrets_store.get_plugin_secrets(plugin_id)
        if secrets:
            return secrets
        if self._secrets_store.exists():
            return {}
        path = self._secrets_path(plugin_id)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.getLogger("aimn.settings").warning(
                "secrets_parse_failed path=%s error=%s", path, exc
            )
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items() if value is not None}


class SecretsStore:
    def __init__(self, repo_root: Path) -> None:
        self._path = repo_root / "config" / "secrets.toml"

    def exists(self) -> bool:
        return self._path.exists()

    def get_plugin_secrets(self, plugin_id: str) -> Dict[str, str]:
        data = self._load()
        if not data:
            data = {}
        secrets: Dict[str, str] = {}
        for prefix in self._prefix_aliases(plugin_id):
            for key, value in data.items():
                if not key.startswith(f"{prefix}_"):
                    continue
                field = key[len(prefix) + 1 :]
                if field not in secrets:
                    secrets[field] = decrypt_secret(str(value))
            env_secrets = self._env_secrets(prefix)
            if env_secrets:
                for field, value in env_secrets.items():
                    if field not in secrets:
                        secrets[field] = value
        # Compatibility aliases:
        # - Some plugins use user_api_key/paid_api_key fields, but env vars and older configs often use user_key/paid_key.
        # - Some code paths also look for api_key.
        if "user_api_key" not in secrets and "user_key" in secrets:
            secrets["user_api_key"] = secrets["user_key"]
        if "paid_api_key" not in secrets and "paid_key" in secrets:
            secrets["paid_api_key"] = secrets["paid_key"]
        if "api_key" not in secrets and "user_api_key" in secrets:
            secrets["api_key"] = secrets["user_api_key"]
        return secrets

    def set_plugin_secrets(
        self,
        plugin_id: str,
        secrets: Dict[str, str],
        *,
        secret_fields: Iterable[str],
        preserve_secrets: Iterable[str],
    ) -> None:
        data = self._load()
        secret_keys = {str(key) for key in secret_fields}
        preserve = {str(key) for key in preserve_secrets}
        for field in secret_keys:
            keys = self._secret_keys_for_field(plugin_id, field)
            value = secrets.get(field)
            if value:
                for key in keys:
                    data[key] = encrypt_secret(str(value))
            else:
                for key in keys:
                    if field not in preserve and key in data:
                        del data[key]
        self._write(data)

    def _load(self) -> Dict[str, object]:
        if not self._path.exists():
            return {}
        try:
            raw = tomllib.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.getLogger("aimn.settings").warning(
                "secrets_parse_failed path=%s error=%s", self._path, exc
            )
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw

    def _write(self, data: Dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = _dump_flat_toml(data)
        atomic_write_text(self._path, payload)

    @staticmethod
    def _prefix(plugin_id: str) -> str:
        raw = str(plugin_id or "").strip().lower()
        chars = [ch if ch.isalnum() else "_" for ch in raw]
        prefix = "".join(chars).strip("_")
        return prefix or "plugin"

    def _secret_keys_for_field(self, plugin_id: str, field_id: str) -> list[str]:
        prefix = self._prefix(plugin_id)
        return [f"{prefix}_{field_id}"]

    @classmethod
    def _prefix_aliases(cls, plugin_id: str) -> list[str]:
        aliases = [cls._prefix(plugin_id)]
        raw = str(plugin_id or "").strip()
        if "." in raw:
            legacy = raw.split(".", 1)[1].strip().lower()
            legacy = "".join(ch if ch.isalnum() else "_" for ch in legacy).strip("_")
            if legacy and legacy not in aliases:
                aliases.append(legacy)
        return aliases

    @staticmethod
    def _env_secrets(prefix: str) -> Dict[str, str]:
        secrets: Dict[str, str] = {}
        env_prefix = f"AIMN_{prefix.upper()}_"
        for key, value in os.environ.items():
            if not key.startswith(env_prefix):
                continue
            field = key[len(env_prefix) :].lower()
            if not value:
                continue
            secrets[field] = value
        return secrets


def _dump_flat_toml(data: Dict[str, object]) -> str:
    lines = ["# Local secrets (do not commit)"]
    for key in sorted(data.keys()):
        value = data[key]
        if isinstance(value, bool):
            encoded = "true" if value else "false"
        elif isinstance(value, (int, float)):
            encoded = str(value)
        else:
            encoded = json.dumps(str(value))
        lines.append(f"{key} = {encoded}")
    return "\n".join(lines) + "\n"
