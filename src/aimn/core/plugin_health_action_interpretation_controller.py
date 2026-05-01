from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PluginHealthActionInterpretationController:
    @staticmethod
    def issue_from_action_warnings(
        *,
        action_id: str,
        message: str,
        data: object,
        warnings: list[str],
        model_id: str,
        full_check: bool,
        normalize_code: Callable[[str, str], str],
        issue_factory: Callable[[str, str, str, str], object],
    ) -> object | None:
        if not full_check:
            return None
        aid = str(action_id or "").strip().lower()
        if aid not in {"test_model", "health_check", "health", "test_connection", "check_server"}:
            return None

        status_hint = str(message or "").strip().lower()
        warning_values = [str(item or "").strip() for item in (warnings or []) if str(item or "").strip()]
        warning_blob = " ".join(item.lower() for item in warning_values)
        detail_hint = ""
        if isinstance(data, dict):
            detail_hint = str(data.get("error", "") or data.get("detail", "") or "").strip()

        critical_markers = (
            "mock_fallback",
            "mock_output",
            "empty_response",
            "response_empty",
            "model_response_empty",
            "not_ready",
            "model_missing",
            "server_not_running",
            "connection_failed",
            "timeout",
            "failed",
            "error",
        )
        if not any(marker in warning_blob for marker in critical_markers) and status_hint not in {
            "model_available_no_output",
        }:
            return None

        detail = "; ".join(warning_values[:6]).strip()
        if detail_hint:
            detail = f"{detail}; {detail_hint}" if detail else detail_hint
        if not detail:
            detail = status_hint or "warning_reported"
        if model_id:
            detail = f"model_id='{model_id}'; {detail}"
        return issue_factory(
            normalize_code(aid, "check"),
            f"Health action '{action_id}' returned warnings.",
            detail,
            "Provider returned degraded/empty output. Check model/provider and retry.",
        )

    @staticmethod
    def issue_from_action_failure(
        *,
        plugin_id: str,
        action_id: str,
        message: str,
        data: object,
        model_id: str,
        plugin_capabilities: dict[str, Any] | None,
        normalize_code: Callable[[str, str], str],
        quick_fix_factory: Callable[[str, str, dict[str, Any]], object],
        issue_factory: Callable[[str, str, str, str, object | None], object],
    ) -> object:
        raw = str(message or "").strip()
        code = normalize_code(raw or action_id, f"action_{action_id}_failed")
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("error", "") or data.get("status", "") or "").strip()
        hint = "Check plugin settings and retry."
        quick_fix = None

        lowered = raw.lower()
        if "api_key" in lowered or lowered.endswith("key_missing") or "api key" in lowered:
            hint = "Add API key in Settings and rerun health check."
        elif raw in {"server_not_running", "connection_failed"} or "connection refused" in lowered:
            hint = "Start local server or fix endpoint URL."
            start_action = str(
                PluginHealthActionInterpretationController._cap_get(
                    plugin_capabilities,
                    "health",
                    "server",
                    "auto_start_action",
                    default="",
                )
                or ""
            ).strip()
            if start_action:
                quick_fix = quick_fix_factory(
                    start_action,
                    "Start server",
                    {"timeout_seconds": 12},
                )
        elif raw in {"model_not_found", "model_id_missing"}:
            hint = "Select/download a model in Settings."
        elif "timeout" in lowered:
            hint = "Increase timeout or verify network/server responsiveness."
        elif (
            "unknown model" in lowered
            or "not a valid model id" in lowered
            or "\"code\":\"1211\"" in lowered
            or "no endpoints found" in lowered
        ):
            hint = "Selected model is unavailable. Pick another model ID in Settings."
        elif "insufficient balance" in lowered or "\"code\":\"1113\"" in lowered:
            hint = "Provider account has insufficient balance/package for this model."
        elif "status=429" in lowered or "rate limit" in lowered:
            hint = "Provider rate limit reached. Retry later or switch model/provider."
        elif raw == "action_not_found":
            hint = "Plugin does not expose this health action. Update plugin implementation."

        summary = f"Health action '{action_id}' failed"
        if raw:
            summary = f"{summary}: {raw}"
        if model_id and raw in {"model_not_found", "model_id_missing"}:
            detail = f"model_id='{model_id}'"
        return issue_factory(code, summary, detail, hint, quick_fix)

    @staticmethod
    def extract_models(data: object) -> list[str]:
        if not isinstance(data, dict):
            return []
        raw_models = data.get("models")
        if not isinstance(raw_models, list):
            return []
        values: list[str] = []
        for entry in raw_models:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if model_id:
                values.append(model_id)
        return values

    @staticmethod
    def extract_installed_models(data: object) -> list[str]:
        if not isinstance(data, dict):
            return []
        raw_models = data.get("models")
        if not isinstance(raw_models, list):
            return []
        values: list[str] = []
        for entry in raw_models:
            if not isinstance(entry, dict):
                continue
            installed = entry.get("installed")
            if installed is None:
                status = str(entry.get("status", "") or "").strip().lower()
                installed = status in {"installed", "enabled", "ready"}
            if not bool(installed):
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if model_id:
                values.append(model_id)
        return values

    @staticmethod
    def _cap_get(payload: object, *keys: str, default: object = None) -> object:
        current = payload
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(str(key))
        return current if current is not None else default
