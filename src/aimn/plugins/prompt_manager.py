from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from aimn.core.app_paths import get_app_root, get_config_dir
from aimn.core.settings_store import SettingsStore

_PROMPT_MANAGER_PLUGIN_ID = "service.prompt_manager"
_PROMPT_MANAGER_LEGACY_PLUGIN_ID = "ui.prompt_manager"
_DEFAULT_PROFILE_ID = "standard"
_STANDARD_PROFILE_IDS: tuple[str, ...] = ("brief", "standard", "detailed", "transcript_edit")
_PROMPT_TEMPLATE_REL_PATH = Path("config") / "prompts" / "meeting_summary_prompt.json"
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DEFAULT_PREVIEW_RUNTIME_INPUT = (
    "[APPROVED_CONTEXT_START]\n"
    "Agenda: Project review, blockers, next milestones.\n"
    "Projects: Apollo, Hermes.\n"
    "[APPROVED_CONTEXT_END]\n\n"
    "[MEETING_TRANSCRIPT_START]\n"
    "Speaker A: We need to move release to next Friday.\n"
    "Speaker B: I will prepare the updated rollout plan.\n"
    "[MEETING_TRANSCRIPT_END]"
)


@dataclass(frozen=True)
class PromptPreset:
    preset_id: str
    label: str
    prompt: str


def load_prompt_presets() -> list[PromptPreset]:
    defaults = normalize_presets(default_prompt_manager_settings().get("profiles", []))
    settings = _load_prompt_manager_settings()
    raw_profiles = settings.get("profiles")
    if not isinstance(raw_profiles, list):
        raw_profiles = settings.get("presets")
    configured = normalize_presets(raw_profiles if isinstance(raw_profiles, list) else [])
    if configured:
        return _merge_presets_with_defaults(configured, defaults=defaults)
    return defaults


def normalize_presets(raw: Iterable[object]) -> list[PromptPreset]:
    presets: list[PromptPreset] = []
    if not isinstance(raw, Iterable):
        return presets
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        preset_id = _normalize_profile_id(str(entry.get("id", entry.get("preset_id", "")) or ""))
        if not preset_id:
            continue
        label = str(entry.get("label", preset_id)).strip() or preset_id
        prompt = str(entry.get("prompt", entry.get("request_body", "")) or "").strip()
        if not prompt:
            continue
        presets.append(PromptPreset(preset_id=preset_id, label=label, prompt=prompt))
    return presets


def resolve_prompt(profile_id: str, presets: Iterable[PromptPreset], custom: str) -> str:
    resolved_profile = _normalize_profile_id(profile_id)
    if not resolved_profile:
        resolved_profile = _active_profile()
    if resolved_profile == "custom":
        inline = str(custom or "").strip()
        if inline:
            return inline
        return str(_merged_prompt_settings().get("custom_prompt_default", "") or "").strip()

    by_id = {preset.preset_id: preset for preset in presets}
    picked = by_id.get(resolved_profile)
    if picked and picked.prompt:
        return picked.prompt

    fallback_profile = _normalize_profile_id(str(_merged_prompt_settings().get("active_profile", "") or ""))
    fallback = by_id.get(fallback_profile or _DEFAULT_PROFILE_ID) or by_id.get(_DEFAULT_PROFILE_ID)
    if fallback and fallback.prompt:
        return fallback.prompt

    for preset in presets:
        if preset.prompt:
            return preset.prompt
    return ""


def build_prompt(
    transcript: str,
    main_prompt: str,
    language_override: str,
    max_words: int,
) -> str:
    transcript_text = str(transcript or "").strip()
    request_body = str(main_prompt or "").strip()
    if not request_body:
        return ""
    language_override = (language_override or "").strip()
    words_limit = int(max_words) if max_words else 600
    context_block, cleaned_transcript = _split_runtime_input(transcript_text)
    inferred_language = _infer_prompt_language(cleaned_transcript, language_override)
    language_line = _language_instruction(language_override, inferred_language)

    sections = _resolve_prompt_sections()
    service_final = _localized_service_final(sections.get("service_final"), inferred_language)
    values = {
        "language_instruction": language_line,
        "max_words": str(words_limit),
        "request_body": request_body,
        "context_block": context_block,
        "transcript": cleaned_transcript,
    }
    parts = [
        language_line,
        _render_section(sections.get("service_start"), values),
        _render_section(sections.get("request_wrapper"), values),
        _render_section(sections.get("context"), values),
        service_final,
        _render_section(sections.get("input_wrapper"), values),
        f"FINAL LANGUAGE RULE:\n{language_line}",
    ]
    return "\n\n".join(part for part in parts if part).strip()


