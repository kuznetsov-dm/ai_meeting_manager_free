from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from aimn.core.atomic_io import atomic_write_text
from aimn.core.contracts import PluginOutput, StageEvent
from aimn.domain.meeting import ArtifactRef


def default_extensions_for_content_type(content_type: str) -> list[str] | None:
    ct = (content_type or "").lower()
    if ct == "text/markdown":
        return ["md"]
    if ct == "text" or ct.startswith("text/"):
        return ["txt"]
    if ct.endswith("json") or ct == "json" or ct == "application/json":
        return ["json"]
    if ct == "audio/wav" or ct.endswith("/wav"):
        return ["wav"]
    return None


class ArtifactWriter:
    def __init__(
        self,
        output_dir: Path,
        store,
        *,
        stage_id: str,
        validator: Callable[[Path, str, str], str | None],
        event_callback: Callable[[StageEvent], None] | None = None,
    ) -> None:
        self._output_dir = output_dir
        self._store = store
        self._stage_id = stage_id
        self._validator = validator
        self._event_callback = event_callback

    def write_output(
        self,
        base_name: str,
        alias: str | None,
        output: PluginOutput,
        *,
        ext: str | None = None,
        meta: dict | None = None,
    ) -> tuple[ArtifactRef | None, str, str | None]:
        content_type = output.content_type or "text"
        extensions = [ext] if ext else (default_extensions_for_content_type(content_type) or ["txt"])
        relpath = self._store.resolve_artifact_path(base_name, alias, output.kind, extensions[0])
        atomic_write_text(self._output_dir / relpath, output.content)
        error = self._validator(self._output_dir, relpath, output.kind)
        if error:
            return None, relpath, error
        artifact = ArtifactRef(
            kind=output.kind,
            path=relpath,
            content_type=content_type,
            user_visible=output.user_visible,
            meta=meta or {},
        )
        if self._event_callback:
            self._event_callback(
                StageEvent(
                    event_type="artifact_written",
                    stage_id=self._stage_id,
                    message=relpath,
                    alias=alias,
                    kind=output.kind,
                    relpath=relpath,
                )
            )
        return artifact, relpath, None

    def write_json_records(
        self,
        base_name: str,
        alias: str | None,
        *,
        kind: str,
        records: object,
        user_visible: bool = False,
        content_type: str = "json",
        meta: dict | None = None,
    ) -> tuple[ArtifactRef | None, str, str | None]:
        payload = json.dumps(records, ensure_ascii=True, indent=2)
        output = PluginOutput(
            kind=kind,
            content=payload,
            content_type=content_type,
            user_visible=user_visible,
        )
        return self.write_output(base_name, alias, output, ext="json", meta=meta)
