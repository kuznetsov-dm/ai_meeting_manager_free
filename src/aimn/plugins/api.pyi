# ruff: noqa: F401, I001
from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

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
    KIND_SEGMENTS,
    KIND_SUMMARY,
    KIND_TRANSCRIPT,
    PluginResult,
)


class PromptPreset:
    preset_id: str
    label: str
    prompt: str


class ManagementStoreProtocol(Protocol):
    def close(self) -> None: ...

    def list_tasks(self) -> list[dict[str, Any]]: ...

    def list_tasks_for_meeting(self, meeting_id: str) -> list[dict[str, Any]]: ...

    def list_projects(self) -> list[dict[str, Any]]: ...

    def list_projects_for_meeting(self, meeting_id: str) -> list[dict[str, Any]]: ...

    def list_agendas(self) -> list[dict[str, Any]]: ...

    def list_agendas_for_meeting(self, meeting_id: str) -> list[dict[str, Any]]: ...


def get_content(path: str, default: Any = ..., repo_root: Any = ...) -> Any: ...


def default_summary_system_prompt() -> str: ...


def open_management_store(ctx: HookContext) -> ManagementStoreProtocol: ...


def load_prompt_presets() -> list[PromptPreset]: ...


def normalize_presets(raw: Iterable[object]) -> list[PromptPreset]: ...


def resolve_prompt(profile_id: str, presets: Iterable[PromptPreset], custom: str) -> str: ...


def build_prompt(
    transcript: str,
    main_prompt: str,
    language_override: str,
    max_words: int,
) -> str: ...


def parse_progress(raw_line: str) -> int | None: ...


def emit_result(ctx: HookContext, result: PluginResult) -> None: ...


__all__: list[str]