def _infer_prompt_language(transcript: str, language_override: str) -> str:
    explicit = str(language_override or "").strip()
    if explicit:
        return explicit
    text = str(transcript or "")
    cyrillic_count = len(_CYRILLIC_RE.findall(text))
    latin_count = len(_LATIN_RE.findall(text))
    if cyrillic_count >= 80 and cyrillic_count >= latin_count * 2:
        return "Russian"
    return ""


def _language_instruction(language_override: str, inferred_language: str) -> str:
    explicit = str(language_override or "").strip()
    inferred = str(inferred_language or "").strip()
    if explicit:
        return (
            f"IMPORTANT: Write the final answer only in {explicit}. "
            "Do not switch to English or any other language."
        )
    if inferred.lower() == "russian":
        return (
            "IMPORTANT: Write the final answer only in Russian. "
            "Use natural Russian wording and Cyrillic in all headings, bullets, and section names. "
            "Do not switch to English."
        )
    return (
        "IMPORTANT: Write the final answer only in the language of the transcript. "
        "If unclear, use the dominant language in the transcript. Do not switch to English."
    )


def _localized_service_final(template: str | None, inferred_language: str) -> str:
    inferred = str(inferred_language or "").strip().lower()
    if inferred == "russian":
        return (
            "СТРУКТУРА ОТВЕТА (все разделы обязательны):\n"
            "### Тема встречи\n"
            "### Задачи, поручения, активности (с датами, если есть)\n"
            "### Названия проектов\n"
            "### Ключевые решения / итоги\n"
            "### Краткое резюме встречи\n"
            "### Краткий ход обсуждения"
        )
    return str(template or "").strip()


def build_prompt_preview(
    profile_id: str,
    *,
    custom_prompt: str = "",
    language_override: str = "",
    max_words: int = 600,
    transcript_sample: str | None = None,
) -> str:
    presets = load_prompt_presets()
    selected_body = resolve_prompt(profile_id, presets, custom_prompt)
    sample = str(transcript_sample).strip() if transcript_sample is not None else _DEFAULT_PREVIEW_RUNTIME_INPUT
    try:
        words_limit = int(max_words)
    except Exception:
        words_limit = 600
    if words_limit <= 0:
        words_limit = 600
    return build_prompt(
        transcript=sample,
        main_prompt=selected_body,
        language_override=language_override,
        max_words=words_limit,
    )


