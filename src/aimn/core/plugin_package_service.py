from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname, urlopen
from zipfile import BadZipFile, ZipFile

from aimn.core.app_paths import (
    get_installed_plugins_dir,
    get_installed_plugins_state_path,
    get_plugin_remote_catalog_path,
)
from aimn.core.atomic_io import atomic_write_text
from aimn.core.plugin_activation_service import PluginActivationService
from aimn.core.plugin_manifest import PluginManifest, load_plugin_manifest
from aimn.core.plugin_remote_catalog import load_remote_catalog
from aimn.core.plugin_trust import PackageVerificationResult, PluginTrustResolver

_MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
_ZIP_MIN_BYTES = 22


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PluginInstallResult:
    plugin_id: str
    version: str
    install_dir: Path
    source_path: Path
    replaced_existing: bool
    verification_state: str = ""
    trust_level: str = ""


@dataclass(frozen=True)
class PluginRemoveResult:
    plugin_id: str
    removed: bool
    removed_path: Path


class PluginPackageService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root
        self._installed_plugins_dir = get_installed_plugins_dir(app_root)
        self._installed_plugins_state_path = get_installed_plugins_state_path(app_root)
        self._activation = PluginActivationService(app_root)
        self._trust = PluginTrustResolver(app_root)

    def install_from_path(self, package_path: Path, *, expected_plugin_id: str = "") -> PluginInstallResult:
        source_path = package_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"plugin_package_missing:{source_path}")
        if source_path.is_file():
            _validate_plugin_package_file(source_path)
        with tempfile.TemporaryDirectory(prefix="aimn_plugin_install_") as temp_dir:
            source_root = self._prepare_source_root(source_path, Path(temp_dir))
            manifest_path = self._find_manifest_path(source_root)
            manifest = load_plugin_manifest(manifest_path)
            if expected_plugin_id and manifest.plugin_id != expected_plugin_id:
                raise ValueError(
                    f"plugin_package_unexpected_id:expected={expected_plugin_id}:actual={manifest.plugin_id}"
                )
            verification = self._trust.verify_package(source_path, manifest)
            if not verification.install_allowed:
                raise ValueError(f"plugin_package_verification_failed:{verification.reason}")
            target_dir = self._target_dir_for(manifest.plugin_id)
            replaced_existing = target_dir.exists()
            self._install_tree(source_root, target_dir)
            self._write_installed_state(
                manifest=manifest,
                target_dir=target_dir,
                source_path=source_path,
                runtime_state="active",
                verification=verification,
            )
            self._activation.ensure_state(manifest.plugin_id, enabled=False)
            return PluginInstallResult(
                plugin_id=manifest.plugin_id,
                version=manifest.version,
                install_dir=target_dir,
                source_path=source_path,
                replaced_existing=replaced_existing,
                verification_state=verification.verification_state,
                trust_level=verification.trust_level,
            )

    def install_from_catalog(self, plugin_id: str) -> PluginInstallResult:
        pid = str(plugin_id or "").strip()
        if not pid:
            raise ValueError("plugin_id_missing")
        entry = next((item for item in load_remote_catalog(get_plugin_remote_catalog_path(self._app_root)) if item.plugin_id == pid), None)
        if not entry:
            raise ValueError(f"plugin_catalog_entry_missing:{pid}")
        download_url = str(entry.download_url or "").strip()
        if not download_url:
            raise ValueError(f"plugin_catalog_download_missing:{pid}")
        with tempfile.TemporaryDirectory(prefix="aimn_plugin_catalog_") as temp_dir:
            temp_root = Path(temp_dir)
            package_path = self._download_package(download_url, temp_root, plugin_id=pid)
            return self.install_from_path(package_path, expected_plugin_id=pid)

    def remove_installed_plugin(self, plugin_id: str) -> PluginRemoveResult:
        pid = str(plugin_id or "").strip()
        if not pid:
            raise ValueError("plugin_id_missing")
        target_dir = self._installed_plugins_dir / pid
        removed = False
        if target_dir.exists():
            shutil.rmtree(target_dir)
            removed = True
        state = self._load_installed_state()
        plugins = state.setdefault("plugins", {})
        if isinstance(plugins, dict) and pid in plugins:
            plugins.pop(pid, None)
            self._save_installed_state(state)
        return PluginRemoveResult(plugin_id=pid, removed=removed, removed_path=target_dir)

    def inspect_package(self, package_path: Path) -> PluginManifest:
        source_path = package_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"plugin_package_missing:{source_path}")
        with tempfile.TemporaryDirectory(prefix="aimn_plugin_inspect_") as temp_dir:
            source_root = self._prepare_source_root(source_path, Path(temp_dir))
            manifest_path = self._find_manifest_path(source_root)
            return load_plugin_manifest(manifest_path)

    def _prepare_source_root(self, source_path: Path, temp_root: Path) -> Path:
        if source_path.is_dir():
            return source_path
        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            extracted_root = temp_root / "extracted"
            extracted_root.mkdir(parents=True, exist_ok=True)
            try:
                with ZipFile(source_path, "r") as archive:
                    self._extract_zip_safe(archive, extracted_root)
            except BadZipFile as exc:
                raise ValueError(
                    f"plugin_package_invalid_zip:{source_path.name}:{_plugin_package_validation_reason(source_path)}"
                ) from exc
            return extracted_root
        raise ValueError(f"plugin_package_unsupported:{source_path}")

    def _find_manifest_path(self, source_root: Path) -> Path:
        direct = source_root / "plugin.json"
        if direct.exists():
            return direct
        manifests = sorted(source_root.rglob("plugin.json"))
        if not manifests:
            raise FileNotFoundError(f"plugin_manifest_missing:{source_root}")
        return manifests[0]

    def _install_tree(self, source_root: Path, target_dir: Path) -> None:
        manifest_path = self._find_manifest_path(source_root)
        plugin_root = manifest_path.parent
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        backup_dir = target_dir.parent / f"{target_dir.name}.backup"
        temp_target = target_dir.parent / f"{target_dir.name}.installing"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        if temp_target.exists():
            shutil.rmtree(temp_target)
        shutil.copytree(plugin_root, temp_target)
        if target_dir.exists():
            target_dir.replace(backup_dir)
        temp_target.replace(target_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    def _write_installed_state(
        self,
        *,
        manifest: PluginManifest,
        target_dir: Path,
        source_path: Path,
        runtime_state: str,
        verification: PackageVerificationResult,
    ) -> None:
        state = self._load_installed_state()
        state["version"] = "1"
        plugins = state.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            state["plugins"] = plugins
        plugins[manifest.plugin_id] = {
            "installed_version": manifest.version,
            "source": "package",
            "source_path": str(source_path),
            "installed_path": str(target_dir),
            "runtime_state": runtime_state,
            "installed_at": _utc_now_iso(),
            "publisher_id": verification.publisher_id,
            "checksum_sha256": verification.checksum_sha256,
            "expected_checksum_sha256": verification.expected_checksum_sha256,
            "checksum_verified": verification.checksum_verified,
            "signature": verification.signature,
            "signature_algorithm": verification.signature_algorithm,
            "signing_key_id": verification.signing_key_id,
            "signature_verified": verification.signature_verified,
            "trust_level": verification.trust_level,
            "trust_source": verification.trust_source,
            "verification_state": verification.verification_state,
        }
        self._save_installed_state(state)

    def _load_installed_state(self) -> dict:
        path = self._installed_plugins_state_path
        if not path.exists():
            return {"version": "1", "plugins": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": "1", "plugins": {}}
        return payload if isinstance(payload, dict) else {"version": "1", "plugins": {}}

    def _save_installed_state(self, payload: dict) -> None:
        self._installed_plugins_state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._installed_plugins_state_path,
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        )

    def _target_dir_for(self, plugin_id: str) -> Path:
        pid = str(plugin_id or "").strip()
        if not pid:
            raise ValueError("plugin_id_missing")
        target_dir = (self._installed_plugins_dir / pid).resolve()
        installed_root = self._installed_plugins_dir.resolve()
        if not _is_relative_to(target_dir, installed_root):
            raise ValueError(f"plugin_install_path_invalid:{plugin_id}")
        return target_dir

    def _download_package(self, download_url: str, temp_root: Path, *, plugin_id: str) -> Path:
        raw_url = str(download_url or "").strip()
        local_candidate = Path(raw_url).expanduser()
        if raw_url and local_candidate.exists() and local_candidate.is_file():
            source = local_candidate.resolve()
            target = temp_root / (source.name or f"{plugin_id}.zip")
            shutil.copy2(source, target)
            _validate_plugin_package_file(target)
            return target
        parsed = urlparse(raw_url)
        if parsed.scheme in {"", "file"}:
            if parsed.scheme == "file":
                candidate = Path(url2pathname(f"{parsed.netloc}{parsed.path}"))
            else:
                candidate = Path(raw_url)
            source = candidate.expanduser().resolve()
            if not source.exists() or not source.is_file():
                raise FileNotFoundError(f"plugin_catalog_download_missing:{plugin_id}:{raw_url}")
            target = temp_root / (source.name or f"{plugin_id}.zip")
            shutil.copy2(source, target)
            _validate_plugin_package_file(target)
            return target
        if parsed.scheme not in {"https", "http"}:
            raise ValueError(f"plugin_catalog_download_scheme_invalid:{parsed.scheme}")
        suffix = Path(parsed.path).suffix or ".zip"
        target = temp_root / f"{plugin_id}{suffix}"
        written = 0
        with urlopen(raw_url) as response, target.open("wb") as handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"plugin_catalog_download_too_large:{plugin_id}")
                handle.write(chunk)
        if not target.exists() or os.path.getsize(target) <= 0:
            raise ValueError(f"plugin_catalog_download_empty:{plugin_id}")
        try:
            _validate_plugin_package_file(target)
        except ValueError:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        return target

    @staticmethod
    def _extract_zip_safe(archive: ZipFile, destination: Path) -> None:
        root = destination.resolve()
        for member in archive.infolist():
            member_name = str(member.filename or "").strip()
            if not member_name:
                continue
            target = (root / member_name).resolve()
            if not _is_relative_to(target, root):
                raise ValueError(f"plugin_package_zip_path_invalid:{member_name}")
            archive.extract(member, root)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_plugin_package_file(path: Path) -> None:
    file_path = path.expanduser().resolve()
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"plugin_package_missing:{file_path}")
    size = int(file_path.stat().st_size)
    if size <= 0:
        raise ValueError(f"plugin_package_empty:{file_path.name}")
    if size < _ZIP_MIN_BYTES:
        raise ValueError(f"plugin_package_too_small:{file_path.name}:{size}")
    try:
        with file_path.open("rb") as handle:
            header = handle.read(32)
    except OSError as exc:
        raise ValueError(f"plugin_package_unreadable:{file_path.name}") from exc
    if not header.startswith(b"PK"):
        raise ValueError(f"plugin_package_invalid_magic:{file_path.name}:{_plugin_package_magic_reason(header)}")
    if not _looks_like_zip(file_path):
        raise ValueError(f"plugin_package_invalid_zip:{file_path.name}:{_plugin_package_validation_reason(file_path)}")


def _looks_like_zip(path: Path) -> bool:
    try:
        with ZipFile(path, "r") as archive:
            archive.testzip()
        return True
    except BadZipFile:
        return False
    except OSError:
        return False


def _plugin_package_validation_reason(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            header = handle.read(128)
    except OSError:
        return "unreadable"
    if not header:
        return "empty"
    return _plugin_package_magic_reason(header)


def _plugin_package_magic_reason(header: bytes) -> str:
    prefix = bytes(header[:16]).lower()
    if prefix.startswith(b"<!do") or prefix.startswith(b"<html") or prefix.startswith(b"<head"):
        return "invalid_magic_html"
    if prefix.startswith(b"{") or prefix.startswith(b"["):
        return "invalid_magic_json"
    if prefix.startswith(b"pk"):
        return "invalid_zip_payload"
    hex_prefix = bytes(header[:8]).hex()
    return f"invalid_magic_{hex_prefix or 'empty'}"
