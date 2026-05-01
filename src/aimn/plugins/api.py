# ruff: noqa: I001
from __future__ import annotations

from pathlib import Path

from aimn.core.content_store import get_content
from aimn.core.management_store import ManagementStore
from aimn.plugins.prompt_manager import (
    build_prompt,
    load_prompt_presets,
    normalize_presets,
    resolve_prompt,
)
from aimn.plugins.progress_parser import parse_progress
from aimn.plugins.interfaces import (
    Artifact,
    ArtifactMeta,
    ArtifactSchema,
    HookContext,
    KIND_ACTIONS,
    KIND_ASR_SEGMENTS_JSON,
    KIND_AUDIO,
    KIND_DEBUG_JSON,
    KIND_DECISIONS,
    KIND_DETECTED_LANGUAGE,
    KIND_EDITED,
    KIND_INDEX,
    KIND_MANAGEMENT_SUGGESTIONS,
    KIND_SEGMENTS,
    KIND_SUMMARY,
    KIND_TRANSCRIPT,
    PluginResult,
)

__all__ = [
    "get_content",
    "default_summary_system_prompt",
    "open_management_store",
    "build_prompt",
    "load_prompt_presets",
    "normalize_presets",
    "resolve_prompt",
    "parse_progress",
    "HookContext",
    "ArtifactSchema",
    "Artifact",
    "ArtifactMeta",
    "KIND_ACTIONS",
    "KIND_ASR_SEGMENTS_JSON",
    "KIND_AUDIO",
    "KIND_DEBUG_JSON",
    "KIND_DECISIONS",
    "KIND_DETECTED_LANGUAGE",
    "KIND_EDITED",
    "KIND_INDEX",
    "KIND_MANAGEMENT_SUGGESTIONS",
    "KIND_SEGMENTS",
    "KIND_SUMMARY",
    "KIND_TRANSCRIPT",
    "emit_result",
]


def default_summary_system_prompt() -> str:
    return "Summarize the meeting transcript into concise bullet points."


def open_management_store(ctx: HookContext) -> ManagementStore:
    raw = getattr(ctx, "_output_dir", None)
    if raw:
        output_dir = Path(str(raw))
    else:
        output_dir = Path(__file__).resolve().parents[3] / "output"
    app_root = output_dir.parent
    return ManagementStore(app_root)


def emit_result(ctx: HookContext, result: PluginResult) -> None:
    for output in result.outputs:
        ctx.write_artifact(
            output.kind,
            output.content,
            content_type=output.content_type,
        )
    for warning in result.warnings:
        ctx.emit_warning(warning)
