from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aimn.core.app_paths import (
    get_installed_plugins_dir,
    get_installed_plugins_state_path,
    get_plugin_remote_catalog_path,
    get_plugin_trust_policy_path,
    get_plugins_dir,
)
from aimn.core.plugin_manifest import PluginDistributionSpec, PluginManifest
from aimn.core.plugin_remote_catalog import RemotePluginCatalogEntry, load_remote_catalog

TRUST_FIRST_PARTY = "first_party"
TRUST_THIRD_PARTY = "trusted_third_party"
TRUST_UNTRUSTED = "untrusted_local"

VERIFICATION_VERIFIED = "verified"
VERIFICATION_UNTRUSTED = "untrusted"
VERIFICATION_BLOCKED = "blocked"


@dataclass(frozen=True)
class PublisherKeySpec:
    key_id: str
    algorithm: str
    public_exponent: str
    modulus_hex: str


@dataclass(frozen=True)
class PublisherTrustPolicy:
    publisher_id: str
    trust_level: str
    require_checksum: bool
    require_signature: bool
    display_name: str = ""
    key_spec: PublisherKeySpec | None = None
    key_specs: tuple[PublisherKeySpec, ...] = ()


@dataclass(frozen=True)
class PluginTrustDecision:
    plugin_id: str
    publisher_id: str
    source_kind: str
    trust_level: str
    trust_source: str
    verification_state: str
    checksum_verified: bool = False
    signature_verified: bool = False

    @property
    def trusted(self) -> bool:
        return self.trust_level in {TRUST_FIRST_PARTY, TRUST_THIRD_PARTY} and (
            self.verification_state == VERIFICATION_VERIFIED
        )

    @property
    def requires_isolation(self) -> bool:
        return not self.trusted


@dataclass(frozen=True)
class PackageVerificationResult:
    plugin_id: str
    version: str
    publisher_id: str
    checksum_sha256: str
    expected_checksum_sha256: str = ""
    checksum_verified: bool = False
    signature: str = ""
    signature_algorithm: str = ""
    signing_key_id: str = ""
    signature_verified: bool = False
    trust_level: str = TRUST_UNTRUSTED
    trust_source: str = "local_package"
    verification_state: str = VERIFICATION_UNTRUSTED
    install_allowed: bool = True
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


