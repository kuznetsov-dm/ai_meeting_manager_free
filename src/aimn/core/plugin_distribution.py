from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aimn.core.app_paths import (
    get_installed_plugins_dir,
    get_installed_plugins_state_path,
    get_plugin_distribution_path,
    get_plugin_roots,
    get_plugins_dir,
)
from aimn.core.plugin_entitlements_service import PluginEntitlementsService
from aimn.core.plugin_manifest import PluginDistributionSpec

ACTIVE_PLUGIN_STATUSES = {"active", "grace"}
PAID_PLUGIN_MODES = {"one_time", "subscription"}


@dataclass(frozen=True)
class PluginAccessState:
    source_kind: str
    source_path: str
    owner_type: str
    pricing_model: str
    requires_platform_edition: bool
    included_in_core: bool
    entitled: bool
    can_run: bool
    access_state: str
    access_reason: str
    catalog_enabled: bool
    billing_product_id: str
    fallback_plugin_id: str


class PluginDistributionResolver:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._bundled_dir = get_plugins_dir(app_root).resolve()
        self._installed_dir = get_installed_plugins_dir(app_root).resolve()
        self._distribution = _load_json_object(get_plugin_distribution_path(app_root))
        self._entitlements = PluginEntitlementsService(app_root).load().payload
        self._installed_state = _load_json_object(get_installed_plugins_state_path(app_root))

    def plugin_roots(self) -> tuple[Path, ...]:
        return get_plugin_roots(self._app_root)

    def source_kind_for_path(self, manifest_path: Path) -> str:
        path = manifest_path.resolve()
        if _is_relative_to(path, self._installed_dir):
            return "installed"
        if _is_relative_to(path, self._bundled_dir):
            return "bundled"
        return "external"

    def resolve_plugin(
        self,
        plugin_id: str,
        spec: PluginDistributionSpec,
        manifest_path: Path,
    ) -> PluginAccessState:
        source_kind = self.source_kind_for_path(manifest_path)
        return self._resolve_access(plugin_id, spec, source_kind=source_kind, manifest_path=str(manifest_path))

    def resolve_catalog_plugin(
        self,
        plugin_id: str,
        spec: PluginDistributionSpec,
    ) -> PluginAccessState:
        return self._resolve_access(plugin_id, spec, source_kind="remote", manifest_path="")

    def _resolve_access(
        self,
        plugin_id: str,
        spec: PluginDistributionSpec,
        *,
        source_kind: str,
        manifest_path: str,
    ) -> PluginAccessState:
        override = self._plugin_override(plugin_id)
        included_in_core = plugin_id in self._baseline_plugin_ids()
        owner_type = _str_or_default(override.get("owner_type"), spec.owner_type)
        pricing_model = _str_or_default(override.get("pricing_model"), spec.pricing_model)
        catalog_enabled = _bool_or_default(override.get("catalog_enabled"), spec.catalog_enabled)
        billing_product_id = _str_or_default(override.get("billing_product_id"), spec.billing_product_id)
        fallback_plugin_id = _str_or_default(override.get("fallback_plugin_id"), spec.fallback_plugin_id)

        requires_platform_edition = _bool_or_default(
            override.get("requires_platform_edition"),
            spec.requires_platform_edition,
        )
        if (not included_in_core) and self._default_optional_requires_platform():
            requires_platform_edition = True

        platform_enabled = self._platform_enabled()
        plugin_status = self._plugin_entitlement_status(plugin_id)
        entitled = False
        access_state = "locked"
        access_reason = "plugin_locked"

        if included_in_core:
            entitled = True
            access_state = "core_included"
            access_reason = "bundled_with_core"
        elif pricing_model not in PAID_PLUGIN_MODES:
            if requires_platform_edition and not platform_enabled:
                access_state = "platform_locked"
                access_reason = "platform_edition_required"
            else:
                entitled = True
                access_state = "active"
                access_reason = "free_plugin_available"
        else:
            if requires_platform_edition and not platform_enabled:
                access_state = "platform_locked"
                access_reason = "platform_edition_required"
            elif plugin_status in ACTIVE_PLUGIN_STATUSES:
                entitled = True
                access_state = "grace" if plugin_status == "grace" else "active"
                access_reason = f"{pricing_model}_entitlement_{plugin_status}"
            else:
                access_state = (
                    "subscription_required" if pricing_model == "subscription" else "purchase_required"
                )
                access_reason = f"{pricing_model}_entitlement_missing"

        if self._is_installed_state_revoked(plugin_id):
            entitled = included_in_core
            if included_in_core:
                access_state = "core_included"
                access_reason = "bundled_with_core"
            else:
                access_state = "revoked"
                access_reason = "entitlement_revoked"

        return PluginAccessState(
            source_kind=source_kind,
            source_path=manifest_path,
            owner_type=owner_type,
            pricing_model=pricing_model,
            requires_platform_edition=requires_platform_edition,
            included_in_core=included_in_core,
            entitled=entitled,
            can_run=entitled,
            access_state=access_state,
            access_reason=access_reason,
            catalog_enabled=catalog_enabled,
            billing_product_id=billing_product_id,
            fallback_plugin_id=fallback_plugin_id,
        )

    def installed_plugins_payload(self) -> dict:
        return dict(self._installed_state)

    def platform_edition_enabled(self) -> bool:
        return self._platform_enabled()

    def _baseline_plugin_ids(self) -> set[str]:
        raw = self._distribution.get("baseline_plugin_ids")
        if not isinstance(raw, list):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    def _default_optional_requires_platform(self) -> bool:
        return bool(self._distribution.get("default_optional_requires_platform_edition", False))

    def _plugin_override(self, plugin_id: str) -> dict[str, Any]:
        payload = self._distribution.get("plugin_overrides")
        if not isinstance(payload, dict):
            return {}
        override = payload.get(plugin_id)
        return dict(override) if isinstance(override, dict) else {}

    def _platform_enabled(self) -> bool:
        payload = self._entitlements.get("platform_edition")
        if not isinstance(payload, dict):
            return False
        if not bool(payload.get("enabled", False)):
            return False
        status = str(payload.get("status", "active") or "active").strip()
        return status in ACTIVE_PLUGIN_STATUSES

    def _plugin_entitlement_status(self, plugin_id: str) -> str:
        payload = self._entitlements.get("plugins")
        if not isinstance(payload, dict):
            return ""
        item = payload.get(plugin_id)
        if not isinstance(item, dict):
            return ""
        return str(item.get("status", "") or "").strip()

    def _is_installed_state_revoked(self, plugin_id: str) -> bool:
        payload = self._installed_state.get("plugins")
        if not isinstance(payload, dict):
            return False
        item = payload.get(plugin_id)
        if not isinstance(item, dict):
            return False
        return str(item.get("runtime_state", "") or "").strip() == "revoked"


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return bool(default)


def _str_or_default(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or str(default or "")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
