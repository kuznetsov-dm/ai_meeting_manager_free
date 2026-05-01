from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PluginHealthSettingsController:
    @staticmethod
    def required_setting_groups(
        plugin_id: str,
        settings: dict[str, Any],
        *,
        capabilities: dict[str, Any] | None,
        schema: object | None,
        looks_like_secret_key: Callable[[str], bool],
    ) -> list[tuple[str, list[str]]]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return []
        caps = dict(capabilities or {}) if isinstance(capabilities, dict) else {}
        health_caps = caps.get("health") if isinstance(caps, dict) else None
        has_explicit_required_settings = isinstance(health_caps, dict) and "required_settings" in health_caps
        cap_rules = PluginHealthSettingsController._cap_get(caps, "health", "required_settings", default=[])
        groups: list[tuple[str, list[str]]] = []
        if isinstance(cap_rules, list):
            for item in cap_rules:
                if not isinstance(item, dict):
                    continue
                when = item.get("when")
                if isinstance(when, dict):
                    matched = True
                    for key, expected in when.items():
                        actual = str(settings.get(str(key), "") or "").strip()
                        if actual != str(expected or "").strip():
                            matched = False
                            break
                    if not matched:
                        continue
                label = str(item.get("label", "") or "").strip()
                keys_raw = item.get("keys")
                keys = []
                if isinstance(keys_raw, list):
                    keys = [str(k or "").strip() for k in keys_raw if str(k or "").strip()]
                if label and keys:
                    groups.append((label, keys))
        if groups or has_explicit_required_settings:
            return groups

        settings_items = list(getattr(schema, "settings", []) or []) if schema is not None else []
        secrets = [str(getattr(item, "key", "") or "").strip() for item in settings_items if looks_like_secret_key(getattr(item, "key", ""))]
        if len(secrets) == 1:
            return [("Secret", [secrets[0]])]
        return []

    @staticmethod
    def run_required_settings_checks(
        *,
        stage_params: dict[str, Any],
        settings: dict[str, Any],
        groups: list[tuple[str, list[str]]],
        value_resolver: Callable[[dict[str, Any], dict[str, Any], str], Any],
        issue_factory: Callable[[str, str, str], object],
        normalize_code: Callable[[str, str], str],
    ) -> tuple[list[str], list[object]]:
        if not groups:
            return [], []
        checks = ["required_settings"]
        issues: list[object] = []
        for label, candidates in groups:
            if any(value_resolver(stage_params, settings, key) for key in candidates):
                continue
            hint = "Fill the required credentials in Settings."
            if "api key" in label.lower():
                hint = "Add the API key in Settings before running the stage."
            code = normalize_code(label, "required_setting_missing")
            issues.append(
                issue_factory(
                    code,
                    f"Missing required setting: {label}.",
                    hint,
                )
            )
        return checks, issues

    @staticmethod
    def _cap_get(payload: object, *keys: str, default: object = None) -> object:
        current = payload
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(str(key))
        return current if current is not None else default