def compute_prompt_signature(profile_id: str, custom_prompt: str = "") -> str:
    presets = load_prompt_presets()
    resolved_profile = _normalize_profile_id(profile_id) or _active_profile()
    request_body = resolve_prompt(resolved_profile, presets, custom_prompt)
    sections = _resolve_prompt_sections()
    payload = {
        "profile_id": resolved_profile,
        "request_body": request_body,
        "sections": sections,
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def default_prompt_manager_settings() -> dict[str, object]:
    template = _load_prompt_template_payload()
    profiles = normalize_presets(template.get("profiles", []))
    active = _normalize_profile_id(str(template.get("active_profile", "") or "")) or _DEFAULT_PROFILE_ID
    custom_default = str(template.get("custom_prompt_default", "") or "").strip()
    sections = template.get("sections")
    normalized_sections: dict[str, str] = {}
    if isinstance(sections, dict):
        for key in ("service_start", "request_wrapper", "context", "service_final", "input_wrapper"):
            value = str(sections.get(key, "") or "").strip()
            if value:
                normalized_sections[key] = value
    return {
        "profiles": [
            {
                "id": preset.preset_id,
                "label": preset.label,
                "prompt": preset.prompt,
            }
            for preset in profiles
        ],
        "active_profile": active,
        "custom_prompt_default": custom_default,
        "sections": normalized_sections,
    }


def _load_prompt_manager_settings() -> dict:
    repo_root = get_app_root()
    store = SettingsStore(get_config_dir(repo_root) / "settings", repo_root=repo_root)
    settings = store.get_settings(_PROMPT_MANAGER_PLUGIN_ID)
    if not settings:
        settings = store.get_settings(_PROMPT_MANAGER_LEGACY_PLUGIN_ID)
    return dict(settings) if isinstance(settings, dict) else {}


def _active_profile() -> str:
    settings = _merged_prompt_settings()
    profile = _normalize_profile_id(str(settings.get("active_profile", "") or ""))
    return profile or _DEFAULT_PROFILE_ID


def _merged_prompt_settings() -> dict[str, object]:
    defaults = default_prompt_manager_settings()
    settings = _load_prompt_manager_settings()
    merged = dict(defaults)
    if not settings:
        return merged

    raw_profiles = settings.get("profiles")
    if not isinstance(raw_profiles, list):
        raw_profiles = settings.get("presets")
    configured = normalize_presets(raw_profiles if isinstance(raw_profiles, list) else [])
    defaults_profiles = normalize_presets(defaults.get("profiles", []))
    merged["profiles"] = [
        {"id": item.preset_id, "label": item.label, "prompt": item.prompt}
        for item in _merge_presets_with_defaults(configured, defaults=defaults_profiles)
    ]

    active = _normalize_profile_id(str(settings.get("active_profile", "") or ""))
    if active:
        merged["active_profile"] = active

    custom_default = str(settings.get("custom_prompt_default", "") or "").strip()
    if custom_default:
        merged["custom_prompt_default"] = custom_default

    raw_sections = settings.get("sections")
    if isinstance(raw_sections, dict):
        merged_sections = dict(defaults.get("sections", {}))
        if not str(raw_sections.get("input_wrapper", "") or "").strip():
            legacy = str(raw_sections.get("transcript_wrapper", "") or "").strip()
            if legacy:
                merged_sections["input_wrapper"] = legacy
        for key in ("service_start", "request_wrapper", "context", "service_final", "input_wrapper"):
            value = str(raw_sections.get(key, "") or "").strip()
            if value:
                merged_sections[key] = value
        merged["sections"] = merged_sections

    return merged


def _resolve_prompt_sections() -> dict[str, str]:
    settings = _merged_prompt_settings()
    raw = settings.get("sections")
    sections = dict(raw) if isinstance(raw, dict) else {}
    required_defaults = default_prompt_manager_settings().get("sections", {})
    if isinstance(required_defaults, dict):
        for key, value in required_defaults.items():
            if not str(sections.get(key, "") or "").strip():
                sections[key] = str(value or "")
    if not str(sections.get("input_wrapper", "") or "").strip():
        legacy = str(sections.get("transcript_wrapper", "") or "").strip()
        if legacy:
            sections["input_wrapper"] = legacy
    return {
        key: str(sections.get(key, "") or "").strip()
        for key in ("service_start", "request_wrapper", "context", "service_final", "input_wrapper")
        if str(sections.get(key, "") or "").strip()
    }


def _load_prompt_template_payload() -> dict:
    path = get_app_root() / _PROMPT_TEMPLATE_REL_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return raw if isinstance(raw, dict) else {}


def _normalize_profile_id(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    aliases = {
        "essential": "brief",
        "short": "brief",
        "default": "standard",
        "normal": "standard",
        "extended": "detailed",
        "edit": "transcript_edit",
        "transcript_editing": "transcript_edit",
    }
    return aliases.get(raw, raw)


def _merge_presets_with_defaults(
    configured: list[PromptPreset],
    *,
    defaults: list[PromptPreset],
) -> list[PromptPreset]:
    merged: dict[str, PromptPreset] = {item.preset_id: item for item in defaults if item.prompt}
    for item in configured:
        if item.prompt:
            merged[item.preset_id] = item

    ordered: list[PromptPreset] = []
    seen: set[str] = set()

    for preset_id in _STANDARD_PROFILE_IDS:
        preset = merged.get(preset_id)
        if preset and preset.prompt:
            ordered.append(preset)
            seen.add(preset_id)

    for preset in defaults:
        if preset.preset_id in seen:
            continue
        selected = merged.get(preset.preset_id)
        if selected and selected.prompt:
            ordered.append(selected)
            seen.add(preset.preset_id)

    for preset_id, preset in merged.items():
        if preset_id in seen:
            continue
        ordered.append(preset)

    return ordered


def _render_section(template: str | None, values: dict[str, str]) -> str:
    text = str(template or "").strip()
    if not text:
        return ""
    rendered = text
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value or ""))
    return rendered.strip()


def _split_runtime_input(raw_text: str) -> tuple[str, str]:
    text = str(raw_text or "").strip()
    if not text:
        return "", ""
    context = _slice_between(text, "[APPROVED_CONTEXT_START]", "[APPROVED_CONTEXT_END]")
    transcript = _slice_between(text, "[MEETING_TRANSCRIPT_START]", "[MEETING_TRANSCRIPT_END]")
    if transcript:
        return context, transcript
    return "", text


def _slice_between(text: str, start: str, end: str) -> str:
    left = text.find(start)
    if left < 0:
        return ""
    left += len(start)
    right = text.find(end, left)
    if right < 0:
        return ""
    return str(text[left:right]).strip()

