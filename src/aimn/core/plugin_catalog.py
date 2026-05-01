from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aimn.core.app_paths import get_plugin_remote_catalog_path
from aimn.core.contracts import PluginDescriptor, PluginOption, PluginSetting, PluginUiSchema
from aimn.core.plugin_activation_service import PluginActivationService
from aimn.core.plugin_discovery import PluginDiscovery
from aimn.core.plugin_distribution import PluginDistributionResolver
from aimn.core.plugin_manifest import PluginDistributionSpec, PluginManifest
from aimn.core.plugin_remote_catalog import RemotePluginCatalogEntry, load_remote_catalog
from aimn.core.plugin_trust import PluginTrustResolver
from aimn.core.plugins_config import PluginsConfig
from aimn.core.release_profile import active_release_profile


class PluginCatalog:
    def __init__(self) -> None:
        self._plugins: List[PluginDescriptor] = []
        self._schemas: List[PluginUiSchema] = []
        self._index: Dict[str, PluginDescriptor] = {}
        self._display_names: Dict[str, str] = {}

    def add_plugin(self, plugin: PluginDescriptor) -> None:
        self._plugins.append(plugin)
        self._index[plugin.plugin_id] = plugin

    def add_schema(self, schema: PluginUiSchema) -> None:
        self._schemas.append(schema)

    def all_plugins(self) -> List[PluginDescriptor]:
        return list(self._plugins)

    def plugin_by_id(self, plugin_id: str) -> Optional[PluginDescriptor]:
        return self._index.get(plugin_id)

    def plugins_for_stage(self, stage_id: str) -> List[PluginDescriptor]:
        return [plugin for plugin in self._plugins if plugin.stage_id == stage_id]

    def enabled_plugins(self) -> List[PluginDescriptor]:
        return [
            plugin
            for plugin in self._plugins
            if plugin.installed and plugin.runtime_state == "active"
        ]

    def allowlist_ids(self) -> List[str]:
        return [plugin.plugin_id for plugin in self.enabled_plugins()]

    def schema_for(self, plugin_id: str) -> Optional[PluginUiSchema]:
        for schema in self._schemas:
            if schema.plugin_id == plugin_id:
                return schema
        return None

    def set_display_name(self, plugin_id: str, name: str) -> None:
        if plugin_id and name:
            self._display_names[plugin_id] = name

    def display_name(self, plugin_id: str) -> str:
        name = self._display_names.get(plugin_id)
        if name:
            return name
        plugin = self._index.get(plugin_id)
        if plugin and plugin.product_name:
            return plugin.product_name
        return plugin.name if plugin else plugin_id

    def provider_label(self, plugin_id: str) -> str:
        plugin = self._index.get(plugin_id)
        if plugin and plugin.provider_name:
            return plugin.provider_name
        return ""

    def provider_description(self, plugin_id: str) -> str:
        plugin = self._index.get(plugin_id)
        if not plugin:
            return ""
        return plugin.provider_description or plugin.description

    def model_details(self, plugin_id: str, model_id: str) -> Dict[str, str]:
        plugin = self._index.get(plugin_id)
        if not plugin:
            return {}
        return dict(plugin.model_info.get(model_id, {}))

    def default_plugin_for_stage(self, stage_id: str) -> Optional[PluginDescriptor]:
        for plugin in self.plugins_for_stage(stage_id):
            if plugin.installed and plugin.runtime_state == "active":
                return plugin
        return None


