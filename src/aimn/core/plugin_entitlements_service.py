from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aimn.core.app_paths import get_plugin_entitlements_path
from aimn.core.plugin_trust import PluginTrustResolver, canonical_json_bytes, verify_signed_message
from aimn.core.release_profile import active_release_profile


@dataclass(frozen=True)
class EntitlementSnapshot:
    payload: dict[str, Any]
    verified: bool
    reason: str
    publisher_id: str = ""
    signature_algorithm: str = ""


class PluginEntitlementsService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._path = get_plugin_entitlements_path(app_root)
        self._trust = PluginTrustResolver(app_root)

    def load(self) -> EntitlementSnapshot:
        raw = _load_json_object(self._path)
        return self.validate_payload(
            raw,
            allow_unsigned_developer=self._allow_unsigned_developer_entitlements(),
        )

    def validate_payload(
        self,
        raw: dict[str, Any],
        *,
        allow_unsigned_developer: bool = False,
    ) -> EntitlementSnapshot:
        if not raw:
            return EntitlementSnapshot(payload={}, verified=False, reason="missing")
        meta = raw.get("_meta")
        signed_payload = {key: value for key, value in raw.items() if key != "_meta"}
        if not _contains_pro_entitlements(signed_payload):
            return EntitlementSnapshot(payload=signed_payload, verified=False, reason="free_only")
        if allow_unsigned_developer and _is_developer_entitlement_payload(signed_payload):
            return EntitlementSnapshot(
                payload=signed_payload,
                verified=False,
                reason="developer_override",
            )
        if not isinstance(meta, dict):
            return EntitlementSnapshot(
                payload=_strip_pro_entitlements(signed_payload),
                verified=False,
                reason="signature_missing",
            )
        publisher_id = str(meta.get("publisher_id", "") or "").strip()
        signature = str(meta.get("signature", "") or "").strip()
        signature_algorithm = str(meta.get("signature_algorithm", "") or "").strip().lower()
        signing_key_id = str(meta.get("signing_key_id", "") or "").strip()
        publisher = self._trust.publisher_policy(publisher_id)
        if not verify_signed_message(
            publisher=publisher,
            message=canonical_json_bytes(signed_payload),
            signature=signature,
            signature_algorithm=signature_algorithm,
            signing_key_id=signing_key_id,
        ):
            return EntitlementSnapshot(
                payload=_strip_pro_entitlements(signed_payload),
                verified=False,
                reason="signature_invalid",
                publisher_id=publisher_id,
                signature_algorithm=signature_algorithm,
            )
        return EntitlementSnapshot(
            payload=signed_payload,
            verified=True,
            reason="verified",
            publisher_id=publisher_id,
            signature_algorithm=signature_algorithm,
        )

    def _allow_unsigned_developer_entitlements(self) -> bool:
        return not active_release_profile(self._app_root).active


def _contains_pro_entitlements(payload: dict[str, Any]) -> bool:
    platform = payload.get("platform_edition")
    if isinstance(platform, dict) and bool(platform.get("enabled", False)):
        return True
    plugins = payload.get("plugins")
    if not isinstance(plugins, dict):
        return False
    for item in plugins.values():
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "") or "").strip().lower()
        if status in {"active", "grace"}:
            return True
    return False


def _is_developer_entitlement_payload(payload: dict[str, Any]) -> bool:
    edition = str(payload.get("edition", "") or "").strip().lower()
    if edition.endswith("_dev"):
        return True
    platform = payload.get("platform_edition")
    if not isinstance(platform, dict):
        return False
    mode = str(platform.get("mode", "") or "").strip().lower()
    return mode == "developer"


def _strip_pro_entitlements(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload) if isinstance(payload, dict) else {}
    platform = sanitized.get("platform_edition")
    if isinstance(platform, dict):
        sanitized["platform_edition"] = {
            **platform,
            "enabled": False,
            "status": "inactive",
        }
    plugins = sanitized.get("plugins")
    if isinstance(plugins, dict):
        sanitized_plugins: dict[str, Any] = {}
        for plugin_id, item in plugins.items():
            if not isinstance(item, dict):
                continue
            sanitized_plugins[str(plugin_id)] = {
                **item,
                "status": "inactive",
            }
        sanitized["plugins"] = sanitized_plugins
    return sanitized


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
