from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PluginHealthActionCheckController:
    @staticmethod
    def run_action_checks(
        *,
        plugin_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        full_check: bool,
        action_ids: set[str],
        plugin_capabilities: dict[str, Any] | None,
        coerce_bool: Callable[[object], bool],
        cap_get: Callable[..., object],
        resolve_model_id: Callable[[dict[str, Any], dict[str, Any]], str],
        settings_override_for_actions: Callable[..., dict[str, Any] | None],
        preflight_settings_override: Callable[[dict[str, Any]], dict[str, Any] | None],
        models_storage_is_local: Callable[[dict[str, Any] | None], bool],
        probe_sequence: Callable[..., list[tuple[str, dict[str, Any]]]],
        invoke_action: Callable[[str, str, dict[str, Any], dict[str, Any] | None], object],
        unpack_action_result: Callable[[object], tuple[str, str, object, list[str]]],
        is_success_status: Callable[[str], bool],
        extract_installed_models: Callable[[object], list[str]],
        extract_models: Callable[[object], list[str]],
        issue_from_action_failure: Callable[[str, str, object, str], object],
        issue_from_action_warnings: Callable[..., object | None],
    ) -> tuple[list[str], list[object]]:
        checks: list[str] = []
        issues: list[object] = []
        if not action_ids:
            return checks, issues

        stage_model_path = str(stage_params.get("model_path", "") or "").strip()
        stage_model_id = str(stage_params.get("model_id", "") or stage_params.get("model", "") or "").strip()
        explicit_model_path = bool(stage_model_path and not stage_model_id)
        model_id = "" if explicit_model_path else (stage_model_id or resolve_model_id(stage_params, settings))
        ran_list_models = False

        settings_override = settings_override_for_actions(
            settings=settings,
            stage_model_path=stage_model_path,
            stage_model_id=stage_model_id,
            model_id=model_id,
            full_check=full_check,
            preflight_settings_override=preflight_settings_override,
        )

        require_installed_list = bool(
            coerce_bool(cap_get(plugin_capabilities, "health", "models", "require_installed_list", default=False))
        )
        local_model_storage = models_storage_is_local(plugin_capabilities)
        must_validate_installed_models = require_installed_list or local_model_storage

        if full_check and must_validate_installed_models and "list_models" in action_ids:
            ran_list_models = True
            checks.append("action:list_models")
            try:
                list_result = invoke_action(plugin_id, "list_models", {}, settings_override)
            except Exception as exc:
                issues.append(
                    issue_from_action_failure(
                        "list_models",
                        "Health action 'list_models' failed.",
                        {"error": str(exc), "status": "exception"},
                        model_id,
                    )
                )
                return checks, issues

            status, message, data, _warnings = unpack_action_result(list_result)
            if not is_success_status(status):
                issues.append(issue_from_action_failure("list_models", message, data, model_id))
                return checks, issues

            installed_models = extract_installed_models(data)
            if model_id and model_id not in installed_models and installed_models:
                issues.append(
                    issue_from_action_failure(
                        "list_models",
                        "model_not_found",
                        {"error": f"installed={','.join(installed_models[:8])}"},
                        model_id,
                    )
                )
                return checks, issues
            if not model_id and installed_models and not explicit_model_path:
                model_id = installed_models[0]
            if not installed_models and must_validate_installed_models and not explicit_model_path:
                issues.append(issue_from_action_failure("list_models", "model_not_found", {}, model_id))
                return checks, issues

        probes = probe_sequence(
            action_ids=action_ids,
            full_check=full_check,
            model_id=model_id,
            ran_list_models=ran_list_models,
        )
        for action_id, payload in probes:
            checks.append(f"action:{action_id}")
            try:
                result = invoke_action(plugin_id, action_id, payload, settings_override)
            except Exception as exc:
                issues.append(
                    issue_from_action_failure(
                        action_id,
                        f"Health action '{action_id}' failed.",
                        {"error": str(exc), "status": "exception"},
                        model_id,
                    )
                )
                return checks, issues

            status, message, data, warnings = unpack_action_result(result)
            if is_success_status(status):
                warning_issue = issue_from_action_warnings(
                    action_id=action_id,
                    message=message,
                    data=data,
                    warnings=warnings,
                    model_id=model_id,
                    full_check=full_check,
                )
                if warning_issue is not None:
                    issues.append(warning_issue)
                    return checks, issues
                if action_id == "list_models" and full_check and model_id:
                    models = extract_models(data)
                    if models and model_id not in set(models):
                        issues.append(issue_from_action_failure(action_id, "model_not_found", {}, model_id))
                        return checks, issues
                continue

            issues.append(issue_from_action_failure(action_id, message, data, model_id))
            return checks, issues

        return checks, issues