def create_default_catalog(app_root: Path, config: Optional[PluginsConfig] = None) -> PluginCatalog:
    catalog = PluginCatalog()
    resolver = PluginDistributionResolver(app_root)
    trust = PluginTrustResolver(app_root)
    activation = PluginActivationService(app_root)
    release_profile = active_release_profile(app_root)
    manifests = _discover_manifests(app_root)
    remote_entries = _discover_remote_entries(app_root) if release_profile.plugin_marketplace_visible() else []
    bundled_ids = set(release_profile.bundled_plugin_ids()) if release_profile.active else set()
    installed_state = resolver.installed_plugins_payload()
    allowlist = config.allowlist() if config else None
    disabled = set(config.disabled() or []) if config else set()
    enabled = set(config.enabled_plugin_ids()) if config else set()
    local_plugin_ids: set[str] = set()

    for manifest, _manifest_path, passport, raw in manifests:
        if bool(getattr(manifest, "ui_hidden", False)):
            continue
        if bundled_ids and manifest.plugin_id not in bundled_ids:
            continue
        local_plugin_ids.add(manifest.plugin_id)
        stage_id = _ui_stage_from_raw(raw) or _stage_id_from_manifest(manifest) or "other"
        desired_enabled = _desired_enabled(
            manifest.plugin_id,
            enabled=enabled,
            allowlist=allowlist,
            disabled=disabled,
            activation=activation,
        )
        descriptor = PluginDescriptor(
            plugin_id=manifest.plugin_id,
            stage_id=stage_id,
            name=manifest.name,
            module=_entrypoint_module(manifest),
            class_name=_entrypoint_class(manifest),
            version=manifest.version,
            product_name=manifest.product_name,
            highlights=manifest.highlights,
            description=manifest.description,
            icon_key=manifest.icon_key,
            default_visibility=manifest.default_visibility,
        )
        access = resolver.resolve_plugin(manifest.plugin_id, manifest.distribution, _manifest_path)
        trust_decision = trust.trust_for_plugin(
            manifest.plugin_id,
            manifest_path=_manifest_path,
            distribution=manifest.distribution,
        )
        descriptor.source_kind = access.source_kind
        descriptor.source_path = access.source_path
        descriptor.owner_type = access.owner_type
        descriptor.publisher_id = trust_decision.publisher_id or manifest.distribution.publisher_id
        descriptor.pricing_model = access.pricing_model
        descriptor.requires_platform_edition = access.requires_platform_edition
        descriptor.included_in_core = access.included_in_core
        descriptor.entitled = access.entitled
        descriptor.access_state = access.access_state
        descriptor.access_reason = access.access_reason
        descriptor.catalog_enabled = access.catalog_enabled
        descriptor.billing_product_id = access.billing_product_id
        descriptor.fallback_plugin_id = access.fallback_plugin_id
        descriptor.trust_level = trust_decision.trust_level
        descriptor.trust_source = trust_decision.trust_source
        descriptor.verification_state = trust_decision.verification_state
        descriptor.checksum_verified = trust_decision.checksum_verified
        descriptor.signature_verified = trust_decision.signature_verified
        descriptor.howto = _howto_from_raw(raw)
        descriptor.tags = _tags_from_raw(raw)
        _apply_raw_capabilities(descriptor, raw)
        _apply_plugin_passport(descriptor, passport)
        _apply_installed_verification_metadata(descriptor, installed_state)
        descriptor.enabled = desired_enabled
        descriptor.installed = True
        descriptor.visible_in_catalog, descriptor.runtime_state = _resolve_runtime_state(
            descriptor.default_visibility,
            entitled=descriptor.entitled,
            desired_enabled=descriptor.enabled,
            access_state=descriptor.access_state,
        )
        if not descriptor.visible_in_catalog:
            continue
        catalog.add_plugin(descriptor)
        catalog.set_display_name(
            descriptor.plugin_id, descriptor.product_name or descriptor.name or descriptor.plugin_id
        )

        schema = _schema_from_raw(raw, manifest.plugin_id, stage_id)
        if schema:
            catalog.add_schema(schema)

    for entry in remote_entries:
        if entry.plugin_id in local_plugin_ids:
            plugin = catalog.plugin_by_id(entry.plugin_id)
            if plugin:
                _apply_remote_catalog_metadata(plugin, entry)
            continue
        descriptor = _remote_descriptor(
            entry,
            resolver=resolver,
            trust=trust,
            activation=activation,
            enabled=enabled,
            allowlist=allowlist,
            disabled=disabled,
        )
        if not descriptor or not descriptor.visible_in_catalog:
            continue
        catalog.add_plugin(descriptor)
        catalog.set_display_name(
            descriptor.plugin_id, descriptor.product_name or descriptor.name or descriptor.plugin_id
        )

    return catalog


def _ui_stage_from_raw(raw: dict) -> str:
    value = raw.get("ui_stage") if isinstance(raw, dict) else None
    sid = str(value or "").strip()
    allowed = {"transcription", "llm_processing", "management", "service", "other"}
    return sid if sid in allowed else ""


def _howto_from_raw(raw: dict) -> list[str]:
    items = raw.get("howto") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            lines.append(text)
    return lines


def _tags_from_raw(raw: dict) -> list[str]:
    items = raw.get("tags") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    tags: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            tags.append(text)
    return tags