class PluginTrustResolver:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._bundled_dir = get_plugins_dir(app_root).resolve()
        self._installed_dir = get_installed_plugins_dir(app_root).resolve()
        self._installed_state = _load_json_object(get_installed_plugins_state_path(app_root))
        self._raw_policy = _load_json_object(get_plugin_trust_policy_path(app_root))
        self._remote_entries = load_remote_catalog(get_plugin_remote_catalog_path(app_root))
        self._publishers = _load_publishers(self._raw_policy.get("publishers"))

    def verify_package(self, source_path: Path, manifest: PluginManifest) -> PackageVerificationResult:
        checksum_sha256 = compute_package_checksum(source_path)
        entry = self.remote_entry(manifest.plugin_id, manifest.version)
        publisher_id = _normalized_publisher_id(
            entry.publisher_id if entry else "",
            manifest.distribution.publisher_id,
        )
        publisher = self.publisher_policy(publisher_id)
        expected_checksum = _normalized_checksum(entry.checksum_sha256 if entry else "")
        signature = str(entry.signature if entry else "").strip()
        signature_algorithm = str(entry.signature_algorithm if entry else "").strip().lower()
        signing_key_id = str(entry.signing_key_id if entry else "").strip()

        if entry and publisher and publisher.trust_level == TRUST_FIRST_PARTY:
            trust_level = TRUST_FIRST_PARTY
            trust_source = "publisher_policy"
        elif entry and publisher and publisher.trust_level == TRUST_THIRD_PARTY:
            trust_level = TRUST_THIRD_PARTY
            trust_source = "publisher_policy"
        else:
            trust_level = TRUST_UNTRUSTED
            trust_source = "local_package"

        checksum_verified = bool(expected_checksum) and hmac.compare_digest(
            checksum_sha256,
            expected_checksum,
        )
        if expected_checksum and not checksum_verified:
            return PackageVerificationResult(
                plugin_id=manifest.plugin_id,
                version=manifest.version,
                publisher_id=publisher_id,
                checksum_sha256=checksum_sha256,
                expected_checksum_sha256=expected_checksum,
                signature=signature,
                signature_algorithm=signature_algorithm,
                signing_key_id=signing_key_id,
                trust_level=trust_level,
                trust_source=trust_source,
                verification_state=VERIFICATION_BLOCKED,
                install_allowed=False,
                reason="checksum_mismatch",
            )

        require_checksum = bool(
            publisher.require_checksum if publisher else trust_level in {TRUST_FIRST_PARTY, TRUST_THIRD_PARTY}
        )
        if require_checksum and not expected_checksum:
            return PackageVerificationResult(
                plugin_id=manifest.plugin_id,
                version=manifest.version,
                publisher_id=publisher_id,
                checksum_sha256=checksum_sha256,
                signature=signature,
                signature_algorithm=signature_algorithm,
                signing_key_id=signing_key_id,
                trust_level=trust_level,
                trust_source=trust_source,
                verification_state=VERIFICATION_BLOCKED,
                install_allowed=False,
                reason="checksum_required",
            )

        signature_verified = False
        require_signature = bool(
            publisher.require_signature if publisher else trust_level == TRUST_THIRD_PARTY
        )
        if signature and publisher:
            signature_verified = verify_signed_message(
                publisher=publisher,
                message=_signature_message(manifest.plugin_id, manifest.version, checksum_sha256),
                signature=signature,
                signature_algorithm=signature_algorithm,
                signing_key_id=signing_key_id,
            )
        elif signature and signature_algorithm and not publisher:
            signature_verified = False

        if require_signature and not signature:
            return PackageVerificationResult(
                plugin_id=manifest.plugin_id,
                version=manifest.version,
                publisher_id=publisher_id,
                checksum_sha256=checksum_sha256,
                expected_checksum_sha256=expected_checksum,
                checksum_verified=checksum_verified,
                trust_level=trust_level,
                trust_source=trust_source,
                verification_state=VERIFICATION_BLOCKED,
                install_allowed=False,
                reason="signature_required",
            )
        if require_signature and not signature_verified:
            return PackageVerificationResult(
                plugin_id=manifest.plugin_id,
                version=manifest.version,
                publisher_id=publisher_id,
                checksum_sha256=checksum_sha256,
                expected_checksum_sha256=expected_checksum,
                checksum_verified=checksum_verified,
                signature=signature,
                signature_algorithm=signature_algorithm,
                signing_key_id=signing_key_id,
                trust_level=trust_level,
                trust_source=trust_source,
                verification_state=VERIFICATION_BLOCKED,
                install_allowed=False,
                reason="signature_invalid",
            )

        if trust_level == TRUST_UNTRUSTED and not self.allow_untrusted_local_install():
            return PackageVerificationResult(
                plugin_id=manifest.plugin_id,
                version=manifest.version,
                publisher_id=publisher_id,
                checksum_sha256=checksum_sha256,
                expected_checksum_sha256=expected_checksum,
                checksum_verified=checksum_verified,
                signature=signature,
                signature_algorithm=signature_algorithm,
                signing_key_id=signing_key_id,
                signature_verified=signature_verified,
                trust_level=trust_level,
                trust_source=trust_source,
                verification_state=VERIFICATION_BLOCKED,
                install_allowed=False,
                reason="untrusted_local_blocked",
            )

        verification_state = (
            VERIFICATION_VERIFIED
            if trust_level in {TRUST_FIRST_PARTY, TRUST_THIRD_PARTY}
            else VERIFICATION_UNTRUSTED
        )
        return PackageVerificationResult(
            plugin_id=manifest.plugin_id,
            version=manifest.version,
            publisher_id=publisher_id,
            checksum_sha256=checksum_sha256,
            expected_checksum_sha256=expected_checksum,
            checksum_verified=checksum_verified or not require_checksum,
            signature=signature,
            signature_algorithm=signature_algorithm,
            signing_key_id=signing_key_id,
            signature_verified=signature_verified or not require_signature,
            trust_level=trust_level,
            trust_source=trust_source,
            verification_state=verification_state,
            install_allowed=True,
        )

    def trust_for_plugin(
        self,
        plugin_id: str,
        *,
        manifest_path: Path | None = None,
        distribution: PluginDistributionSpec | None = None,
    ) -> PluginTrustDecision:
        item = self._installed_state_item(plugin_id)
        if item:
            return PluginTrustDecision(
                plugin_id=plugin_id,
                publisher_id=str(item.get("publisher_id", "") or "").strip(),
                source_kind=str(item.get("source", "") or "installed").strip() or "installed",
                trust_level=str(item.get("trust_level", "") or TRUST_UNTRUSTED).strip() or TRUST_UNTRUSTED,
                trust_source=str(item.get("trust_source", "") or "installed_state").strip(),
                verification_state=(
                    str(item.get("verification_state", "") or VERIFICATION_UNTRUSTED).strip()
                    or VERIFICATION_UNTRUSTED
                ),
                checksum_verified=bool(item.get("checksum_verified", False)),
                signature_verified=bool(item.get("signature_verified", False)),
            )

        source_kind = self.source_kind_for_path(manifest_path) if manifest_path else "external"
        publisher_id = _normalized_publisher_id(distribution.publisher_id if distribution else "", "")
        publisher = self.publisher_policy(publisher_id)
        trust_level = TRUST_UNTRUSTED
        trust_source = "source_path"
        verification_state = VERIFICATION_UNTRUSTED
        if source_kind == "bundled":
            if publisher and publisher.trust_level in {TRUST_FIRST_PARTY, TRUST_THIRD_PARTY}:
                trust_level = publisher.trust_level
                trust_source = "publisher_policy"
            elif distribution and distribution.owner_type == TRUST_FIRST_PARTY:
                trust_level = TRUST_FIRST_PARTY
                trust_source = "bundled_distribution"
            verification_state = (
                VERIFICATION_VERIFIED
                if trust_level in {TRUST_FIRST_PARTY, TRUST_THIRD_PARTY}
                else VERIFICATION_UNTRUSTED
            )
        return PluginTrustDecision(
            plugin_id=plugin_id,
            publisher_id=publisher_id,
            source_kind=source_kind,
            trust_level=trust_level,
            trust_source=trust_source,
            verification_state=verification_state,
        )

    def source_kind_for_path(self, manifest_path: Path | None) -> str:
        if manifest_path is None:
            return "external"
        path = manifest_path.resolve()
        if _is_relative_to(path, self._installed_dir):
            return "installed"
        if _is_relative_to(path, self._bundled_dir):
            return "bundled"
        return "external"

    def remote_entry(self, plugin_id: str, version: str = "") -> RemotePluginCatalogEntry | None:
        pid = str(plugin_id or "").strip()
        target_version = str(version or "").strip()
        for entry in self._remote_entries:
            if entry.plugin_id != pid:
                continue
            if target_version and entry.version != target_version:
                continue
            return entry
        return None

    def publisher_policy(self, publisher_id: str) -> PublisherTrustPolicy | None:
        return self._publishers.get(str(publisher_id or "").strip())

    def allow_untrusted_local_install(self) -> bool:
        return bool(self._raw_policy.get("allow_untrusted_local_install", True))

    def trusted_plugin_ids(self) -> set[str]:
        raw = self._raw_policy.get("trusted_plugin_ids")
        if not isinstance(raw, list):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    def installed_state_item(self, plugin_id: str) -> dict[str, Any]:
        return dict(self._installed_state_item(plugin_id))

    def _installed_state_item(self, plugin_id: str) -> dict[str, Any]:
        plugins = self._installed_state.get("plugins")
        if not isinstance(plugins, dict):
            return {}
        item = plugins.get(str(plugin_id or "").strip())
        return dict(item) if isinstance(item, dict) else {}


