from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from dataclasses import dataclass

from aimn.core.app_paths import get_app_root, get_config_dir


@dataclass(frozen=True)
class ContentBundle:
    data: dict
    source: str
    version: str
    mtime: float | None


_CONTENT_CACHE: dict[str, ContentBundle] = {}


def load_content_bundle(repo_root: Path | None = None) -> ContentBundle:
    root = repo_root or get_app_root()
    path = (get_config_dir(root) / "content.json").resolve()
    mtime = path.stat().st_mtime if path.exists() else None
    cached = _CONTENT_CACHE.get(str(path))
    if cached and cached.mtime == mtime:
        return cached
    if not path.exists():
        bundle = ContentBundle(data={}, source=str(path), version="missing", mtime=None)
        _CONTENT_CACHE[str(path)] = bundle
        return bundle
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logging.getLogger("aimn.content").warning("content_invalid path=%s error=%s", path, exc)
        bundle = ContentBundle(data={}, source=str(path), version="invalid", mtime=mtime)
        _CONTENT_CACHE[str(path)] = bundle
        return bundle
    version = str(data.get("version", "")).strip() if isinstance(data, dict) else ""
    bundle = ContentBundle(data=data if isinstance(data, dict) else {}, source=str(path), version=version, mtime=mtime)
    _CONTENT_CACHE[str(path)] = bundle
    return bundle


def load_content(repo_root: Path | None = None) -> dict:
    return load_content_bundle(repo_root).data


def content_metadata(repo_root: Path | None = None) -> dict:
    bundle = load_content_bundle(repo_root)
    return {"source": bundle.source, "version": bundle.version, "mtime": bundle.mtime}


def get_content(path: str, default: Any = None, repo_root: Path | None = None) -> Any:
    data: Any = load_content(repo_root)
    for part in path.split("."):
        if isinstance(data, list) and part.isdigit():
            index = int(part)
            if index < 0 or index >= len(data):
                return default
            data = data[index]
            continue
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data