def _apply_raw_capabilities(plugin: PluginDescriptor, raw: dict) -> None:
    caps = raw.get("capabilities") if isinstance(raw, dict) else None
    if not isinstance(caps, dict) or not caps:
        return
    try:
        merged = dict(plugin.capabilities) if isinstance(plugin.capabilities, dict) else {}
        merged.update(dict(caps))
        plugin.capabilities = merged
    except Exception:
        return


def _discover_manifests(app_root: Path) -> List[Tuple[PluginManifest, Path, dict, dict]]:
    manifests: List[Tuple[PluginManifest, Path, dict, dict]] = []
    discovery = PluginDiscovery(PluginDistributionResolver(app_root).plugin_roots())
    for entry in discovery.discover_entries():
        path = entry.manifest_path
        if _is_test_plugin_manifest(path):
            continue
        raw = _load_manifest_raw(path)
        manifest = entry.manifest
        manifests.append((manifest, path, _load_passport(path), raw))
    return manifests


def _is_test_plugin_manifest(path: Path) -> bool:
    parent_name = str(path.parent.name or "").strip()
    return parent_name.startswith("_test_")


def _discover_remote_entries(app_root: Path) -> list[RemotePluginCatalogEntry]:
    return load_remote_catalog(get_plugin_remote_catalog_path(app_root))


def _schema_from_raw(raw: dict, plugin_id: str, stage_id: str) -> Optional[PluginUiSchema]:
    schema = raw.get("ui_schema") if isinstance(raw, dict) else None
    if not isinstance(schema, dict):
        return None
    settings_raw = schema.get("settings")
    if not isinstance(settings_raw, list):
        return None
    settings: List[PluginSetting] = []
    for setting in settings_raw:
        if not isinstance(setting, dict):
            continue
        key = str(setting.get("key", "")).strip()
        label = str(setting.get("label", "")).strip()
        value_raw = setting.get("value", "")
        advanced = bool(setting.get("advanced", False))
        if isinstance(value_raw, bool):
            value = "true" if value_raw else "false"
        elif value_raw is None:
            value = ""
        else:
            value = str(value_raw).strip()
        if not key or not label:
            continue
        options = None
        raw_options = setting.get("options")
        if isinstance(raw_options, list):
            options = []
            for opt in raw_options:
                if not isinstance(opt, dict):
                    continue
                label = str(opt.get("label", "")).strip()
                if not label or "value" not in opt:
                    continue
                raw_value = opt.get("value", "")
                options.append(
                    PluginOption(
                        label=label,
                        value="" if raw_value is None else str(raw_value),
                    )
                )
        settings.append(
            PluginSetting(
                key=key,
                label=label,
                value=value,
                options=_augment_options(plugin_id, key, options),
                editable=bool(setting.get("editable", False)),
                advanced=advanced,
            )
        )
    if not settings:
        return None
    return PluginUiSchema(plugin_id=plugin_id, stage_id=stage_id, settings=settings)


