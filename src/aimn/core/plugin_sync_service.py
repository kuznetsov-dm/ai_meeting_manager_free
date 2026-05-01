from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname, urlopen

from aimn.core.app_paths import (
    get_config_dir,
    get_plugin_sync_config_path,
)
from aimn.core.atomic_io import atomic_write_text
from aimn.core.plugin_entitlements_service import PluginEntitlementsService
from aimn.core.plugin_remote_catalog import load_remote_catalog

_MAX_SYNC_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class PluginCatalogSyncResult:
    source: str
    path: Path
    plugin_count: int


@dataclass(frozen=True)
class PluginEntitlementImportResult:
    source: str
    path: Path
    verified: bool
    reason: str
    platform_edition_enabled: bool


class PluginSyncService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._config_path = get_plugin_sync_config_path(app_root)
        self._config = _load_json_object(self._config_path)
        self._config_dir = get_config_dir(app_root)

    def sync_catalog(self, source: str = "") -> PluginCatalogSyncResult:
        resolved_source = str(source or self._config.get("catalog_url", "") or "").strip()
        if not resolved_source:
            raise ValueError("plugin_catalog_sync_source_missing")
        payload = self._fetch_json_object(resolved_source)
        plugins = payload.get("plugins")
        if not isinstance(plugins, list):
            raise ValueError("plugin_catalog_sync_invalid_payload")
        target_path = self._config_dir / "plugin_catalog.json"
        atomic_write_text(
            target_path,
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        )
        plugin_count = len(load_remote_catalog(target_path))
        return PluginCatalogSyncResult(
            source=resolved_source,
            path=target_path,
            plugin_count=plugin_count,
        )

    def sync_entitlements(self, source: str = "") -> PluginEntitlementImportResult:
        resolved_source = str(source or self._config.get("entitlements_url", "") or "").strip()
        if not resolved_source:
            raise ValueError("plugin_entitlements_sync_source_missing")
        payload = self._fetch_json_object(resolved_source)
        return self._write_entitlements_payload(payload, source=resolved_source)

    def import_entitlements(self, source: Path | str) -> PluginEntitlementImportResult:
        resolved_source = str(source or "").strip()
        if not resolved_source:
            raise ValueError("plugin_entitlements_import_source_missing")
        payload = self._fetch_json_object(resolved_source)
        return self._write_entitlements_payload(payload, source=resolved_source)

    def _write_entitlements_payload(
        self,
        payload: dict,
        *,
        source: str,
    ) -> PluginEntitlementImportResult:
        target_path = self._config_dir / "plugin_entitlements.json"
        service = PluginEntitlementsService(self._app_root)
        snapshot = service.validate_payload(payload)
        if _contains_pro_entitlements(payload) and not snapshot.verified:
            raise ValueError(f"plugin_entitlements_import_invalid:{snapshot.reason}")
        atomic_write_text(
            target_path,
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        )
        return PluginEntitlementImportResult(
            source=source,
            path=target_path,
            verified=snapshot.verified,
            reason=snapshot.reason,
            platform_edition_enabled=bool(
                isinstance(snapshot.payload.get("platform_edition"), dict)
                and snapshot.payload.get("platform_edition", {}).get("enabled", False)
            ),
        )

    def _fetch_json_object(self, source: str) -> dict:
        raw_text = self._read_source_text(source)
        try:
            payload = json.loads(raw_text)
        except Exception as exc:
            raise ValueError(f"plugin_sync_json_invalid:{exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("plugin_sync_payload_invalid")
        return payload

    def _read_source_text(self, source: str) -> str:
        raw = str(source or "").strip()
        if not raw:
            raise ValueError("plugin_sync_source_missing")
        local_candidate = Path(raw).expanduser()
        if local_candidate.exists() and local_candidate.is_file():
            return local_candidate.read_text(encoding="utf-8")
        parsed = urlparse(raw)
        if parsed.scheme in {"", "file"}:
            if parsed.scheme == "file":
                local_path = Path(url2pathname(f"{parsed.netloc}{parsed.path}")).expanduser().resolve()
            else:
                local_path = Path(raw).expanduser().resolve()
            if not local_path.exists():
                raise FileNotFoundError(f"plugin_sync_source_missing:{raw}")
            return local_path.read_text(encoding="utf-8")
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"plugin_sync_scheme_invalid:{parsed.scheme}")
        with urlopen(raw) as response:
            body = response.read(_MAX_SYNC_BYTES + 1)
        if len(body) > _MAX_SYNC_BYTES:
            raise ValueError("plugin_sync_payload_too_large")
        return body.decode("utf-8")


def _load_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _contains_pro_entitlements(payload: dict) -> bool:
    platform = payload.get("platform_edition")
    if isinstance(platform, dict) and bool(platform.get("enabled", False)):
        return True
    plugins = payload.get("plugins")
    if not isinstance(plugins, dict):
        return False
    for item in plugins.values():
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "") or "").strip().lower() in {"active", "grace"}:
            return True
    return False
