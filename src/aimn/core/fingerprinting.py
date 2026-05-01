from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_json(value: Any) -> str:
    normalized = _normalize(value)
    return json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def compute_fingerprint(
    stage_id: str,
    plugin_id: str,
    plugin_version: str,
    params: Dict[str, Any],
    input_fingerprints: Iterable[str],
) -> str:
    inputs = sorted(input_fingerprints)
    payload = {
        "stage_id": stage_id,
        "plugin_id": plugin_id,
        "plugin_version": plugin_version,
        "params": params,
        "inputs": inputs,
    }
    digest = hashlib.sha1(canonical_json(payload).encode("utf-8"))
    return f"sha1:{digest.hexdigest()}"


def compute_source_fingerprint(path: str) -> str:
    file_path = Path(path)
    stat = file_path.stat()
    size = stat.st_size
    digest = hashlib.sha1()
    digest.update(f"size:{size}\n".encode("utf-8"))
    full_read_limit = 8 * 1024 * 1024
    chunk_size = 1024 * 1024
    with file_path.open("rb") as handle:
        if size <= full_read_limit:
            digest.update(handle.read())
        else:
            head = handle.read(chunk_size)
            digest.update(head)
            if size > chunk_size:
                handle.seek(-chunk_size, 2)
                tail = handle.read(chunk_size)
                digest.update(tail)
    return f"sha1:{digest.hexdigest()}"
