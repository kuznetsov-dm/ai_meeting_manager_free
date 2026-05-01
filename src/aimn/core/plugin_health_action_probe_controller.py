from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PluginHealthActionProbeController:
    @staticmethod
    def settings_override_for_actions(
        *,
        settings: dict[str, Any],
        stage_model_path: str,
        stage_model_id: str,
        model_id: str,
        full_check: bool,
        preflight_settings_override: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        settings_for_actions = dict(settings or {})
        if stage_model_path:
            settings_for_actions["model_path"] = stage_model_path
            if not stage_model_id:
                settings_for_actions.pop("model_id", None)
        if stage_model_id:
            settings_for_actions["model_id"] = stage_model_id
        elif model_id and not str(settings_for_actions.get("model_id", "")).strip():
            settings_for_actions["model_id"] = model_id

        if full_check:
            return settings_for_actions

        quick_override = preflight_settings_override(settings_for_actions)
        if quick_override is not None:
            return quick_override
        if settings_for_actions != dict(settings or {}):
            return settings_for_actions
        return None

    @staticmethod
    def probe_sequence(
        *,
        action_ids: set[str],
        full_check: bool,
        model_id: str,
        ran_list_models: bool,
    ) -> list[tuple[str, dict[str, Any]]]:
        probes: list[tuple[str, dict[str, Any]]] = []
        if full_check and model_id and "test_model" in action_ids:
            probes.append(("test_model", {"model_id": model_id}))
            return probes

        for action_id in ("health_check", "health", "test_connection", "check_server"):
            if action_id in action_ids:
                probes.append((action_id, {}))
                break

        if full_check and "list_models" in action_ids and not ran_list_models and not probes:
            probes.append(("list_models", {}))
        return probes

    @staticmethod
    def unpack_action_result(result: object) -> tuple[str, str, object, list[str]]:
        if result is None:
            return "error", "empty_result", None, []
        if isinstance(result, dict):
            status = str(result.get("status", "") or "")
            message = str(result.get("message", "") or "")
            warnings: list[str] = []
            raw_warnings = result.get("warnings")
            if isinstance(raw_warnings, list):
                warnings.extend([str(item or "").strip() for item in raw_warnings if str(item or "").strip()])
            data = result.get("data")
            if isinstance(data, dict):
                data_warnings = data.get("warnings")
                if isinstance(data_warnings, list):
                    warnings.extend(
                        [str(item or "").strip() for item in data_warnings if str(item or "").strip()]
                    )
            return status, message, data, warnings

        status = str(getattr(result, "status", "") or "")
        message = str(getattr(result, "message", "") or "")
        data = getattr(result, "data", None)
        warnings = getattr(result, "warnings", [])
        normalized_warnings = (
            [str(item or "").strip() for item in warnings if str(item or "").strip()]
            if isinstance(warnings, list)
            else []
        )
        if isinstance(data, dict):
            data_warnings = data.get("warnings")
            if isinstance(data_warnings, list):
                normalized_warnings.extend(
                    [str(item or "").strip() for item in data_warnings if str(item or "").strip()]
                )
        return status, message, data, normalized_warnings
