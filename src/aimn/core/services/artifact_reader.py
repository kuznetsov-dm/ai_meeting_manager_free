from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aimn.core.fingerprinting import compute_source_fingerprint


@dataclass(frozen=True)
class ArtifactInput:
    relpath: str
    path: Path
    content: str | None
    fingerprint: str | None


class ArtifactReader:
    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def read_text_with_fingerprint(self, relpath: str) -> ArtifactInput:
        path = self._output_dir / relpath
        if not path.exists():
            return ArtifactInput(relpath=relpath, path=path, content=None, fingerprint=None)
        content = path.read_text(encoding="utf-8", errors="ignore")
        fingerprint = compute_source_fingerprint(str(path))
        return ArtifactInput(relpath=relpath, path=path, content=content, fingerprint=fingerprint)

    def fingerprint(self, relpath: str) -> ArtifactInput:
        path = self._output_dir / relpath
        if not path.exists():
            return ArtifactInput(relpath=relpath, path=path, content=None, fingerprint=None)
        fingerprint = compute_source_fingerprint(str(path))
        return ArtifactInput(relpath=relpath, path=path, content=None, fingerprint=fingerprint)