def compute_package_checksum(source_path: Path) -> str:
    path = source_path.expanduser().resolve()
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    digest = hashlib.sha256()
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relpath = file_path.relative_to(path).as_posix()
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _load_publishers(raw: Any) -> dict[str, PublisherTrustPolicy]:
    if not isinstance(raw, dict):
        return {}
    publishers: dict[str, PublisherTrustPolicy] = {}
    for publisher_id, item in raw.items():
        if not isinstance(item, dict):
            continue
        normalized_id = str(publisher_id or "").strip()
        if not normalized_id:
            continue
        trust_level = str(item.get("trust_level", "") or "").strip() or TRUST_THIRD_PARTY
        key_specs = _load_key_specs(item)
        key_spec = key_specs[0] if key_specs else None
        require_checksum = bool(item.get("require_checksum", trust_level != TRUST_UNTRUSTED))
        require_signature = bool(
            item.get("require_signature", trust_level == TRUST_THIRD_PARTY and key_spec is not None)
        )
        publishers[normalized_id] = PublisherTrustPolicy(
            publisher_id=normalized_id,
            display_name=str(item.get("display_name", "") or "").strip(),
            trust_level=trust_level,
            require_checksum=require_checksum,
            require_signature=require_signature,
            key_spec=key_spec,
            key_specs=key_specs,
        )
    return publishers


