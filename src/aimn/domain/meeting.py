from __future__ import annotations

import re
from pathlib import PurePath
from typing import ClassVar, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION}


class AimnBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ArtifactRef(AimnBaseModel):
    kind: str
    path: str
    content_type: Optional[str] = None
    user_visible: bool = True
    meta: Dict[str, object] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def validate_flat_relative_path(cls, value: str) -> str:
        path = PurePath(value)
        if path.is_absolute():
            raise ValueError("Artifact path must be relative")
        if ".." in path.parts or len(path.parts) != 1:
            raise ValueError("Artifact path must be flat (no directories)")
        return value


class NodeTool(AimnBaseModel):
    plugin_id: str
    version: str


class NodeInputs(AimnBaseModel):
    source_ids: List[str] = Field(default_factory=list)
    parent_nodes: List[str] = Field(default_factory=list)


class LineageNode(AimnBaseModel):
    stage_id: str
    tool: NodeTool
    params: Dict[str, object] = Field(default_factory=dict)
    inputs: NodeInputs
    fingerprint: str
    cacheable: bool = True
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    created_at: Optional[str] = None


class PipelineStageResult(AimnBaseModel):
    stage_id: str
    status: str
    duration_ms: Optional[int] = None
    cache_hit: Optional[bool] = None
    error: Optional[str] = None
    skip_reason: Optional[str] = None

    @field_validator("duration_ms")
    @classmethod
    def validate_duration(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("duration_ms must be non-negative")
        return value


class PipelineRun(AimnBaseModel):
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    force_run: bool = False
    result: str
    stages: List[PipelineStageResult] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class SourceItem(AimnBaseModel):
    source_id: str
    input_filename: str
    input_path: str
    size_bytes: Optional[int] = None
    mtime_utc: Optional[str] = None
    content_fingerprint: Optional[str] = None


class SourceInfo(AimnBaseModel):
    items: List[SourceItem] = Field(default_factory=list)


class StorageInfo(AimnBaseModel):
    backend: str = "files"
    output_dir_rel: str = "."

    @field_validator("output_dir_rel")
    @classmethod
    def validate_output_dir_rel(cls, value: str) -> str:
        path = PurePath(value)
        if path.is_absolute():
            raise ValueError("output_dir_rel must be relative")
        return value


class SegmentIndex(AimnBaseModel):
    index: int
    start_ms: int
    end_ms: int
    speaker: Optional[str] = None
    confidence: Optional[float] = None
    meta: Dict[str, object] = Field(default_factory=dict)

    @field_validator("end_ms")
    @classmethod
    def validate_segment_range(cls, value: int, info) -> int:
        start_ms = info.data.get("start_ms")
        if start_ms is not None and value < start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return value


class MeetingManifest(AimnBaseModel):
    schema_version: str
    meeting_id: str
    base_name: str
    created_at: str
    updated_at: str
    storage: StorageInfo
    source: SourceInfo
    naming_mode: str = "single"
    pipeline_runs: List[PipelineRun] = Field(default_factory=list)
    nodes: Dict[str, LineageNode] = Field(default_factory=dict)
    segments_index: List[SegmentIndex] = Field(default_factory=list)
    audio_relpath: Optional[str] = None
    segments_relpath: Optional[str] = None
    transcript_relpath: Optional[str] = None

    # Explicit version selection policy (UI-driven).
    # - active_aliases: last selected alias for a stage (view/navigation preference)
    # - pinned_aliases: user-pinned alias for a stage (drives downstream selection policy)
    active_aliases: Dict[str, str] = Field(default_factory=dict)
    pinned_aliases: Dict[str, str] = Field(default_factory=dict)

    _naming_modes: ClassVar[Set[str]] = {"single", "branched"}
    _meeting_id_pattern: ClassVar[re.Pattern[str]] = re.compile(r"^\d{6}-\d{4}_[A-Za-z0-9_-]+$")
    _base_name_pattern: ClassVar[re.Pattern[str]] = re.compile(r"^\d{6}-\d{4}_.+$")

    @field_validator("meeting_id")
    @classmethod
    def validate_meeting_id(cls, value: str) -> str:
        if not cls._meeting_id_pattern.match(value):
            raise ValueError("meeting_id must match YYMMDD-HHMM_<key>")
        return value

    @field_validator("base_name")
    @classmethod
    def validate_base_name(cls, value: str) -> str:
        path = PurePath(value)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise ValueError("base_name must be a flat name, not a path")
        if not cls._base_name_pattern.match(value):
            raise ValueError("base_name must match YYMMDD-HHMM_<short_source_name>")
        return value

    @field_validator("naming_mode")
    @classmethod
    def validate_naming_mode(cls, value: str) -> str:
        if value not in cls._naming_modes:
            raise ValueError(f"naming_mode must be one of: {sorted(cls._naming_modes)}")
        return value
