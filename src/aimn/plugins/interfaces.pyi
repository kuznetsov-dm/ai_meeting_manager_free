# ruff: noqa: F401, I001
from __future__ import annotations

from aimn.core.contracts import (
    KIND_ACTIONS,
    KIND_ASR_SEGMENTS_JSON,
    KIND_AUDIO,
    KIND_DEBUG_JSON,
    KIND_DECISIONS,
    KIND_DETECTED_LANGUAGE,
    KIND_EDITED,
    KIND_INDEX,
    KIND_SEGMENTS,
    KIND_SUMMARY,
    KIND_TRANSCRIPT,
    ActionDescriptor,
    ActionResult,
    Artifact,
    ArtifactMeta,
    ArtifactSchema,
    HookContext,
    JobStatus,
    PluginLogLevel,
    PluginOutput,
    PluginResult,
)

__all__: list[str]
