from __future__ import annotations

from aimn.plugins.api import ArtifactSchema
from aimn.plugins.interfaces import KIND_SUMMARY
from aimn.plugins.prompt_manager import default_prompt_manager_settings, normalize_presets


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_SUMMARY, ArtifactSchema(content_type="text/markdown", user_visible=True))
        ctx.register_settings_schema(settings_schema)
        _ensure_default_settings(ctx)


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "Prompt Manager",
        "description": "Manage standard and custom prompt profiles for AI summaries.",
        "layout": {
            "type": "tabs",
            "tabs": [
                {"id": "profiles", "title": "Profiles"},
                {"id": "defaults", "title": "Defaults"},
            ],
        },
        "views": [
            {
                "id": "profiles",
                "type": "repeater",
                "binding": "profiles",
                "title": "Profiles",
                "item_title": {"field": "label"},
                "item_actions": [
                    {"id": "duplicate_profile", "label": "Duplicate"},
                    {"id": "delete_profile", "label": "Delete", "dangerous": True},
                ],
                "fields": [
                    {"id": "id", "type": "string", "label": "ID", "required": True},
                    {"id": "label", "type": "string", "label": "Label", "required": True},
                    {"id": "prompt", "type": "multiline", "label": "Request body", "required": True},
                ],
                "add_button": {"label": "Add Profile", "defaults": {"label": "New", "prompt": ""}},
            },
            {
                "id": "defaults",
                "type": "form",
                "sections": [
                    {
                        "id": "selection",
                        "title": "Default profile",
                        "fields": [
                            {
                                "id": "active_profile",
                                "label": "Active profile",
                                "type": "enum",
                                "default": "standard",
                                "options": [
                                    {"label": "Brief", "value": "brief"},
                                    {"label": "Standard", "value": "standard"},
                                    {"label": "Detailed", "value": "detailed"},
                                    {"label": "Transcript edit", "value": "transcript_edit"},
                                    {"label": "Custom", "value": "custom"},
                                ],
                            },
                            {
                                "id": "custom_prompt_default",
                                "label": "Custom default request body",
                                "type": "multiline",
                                "default": "",
                            },
                        ],
                    }
                ],
            },
        ],
    }


def _ensure_default_settings(ctx) -> None:
    defaults = default_prompt_manager_settings()
    settings = dict(ctx.get_settings() or {})
    payload = dict(settings)

    raw_profiles = settings.get("profiles")
    if not isinstance(raw_profiles, list):
        raw_profiles = settings.get("presets")
    profiles = normalize_presets(raw_profiles if isinstance(raw_profiles, list) else [])
    if not profiles:
        profiles = normalize_presets(defaults.get("profiles", []))
    payload["profiles"] = [
        {"id": item.preset_id, "label": item.label, "prompt": item.prompt}
        for item in profiles
    ]
    payload.pop("presets", None)

    active = str(settings.get("active_profile", "") or "").strip().lower()
    if not active:
        active = str(defaults.get("active_profile", "standard") or "standard").strip().lower()
    payload["active_profile"] = active

    custom_default = str(settings.get("custom_prompt_default", "") or "").strip()
    if not custom_default:
        custom_default = str(defaults.get("custom_prompt_default", "") or "").strip()
    payload["custom_prompt_default"] = custom_default

    default_sections = defaults.get("sections")
    if isinstance(default_sections, dict):
        raw_sections = settings.get("sections")
        sections = dict(raw_sections) if isinstance(raw_sections, dict) else {}
        legacy_input = str(sections.get("transcript_wrapper", "") or "").strip()
        if legacy_input and not str(sections.get("input_wrapper", "") or "").strip():
            sections["input_wrapper"] = legacy_input
        sections.pop("transcript_wrapper", None)
        for key, value in default_sections.items():
            if not str(sections.get(key, "") or "").strip():
                sections[key] = str(value or "")
        payload["sections"] = sections

    ctx.set_settings(payload, secret_fields=[])
