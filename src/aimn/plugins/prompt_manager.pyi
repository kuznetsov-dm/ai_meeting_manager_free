from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

@dataclass(frozen=True)
class PromptPreset:
    preset_id: str
    label: str
    prompt: str


def load_prompt_presets() -> list[PromptPreset]: ...


def normalize_presets(raw: Iterable[object]) -> list[PromptPreset]: ...


def resolve_prompt(profile_id: str, presets: Iterable[PromptPreset], custom: str) -> str: ...


def build_prompt(
    transcript: str,
    main_prompt: str,
    language_override: str,
    max_words: int,
) -> str: ...


def build_prompt_preview(
    profile_id: str,
    *,
    custom_prompt: str = "",
    language_override: str = "",
    max_words: int = 600,
    transcript_sample: str | None = None,
) -> str: ...


def compute_prompt_signature(profile_id: str, custom_prompt: str = "") -> str: ...


def default_prompt_manager_settings() -> dict[str, object]: ...
