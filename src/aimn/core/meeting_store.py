from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from aimn.domain.meeting import MeetingManifest, SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS


class MeetingStore:
    def load(self, base_name: str) -> MeetingManifest:
        raise NotImplementedError

    def save(self, manifest: MeetingManifest) -> None:
        raise NotImplementedError

    def list_meetings(self) -> Iterable[str]:
        raise NotImplementedError

    def resolve_artifact_path(
        self, base_name: str, alias: Optional[str], kind: str, ext: str
    ) -> str:
        raise NotImplementedError

    def open_artifact(self, relpath: str, mode: str = "rb"):
        raise NotImplementedError


class FileMeetingStore(MeetingStore):
    def __init__(self, output_dir: Path | str) -> None:
        self.output_dir = Path(output_dir)

    def load(self, base_name: str) -> MeetingManifest:
        path = self._meeting_path(base_name)
        data = json.loads(path.read_text(encoding="utf-8"))
        migrated = _migrate_manifest_data(data)
        return MeetingManifest.model_validate(migrated)

    def save(self, manifest: MeetingManifest) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self._meeting_path(manifest.base_name)
        payload = manifest.model_dump(mode="json", exclude_none=True)
        data = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)

        fd, tmp_name = tempfile.mkstemp(dir=str(self.output_dir), prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def list_meetings(self) -> Iterable[str]:
        if not self.output_dir.exists():
            return []
        suffix = "__MEETING.json"
        return [p.name[: -len(suffix)] for p in self.output_dir.glob(f"*{suffix}")]

    def resolve_artifact_path(
        self, base_name: str, alias: Optional[str], kind: str, ext: str
    ) -> str:
        safe_ext = ext.lstrip(".")
        if alias:
            return f"{base_name}__{alias}.{kind}.{safe_ext}"
        return f"{base_name}.{kind}.{safe_ext}"

    def open_artifact(self, relpath: str, mode: str = "rb"):
        path = self._safe_path(relpath)
        return open(path, mode)

    def _meeting_path(self, base_name: str) -> Path:
        return self.output_dir / f"{base_name}__MEETING.json"

    def _safe_path(self, relpath: str) -> Path:
        rel = Path(relpath)
        if rel.is_absolute():
            raise ValueError("Artifact path must be relative")
        resolved = (self.output_dir / rel).resolve()
        if self.output_dir.resolve() not in resolved.parents and resolved != self.output_dir.resolve():
            raise ValueError("Artifact path escapes output directory")
        return resolved


def _migrate_manifest_data(data: dict) -> dict:
    version = data.get("schema_version")
    if not version:
        data["schema_version"] = SCHEMA_VERSION
        return data
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        return data
    return data
