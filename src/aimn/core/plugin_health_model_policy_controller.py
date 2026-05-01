from __future__ import annotations

from typing import Any


class PluginHealthModelPolicyController:
    @staticmethod
    def models_storage_is_local(capabilities: dict[str, Any] | None) -> bool:
        if not isinstance(capabilities, dict):
            return False
        models = capabilities.get("models")
        if not isinstance(models, dict):
            return False
        return str(models.get("storage", "") or "").strip().lower() == "local"

    @staticmethod
    def resolve_model_id(stage_params: dict[str, Any], settings: dict[str, Any]) -> str:
        direct = str(
            stage_params.get("model_id", "")
            or stage_params.get("model", "")
            or settings.get("model_id", "")
            or settings.get("model", "")
        ).strip()
        if direct:
            return direct
        rows = settings.get("models")
        if isinstance(rows, list):
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                if entry.get("enabled") is not True:
                    continue
                model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
                if model_id:
                    return model_id
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
                if model_id:
                    return model_id
        return ""

    @staticmethod
    def preflight_settings_override(settings: dict[str, Any]) -> dict[str, Any] | None:
        override = dict(settings or {})
        raw_timeout = override.get("timeout_seconds")
        if raw_timeout is None:
            return None
        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError):
            timeout = 8
        timeout = max(2, min(timeout, 8))
        override["timeout_seconds"] = timeout
        return override