def _load_key_specs(raw: dict[str, Any]) -> tuple[PublisherKeySpec, ...]:
    items: list[PublisherKeySpec] = []
    explicit = raw.get("signature_keys")
    if isinstance(explicit, list):
        for index, item in enumerate(explicit):
            key_spec = _load_key_spec(item, default_key_id=f"key_{index}")
            if key_spec:
                items.append(key_spec)
    legacy = _load_key_spec(raw.get("signature"), default_key_id="default")
    if legacy:
        if not any(spec.key_id == legacy.key_id for spec in items):
            items.insert(0, legacy)
    return tuple(items)


def _load_key_spec(raw: Any, *, default_key_id: str) -> PublisherKeySpec | None:
    if not isinstance(raw, dict):
        return None
    key_id = str(raw.get("key_id", "") or "").strip() or str(default_key_id or "").strip() or "default"
    algorithm = str(raw.get("algorithm", "") or "").strip().lower()
    modulus_hex = str(raw.get("modulus_hex", "") or "").strip().lower()
    public_exponent = str(raw.get("public_exponent", "") or "").strip()
    if algorithm != "rsa-sha256" or not modulus_hex or not public_exponent:
        return None
    return PublisherKeySpec(
        key_id=key_id,
        algorithm=algorithm,
        public_exponent=public_exponent,
        modulus_hex=modulus_hex,
    )


def _signature_message(plugin_id: str, version: str, checksum_sha256: str) -> bytes:
    payload = f"{plugin_id}:{version}:{checksum_sha256}"
    return payload.encode("utf-8")


def _verify_rsa_signature(key_spec: PublisherKeySpec, message: bytes, signature: str) -> bool:
    if key_spec.algorithm != "rsa-sha256":
        return False
    try:
        modulus = int(key_spec.modulus_hex, 16)
        exponent = int(str(key_spec.public_exponent), 0)
        signature_bytes = base64.b64decode(signature, validate=True)
    except Exception:
        return False
    if modulus <= 1 or exponent <= 1:
        return False
    key_size = (modulus.bit_length() + 7) // 8
    if len(signature_bytes) != key_size:
        return False
    decoded = pow(int.from_bytes(signature_bytes, "big"), exponent, modulus).to_bytes(key_size, "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(message).digest()
    padding_length = key_size - len(digest_info) - 3
    if padding_length < 8:
        return False
    expected = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    return hmac.compare_digest(decoded, expected)


def verify_signed_message(
    *,
    publisher: PublisherTrustPolicy | None,
    message: bytes,
    signature: str,
    signature_algorithm: str,
    signing_key_id: str = "",
) -> bool:
    if not publisher or not signature:
        return False
    algorithm = str(signature_algorithm or "").strip().lower()
    if not algorithm:
        return False
    candidates = _candidate_keys(publisher, signing_key_id=signing_key_id, signature_algorithm=algorithm)
    for key_spec in candidates:
        if _verify_rsa_signature(key_spec, message, signature):
            return True
    return False


def _candidate_keys(
    publisher: PublisherTrustPolicy,
    *,
    signing_key_id: str,
    signature_algorithm: str,
) -> tuple[PublisherKeySpec, ...]:
    key_id = str(signing_key_id or "").strip()
    algorithm = str(signature_algorithm or "").strip().lower()
    keys = tuple(
        spec for spec in (publisher.key_specs or ()) if spec.algorithm == algorithm
    ) or ((publisher.key_spec,) if publisher.key_spec and publisher.key_spec.algorithm == algorithm else ())
    if key_id:
        keyed = tuple(spec for spec in keys if spec.key_id == key_id)
        if keyed:
            return keyed
    return keys


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalized_checksum(value: str) -> str:
    return str(value or "").strip().lower()


def _normalized_publisher_id(primary: str, fallback: str) -> str:
    text = str(primary or "").strip()
    if text:
        return text
    return str(fallback or "").strip()


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
