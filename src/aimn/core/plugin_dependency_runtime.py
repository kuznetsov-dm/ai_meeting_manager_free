from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import venv

from aimn.core.plugin_manifest import load_plugin_manifest


def resolve_plugin_python(repo_root: Path, plugin_id: str) -> str:
    repo = Path(repo_root).resolve()
    pid = str(plugin_id or "").strip()
    if not pid:
        return sys.executable

    info = _find_plugin(repo, pid)
    if not info:
        return sys.executable
    plugin_dir, dependencies = info
    requirements = plugin_dir / "requirements.txt"
    spec_hash = _dependency_spec_hash(dependencies, requirements)
    env_root = repo / "config" / "plugin_envs" / _safe_plugin_id(pid)
    venv_dir = env_root / "venv"
    python_path = _venv_python(venv_dir)
    lock_path = env_root / ".deps.lock"

    # If no declared dependencies, we still honor an already prepared venv.
    if not dependencies and not requirements.exists():
        return str(python_path) if python_path.exists() else sys.executable

    if python_path.exists() and lock_path.exists():
        if str(lock_path.read_text(encoding="utf-8", errors="ignore")).strip() == spec_hash:
            return str(python_path)

    if os.environ.get("AIMN_PLUGIN_AUTO_INSTALL_DEPS", "1").strip().lower() in {"0", "false", "no"}:
        return sys.executable

    if not _ensure_plugin_env(venv_dir, dependencies, requirements):
        return sys.executable

    try:
        env_root.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(spec_hash, encoding="utf-8")
    except Exception:
        pass
    return str(python_path) if python_path.exists() else sys.executable


def _find_plugin(repo_root: Path, plugin_id: str) -> tuple[Path, list[str]] | None:
    plugins_dir = repo_root / "plugins"
    if not plugins_dir.exists():
        return None
    for manifest_path in sorted(plugins_dir.rglob("plugin.json")):
        try:
            manifest = load_plugin_manifest(manifest_path)
        except Exception:
            continue
        if manifest.plugin_id != plugin_id:
            continue
        return manifest_path.parent, list(manifest.dependencies)
    return None


def _dependency_spec_hash(dependencies: list[str], requirements_path: Path) -> str:
    payload = {
        "dependencies": sorted([str(item).strip() for item in dependencies if str(item).strip()]),
        "requirements": "",
    }
    if requirements_path.exists():
        try:
            payload["requirements"] = requirements_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            payload["requirements"] = ""
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_pip(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "pip.exe"
    return venv_dir / "bin" / "pip"


def _ensure_plugin_env(venv_dir: Path, dependencies: list[str], requirements_path: Path) -> bool:
    logger = logging.getLogger("aimn.plugins.deps")
    try:
        if not _venv_python(venv_dir).exists():
            venv_dir.parent.mkdir(parents=True, exist_ok=True)
            builder = venv.EnvBuilder(with_pip=True)
            builder.create(str(venv_dir))
        pip_path = _venv_pip(venv_dir)
        if not pip_path.exists():
            return False
        timeout_seconds = int(os.environ.get("AIMN_PLUGIN_PIP_TIMEOUT_SECONDS", "180") or 180)
        if requirements_path.exists():
            proc = subprocess.run(
                [str(pip_path), "install", "-r", str(requirements_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if proc.returncode != 0:
                logger.warning(
                    "plugin_requirements_install_failed path=%s stderr=%s",
                    requirements_path,
                    (proc.stderr or proc.stdout or "")[-800:],
                )
                return False
        deps = [str(item).strip() for item in dependencies if str(item).strip()]
        if deps:
            proc = subprocess.run(
                [str(pip_path), "install", *deps],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if proc.returncode != 0:
                logger.warning(
                    "plugin_dependencies_install_failed deps=%s stderr=%s",
                    ",".join(deps),
                    (proc.stderr or proc.stdout or "")[-800:],
                )
                return False
        return True
    except Exception as exc:
        logger.warning("plugin_dependency_env_failed error=%s", exc)
        return False


def _safe_plugin_id(plugin_id: str) -> str:
    safe = str(plugin_id or "").strip()
    if not safe:
        return "plugin"
    for src, dst in (
        ("/", "_"),
        ("\\", "_"),
        (":", "_"),
        (" ", "_"),
    ):
        safe = safe.replace(src, dst)
    return safe

