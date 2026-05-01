from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RemotePluginCatalogEntry:
    plugin_id: str
    version: str
    api_version: str
    stage_id: str
    owner_type: str
    publisher_id: str
    pricing_model: str
    requires_platform_edition: bool
    catalog_enabled: bool
    compatible_app_versions: list[str] = field(default_factory=list)
    download_url: str = ""
    checksum_sha256: str = ""
    signature: str = ""
    signature_algorithm: str = ""
    signing_key_id: str = ""
    manifest_url: str = ""
    product_name: str = ""
    name: str = ""
    highlights: str = ""
    description: str = ""
    icon_key: str = ""
    provider_name: str = ""
    provider_description: str = ""
    default_visibility: str = "visible"
    tags: list[str] = field(default_factory=list)
    howto: list[str] = field(default_factory=list)
    billing_product_id: str = ""
    fallback_plugin_id: str = ""


def load_remote_catalog(path: Path) -> list[RemotePluginCatalogEntry]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    plugins = raw.get("plugins") if isinstance(raw, dict) else None
    if not isinstance(plugins, list):
        return []
    entries: list[RemotePluginCatalogEntry] = []
    seen: set[str] = set()
    for item in plugins:
        entry = _coerce_entry(item)
        if not entry or entry.plugin_id in seen:
            continue
        seen.add(entry.plugin_id)
        entries.append(entry)
    return entries


def _coerce_entry(raw: object) -> RemotePluginCatalogEntry | None:
    if not isinstance(raw, dict):
        return None
    plugin_id = str(raw.get("plugin_id", "") or "").strip()
    version = str(raw.get("version", "") or "").strip()
    api_version = str(raw.get("api_version", "") or "").strip() or "1"
    stage_id = str(raw.get("stage_id", "") or "").strip() or "other"
    if not plugin_id or not version:
        return None
    return RemotePluginCatalogEntry(
        plugin_id=plugin_id,
        version=version,
        api_version=api_version,
        stage_id=stage_id,
        owner_type=str(raw.get("owner_type", "") or "").strip() or "third_party",
        publisher_id=str(raw.get("publisher_id", "") or "").strip(),
        pricing_model=str(raw.get("pricing_model", "") or "").strip() or "free",
        requires_platform_edition=bool(raw.get("requires_platform_edition", False)),
        catalog_enabled=bool(raw.get("catalog_enabled", True)),
        compatible_app_versions=_list_of_str(raw.get("compatible_app_versions")),
        download_url=str(raw.get("download_url", "") or "").strip(),
        checksum_sha256=str(raw.get("checksum_sha256", "") or "").strip(),
        signature=str(raw.get("signature", "") or "").strip(),
        signature_algorithm=str(raw.get("signature_algorithm", "") or "").strip().lower(),
        signing_key_id=str(raw.get("signing_key_id", "") or "").strip(),
        manifest_url=str(raw.get("manifest_url", "") or "").strip(),
        product_name=str(raw.get("product_name", "") or "").strip(),
        name=str(raw.get("name", "") or "").strip(),
        highlights=str(raw.get("highlights", "") or "").strip(),
        description=str(raw.get("description", "") or "").strip(),
        icon_key=str(raw.get("icon_key", "") or "").strip(),
        provider_name=str(raw.get("provider_name", "") or "").strip(),
        provider_description=str(raw.get("provider_description", "") or "").strip(),
        default_visibility=str(raw.get("default_visibility", "") or "").strip().lower() or "visible",
        tags=_list_of_str(raw.get("tags")),
        howto=_list_of_str(raw.get("howto")),
        billing_product_id=str(raw.get("billing_product_id", "") or "").strip(),
        fallback_plugin_id=str(raw.get("fallback_plugin_id", "") or "").strip(),
    )


def _list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            items.append(text)
    return items