def _load_manifest_raw(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_passport(manifest_path: Path) -> dict:
    passport_path = manifest_path.parent / "plugin_passport.json"
    if not passport_path.exists():
        return {}
    try:
        return json.loads(passport_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _apply_plugin_passport(plugin: PluginDescriptor, passport: dict) -> None:
    if not isinstance(passport, dict):
        return

    # plugin_passport.json is meant to describe runtime/provider/model metadata.
    # UI copy (product_name/highlights/description/icon_key) must live in plugin.json.
    ignored_keys = [k for k in ("product_name", "highlights", "description", "icon_key") if k in passport]
    if ignored_keys:
        logging.getLogger("aimn.plugins").debug(
            "plugin_passport_ui_fields_ignored plugin_id=%s keys=%s",
            plugin.plugin_id,
            ",".join(ignored_keys),
        )
    provider = passport.get("provider")
    provider_name = ""
    provider_description = ""
    if isinstance(provider, dict):
        provider_name = str(provider.get("name", "")).strip()
        provider_description = str(provider.get("description", "")).strip()
    models = passport.get("models")
    model_index: Dict[str, Dict[str, str]] = {}
    if isinstance(models, list):
        for entry in models:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("id", "") or entry.get("model_id", "")).strip()
            if not model_id:
                continue
            model_index[model_id] = {
                "model_id": model_id,
                "model_name": str(entry.get("name", "")).strip(),
                "model_description": str(entry.get("description", "")).strip(),
                "quant": str(entry.get("quant", "")).strip(),
                "size_hint": str(entry.get("size_hint", "")).strip(),
                "file": str(entry.get("file", "")).strip(),
                "source_url": str(entry.get("source_url", "") or "").strip(),
                "download_url": str(entry.get("download_url", "") or "").strip(),
                "enabled": bool(entry.get("enabled", True)),
                "catalog_source": str(entry.get("catalog_source", "") or "recommended").strip(),
            }
    if provider_name:
        plugin.provider_name = provider_name
    if provider_description:
        plugin.provider_description = provider_description
    if model_index:
        plugin.model_info = model_index

    capabilities = passport.get("capabilities")
    if isinstance(capabilities, dict) and capabilities:
        plugin.capabilities = dict(capabilities)


def _remote_descriptor(
    entry: RemotePluginCatalogEntry,
    *,
    resolver: PluginDistributionResolver,
    trust: PluginTrustResolver,
    activation: PluginActivationService,
    enabled: set[str],
    allowlist: list[str] | None,
    disabled: set[str],
) -> PluginDescriptor | None:
    spec = PluginDistributionSpec(
        channel="catalog",
        owner_type=entry.owner_type or "third_party",
        publisher_id=entry.publisher_id,
        pricing_model=entry.pricing_model or "free",
        requires_platform_edition=bool(entry.requires_platform_edition),
        catalog_enabled=bool(entry.catalog_enabled),
        billing_product_id=entry.billing_product_id,
        fallback_plugin_id=entry.fallback_plugin_id,
    )
    access = resolver.resolve_catalog_plugin(entry.plugin_id, spec)
    trust_decision = trust.trust_for_plugin(entry.plugin_id, distribution=spec)
    desired_enabled = _desired_enabled(
        entry.plugin_id,
        enabled=enabled,
        allowlist=allowlist,
        disabled=disabled,
        activation=activation,
    )
    descriptor = PluginDescriptor(
        plugin_id=entry.plugin_id,
        stage_id=entry.stage_id or "other",
        name=entry.name or entry.product_name or entry.plugin_id,
        module="",
        class_name="",
        version=entry.version,
        enabled=False,
        installed=False,
        product_name=entry.product_name or entry.name or entry.plugin_id,
        provider_name=entry.provider_name,
        provider_description=entry.provider_description,
        tags=list(entry.tags),
        highlights=entry.highlights,
        description=entry.description,
        howto=list(entry.howto),
        icon_key=entry.icon_key,
        source_kind=access.source_kind,
        source_path=access.source_path,
        owner_type=access.owner_type,
        pricing_model=access.pricing_model,
        requires_platform_edition=access.requires_platform_edition,
        included_in_core=access.included_in_core,
        entitled=access.entitled,
        access_state=access.access_state,
        access_reason=access.access_reason,
        catalog_enabled=access.catalog_enabled,
        billing_product_id=access.billing_product_id,
        fallback_plugin_id=access.fallback_plugin_id,
        default_visibility=entry.default_visibility or "visible",
        remote_version=entry.version,
        remote_only=True,
        download_url=entry.download_url,
        manifest_url=entry.manifest_url,
        publisher_id=entry.publisher_id,
        checksum_sha256=entry.checksum_sha256,
        signature=entry.signature,
        signature_algorithm=entry.signature_algorithm,
        signing_key_id=entry.signing_key_id,
        trust_level=trust_decision.trust_level,
        trust_source=trust_decision.trust_source,
        verification_state=trust_decision.verification_state,
        checksum_verified=trust_decision.checksum_verified,
        signature_verified=trust_decision.signature_verified,
        compatible_app_versions=list(entry.compatible_app_versions),
    )
    descriptor.visible_in_catalog, descriptor.runtime_state = _resolve_runtime_state(
        descriptor.default_visibility,
        entitled=descriptor.entitled,
        desired_enabled=desired_enabled,
        access_state=descriptor.access_state,
        installed=False,
    )
    descriptor.enabled = False
    return descriptor


def _apply_remote_catalog_metadata(plugin: PluginDescriptor, entry: RemotePluginCatalogEntry) -> None:
    plugin.remote_version = entry.version
    plugin.download_url = entry.download_url or plugin.download_url
    plugin.manifest_url = entry.manifest_url or plugin.manifest_url
    plugin.publisher_id = entry.publisher_id or plugin.publisher_id
    plugin.checksum_sha256 = entry.checksum_sha256 or plugin.checksum_sha256
    plugin.signature = entry.signature or plugin.signature
    plugin.signature_algorithm = entry.signature_algorithm or plugin.signature_algorithm
    plugin.signing_key_id = entry.signing_key_id or plugin.signing_key_id
    plugin.compatible_app_versions = list(entry.compatible_app_versions or plugin.compatible_app_versions)
    if entry.provider_name and not plugin.provider_name:
        plugin.provider_name = entry.provider_name
    if entry.provider_description and not plugin.provider_description:
        plugin.provider_description = entry.provider_description
    if entry.highlights and not plugin.highlights:
        plugin.highlights = entry.highlights
    if entry.description and not plugin.description:
        plugin.description = entry.description
    if entry.tags and not plugin.tags:
        plugin.tags = list(entry.tags)
    if entry.howto and not plugin.howto:
        plugin.howto = list(entry.howto)
    plugin.has_update = _is_version_newer(entry.version, plugin.version)


def _apply_installed_verification_metadata(plugin: PluginDescriptor, installed_state: dict) -> None:
    plugins = installed_state.get("plugins") if isinstance(installed_state, dict) else None
    if not isinstance(plugins, dict):
        return
    item = plugins.get(plugin.plugin_id)
    if not isinstance(item, dict):
        return
    plugin.publisher_id = str(item.get("publisher_id", "") or plugin.publisher_id).strip() or plugin.publisher_id
    plugin.checksum_sha256 = str(item.get("checksum_sha256", "") or plugin.checksum_sha256).strip()
    plugin.signature = str(item.get("signature", "") or plugin.signature).strip()
    plugin.signature_algorithm = str(
        item.get("signature_algorithm", "") or plugin.signature_algorithm
    ).strip()
    plugin.signing_key_id = str(item.get("signing_key_id", "") or plugin.signing_key_id).strip()
    plugin.trust_level = str(item.get("trust_level", "") or plugin.trust_level).strip()
    plugin.trust_source = str(item.get("trust_source", "") or plugin.trust_source).strip()
    plugin.verification_state = str(
        item.get("verification_state", "") or plugin.verification_state
    ).strip()
    plugin.checksum_verified = bool(item.get("checksum_verified", plugin.checksum_verified))
    plugin.signature_verified = bool(item.get("signature_verified", plugin.signature_verified))


def _desired_enabled(
    plugin_id: str,
    *,
    enabled: set[str],
    allowlist: list[str] | None,
    disabled: set[str],
    activation: PluginActivationService,
) -> bool:
    default = True
    if enabled:
        default = plugin_id in enabled
    elif allowlist is not None:
        default = plugin_id in set(allowlist)
    else:
        default = plugin_id not in disabled
    return activation.is_enabled(plugin_id, default=default)


def _resolve_runtime_state(
    default_visibility: str,
    *,
    entitled: bool,
    desired_enabled: bool,
    access_state: str,
    installed: bool = True,
) -> tuple[bool, str]:
    visibility = str(default_visibility or "visible").strip().lower() or "visible"
    if installed and entitled:
        return True, "active" if desired_enabled else "available_inactive"
    if not installed and entitled:
        return True, "installable"
    if visibility == "hidden" and not desired_enabled and access_state != "revoked":
        return False, "hidden"
    return True, "visible_locked" if installed else "installable_locked"


def _is_version_newer(candidate: str, current: str) -> bool:
    left = _version_key(candidate)
    right = _version_key(current)
    return left > right


def _version_key(value: str) -> tuple:
    raw = str(value or "").strip()
    if not raw:
        return tuple()
    parts: list[object] = []
    token = ""
    numeric = raw[:1].isdigit()
    for char in raw:
        if char.isdigit() == numeric:
            token += char
            continue
        parts.append(int(token) if numeric and token else token.lower())
        token = char
        numeric = char.isdigit()
    if token:
        parts.append(int(token) if numeric else token.lower())
    return tuple(parts)


def _augment_options(
    plugin_id: str, key: str, options: Optional[List[PluginOption]]
) -> Optional[List[PluginOption]]:
    return options


def _stage_id_from_manifest(manifest: PluginManifest) -> str:
    for hook in manifest.hooks:
        if hook.name == "derive.after_postprocess":
            return "llm_processing"
        if hook.name == "derive.after_summary":
            return "management"
    for hook in manifest.hooks:
        if hook.name.startswith("transcribe."):
            return "transcription"
        if hook.name.startswith("postprocess."):
            return "llm_processing"
    return "other"


def _entrypoint_module(manifest: PluginManifest) -> str:
    return manifest.entrypoint.split(":")[0]


def _entrypoint_class(manifest: PluginManifest) -> str:
    parts = manifest.entrypoint.split(":")
    return parts[1] if len(parts) > 1 else ""
