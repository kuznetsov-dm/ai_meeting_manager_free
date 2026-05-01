from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
_ENTRYPOINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\.]*:[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_VISIBILITY = {"visible", "hidden"}


@dataclass(frozen=True)
class HookSpec:
    name: str
    mode: str = "optional"
    priority: int = 100
    handler_id: str = ""


@dataclass(frozen=True)
class PluginDistributionSpec:
    channel: str = "bundled"
    owner_type: str = "first_party"
    publisher_id: str = ""
    pricing_model: str = "free"
    requires_platform_edition: bool = False
    catalog_enabled: bool = False
    billing_product_id: str = ""
    fallback_plugin_id: str = ""


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    api_version: str
    entrypoint: str
    hooks: list[HookSpec]
    artifacts: list[str]
    dependencies: list[str] = field(default_factory=list)
    ui_hidden: bool = False
    product_name: str | None = None
    highlights: str = ""
    description: str = ""
    icon_key: str = ""
    default_visibility: str = "visible"
    distribution: PluginDistributionSpec = field(default_factory=PluginDistributionSpec)


def load_plugin_manifest(path: Path) -> PluginManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("plugin.json must be an object")
    if "stages" in raw or "pipeline" in raw:
        raise ValueError("plugin.json must not declare pipeline stages")

    plugin_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    version = str(raw.get("version", "")).strip()
    api_version = str(raw.get("api_version", "")).strip()
    entrypoint = str(raw.get("entrypoint", "")).strip()
    if not plugin_id or not name or not version or not api_version or not entrypoint:
        raise ValueError("plugin.json missing required fields")

    if "product_name" not in raw:
        raise ValueError("plugin.json missing required product_name")
    if not _PLUGIN_ID_RE.fullmatch(plugin_id):
        raise ValueError(f"plugin.json invalid plugin id: {plugin_id}")
    if not _ENTRYPOINT_RE.fullmatch(entrypoint):
        raise ValueError(f"plugin.json invalid entrypoint: {entrypoint}")
    product_name = _clean(raw.get("product_name"))
    if not product_name:
        raise ValueError("plugin.json product_name must be non-empty")
    if "highlights" not in raw:
        raise ValueError("plugin.json missing required highlights")
    if "description" not in raw:
        raise ValueError("plugin.json missing required description")
    hooks = _parse_hooks(raw.get("hooks"))
    artifacts = _parse_artifacts(raw.get("artifacts"))
    dependencies = _parse_dependencies(raw.get("dependencies", []))
    distribution = _parse_distribution(raw.get("distribution"))
    default_visibility = _parse_default_visibility(raw.get("default_visibility"))
    if hooks is None or artifacts is None:
        raise ValueError("plugin.json missing required hooks/artifacts")
    return PluginManifest(
        plugin_id=plugin_id,
        name=name,
        version=version,
        api_version=api_version,
        entrypoint=entrypoint,
        hooks=hooks,
        artifacts=artifacts,
        dependencies=dependencies,
        ui_hidden=bool(raw.get("ui_hidden", False)),
        product_name=product_name,
        highlights=str(raw.get("highlights", "") or "").strip(),
        description=str(raw.get("description", "") or "").strip(),
        icon_key=str(raw.get("icon_key", "") or "").strip(),
        default_visibility=default_visibility,
        distribution=distribution,
    )


def _parse_hooks(raw: Any) -> list[HookSpec] | None:
    hooks: list[HookSpec] = []
    if not isinstance(raw, list):
        return None
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        mode = str(entry.get("mode", "optional")).strip() or "optional"
        priority = entry.get("priority", 100)
        if not isinstance(priority, int):
            priority = 100
        handler_id = str(entry.get("id", "")).strip()
        hooks.append(HookSpec(name=name, mode=mode, priority=priority, handler_id=handler_id))
    return hooks


def _parse_artifacts(raw: Any) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    artifacts: list[str] = []
    for entry in raw:
        value = str(entry).strip()
        if value:
            artifacts.append(value)
    return artifacts


def _parse_dependencies(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("plugin.json dependencies must be an array of strings")
    deps: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError("plugin.json dependencies must be an array of strings")
        value = entry.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deps.append(value)
    return deps


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_distribution(raw: Any) -> PluginDistributionSpec:
    if raw is None:
        return PluginDistributionSpec()
    if not isinstance(raw, dict):
        raise ValueError("plugin.json distribution must be an object")
    channel = str(raw.get("channel", "bundled") or "bundled").strip() or "bundled"
    owner_type = str(raw.get("owner_type", "first_party") or "first_party").strip() or "first_party"
    publisher_id = str(raw.get("publisher_id", "") or "").strip()
    pricing_model = str(raw.get("pricing_model", "free") or "free").strip() or "free"
    billing_product_id = str(raw.get("billing_product_id", "") or "").strip()
    fallback_plugin_id = str(raw.get("fallback_plugin_id", "") or "").strip()
    return PluginDistributionSpec(
        channel=channel,
        owner_type=owner_type,
        publisher_id=publisher_id,
        pricing_model=pricing_model,
        requires_platform_edition=bool(raw.get("requires_platform_edition", False)),
        catalog_enabled=bool(raw.get("catalog_enabled", False)),
        billing_product_id=billing_product_id,
        fallback_plugin_id=fallback_plugin_id,
    )


def _parse_default_visibility(raw: Any) -> str:
    value = str(raw or "visible").strip().lower() or "visible"
    if value not in _DEFAULT_VISIBILITY:
        raise ValueError(f"plugin.json default_visibility must be one of: {sorted(_DEFAULT_VISIBILITY)}")
    return value
