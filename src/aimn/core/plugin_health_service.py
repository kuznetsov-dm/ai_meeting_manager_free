from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from aimn.core.plugin_action_service import PluginActionService
from aimn.core.plugin_catalog_service import PluginCatalogService
from aimn.core.plugin_health_action_check_controller import PluginHealthActionCheckController
from aimn.core.plugin_health_action_interpretation_controller import (
    PluginHealthActionInterpretationController,
)
from aimn.core.plugin_health_action_probe_controller import PluginHealthActionProbeController
from aimn.core.plugin_health_local_prereq_controller import PluginHealthLocalPrereqController
from aimn.core.plugin_health_model_policy_controller import PluginHealthModelPolicyController
from aimn.core.plugin_health_settings_controller import PluginHealthSettingsController
from aimn.core.settings_services import SettingsService

_EXPECTED_HEALTH_RUNTIME_ERRORS = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _looks_like_secret_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if not lowered:
        return False
    if lowered in {
        "key",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
    }:
        return True
    if lowered.startswith("api_key_") or lowered.endswith("_api_key") or lowered.endswith("apikey"):
        return True
    if lowered.endswith("_token") or lowered.endswith("_secret") or lowered.endswith("_password"):
        return True
    if lowered.endswith("_key") or lowered.endswith("_keys") or lowered.endswith("_password"):
        return True
    if lowered.startswith("key_"):
        return True
    return False


def _is_success_status(value: str) -> bool:
    return str(value or "").strip().lower() in {"ok", "success", "passed", "healthy"}


def _normalize_code(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or fallback


def _cap_get(payload: object, *keys: str, default: object = None) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(str(key))
    return current if current is not None else default


@dataclass(frozen=True)
class PluginHealthQuickFix:
    action_id: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginHealthIssue:
    code: str
    severity: str
    summary: str
    detail: str = ""
    hint: str = ""
    quick_fix: PluginHealthQuickFix | None = None


@dataclass(frozen=True)
class PluginHealthReport:
    plugin_id: str
    stage_id: str
    healthy: bool
    checked_at: float
    cached: bool
    checks: tuple[str, ...] = ()
    issues: tuple[PluginHealthIssue, ...] = ()


class PluginHealthService:
    _cache: dict[str, tuple[float, PluginHealthReport]] = {}

    def __init__(
        self,
        app_root: Path,
        *,
        catalog_service: PluginCatalogService | None = None,
        action_service: PluginActionService | None = None,
        settings_service: SettingsService | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._app_root = Path(app_root)
        self._catalog_service = catalog_service or PluginCatalogService(self._app_root)
        self._action_service = action_service or PluginActionService(
            self._app_root, catalog_service=self._catalog_service
        )
        settings_dir = self._app_root / "config" / "settings"
        self._settings_service = settings_service or SettingsService(settings_dir, repo_root=self._app_root)
        self._clock = clock or time.monotonic
        self._logger = logging.getLogger("aimn.health")

    def check_plugin(
        self,
        plugin_id: str,
        *,
        stage_id: str = "",
        stage_params: dict[str, Any] | None = None,
        settings_override: dict[str, Any] | None = None,
        full_check: bool = False,
        force: bool = False,
        max_age_seconds: float = 180.0,
        allow_disabled: bool = False,
        allow_stale_on_error: bool = True,
    ) -> PluginHealthReport:
        pid = str(plugin_id or "").strip()
        stage = str(stage_id or "").strip()
        params = dict(stage_params or {})
        now = self._clock()
        settings = self._settings_service.get_settings(pid, include_secrets=True) if pid else {}
        if pid:
            settings = self._settings_with_defaults(pid, settings)
            if isinstance(settings_override, dict) and settings_override:
                settings.update(dict(settings_override))

        snapshot = self._catalog_service.load()
        cache_key = self._cache_key(snapshot.stamp, pid, stage, settings, params, full_check, allow_disabled)
        cached = self._cache.get(cache_key)
        if not force and cached and now <= cached[0]:
            return replace(cached[1], cached=True)

        stale_report = cached[1] if cached else None
        checks: list[str] = []
        issues: list[PluginHealthIssue] = []

        plugin = snapshot.catalog.plugin_by_id(pid) if pid else None
        if not pid:
            issues.append(
                PluginHealthIssue(
                    code="plugin_id_missing",
                    severity="error",
                    summary="Plugin is not selected.",
                    hint="Choose a provider before running this stage.",
                )
            )
        elif not plugin:
            issues.append(
                PluginHealthIssue(
                    code="plugin_not_found",
                    severity="error",
                    summary=f"Plugin '{pid}' is not available.",
                    hint="Reload plugins or reinstall the missing plugin.",
                )
            )
        else:
            if not plugin.installed:
                issues.append(
                    PluginHealthIssue(
                        code="plugin_not_installed",
                        severity="error",
                        summary=f"Plugin '{pid}' is not installed.",
                        hint="Install the plugin in the Plugins tab.",
                    )
                )
            elif not plugin.enabled and not allow_disabled:
                issues.append(
                    PluginHealthIssue(
                        code="plugin_disabled",
                        severity="error",
                        summary=f"Plugin '{pid}' is disabled.",
                        hint="Enable the plugin in Plugins settings.",
                    )
                )

        if not any(issue.severity == "error" for issue in issues):
            try:
                checks.extend(self._run_required_settings_checks(pid, settings, params, issues))
                checks.extend(self._run_local_prereq_checks(pid, settings, params, issues))
                checks.extend(self._run_action_checks(pid, settings, params, full_check, issues))
            except _EXPECTED_HEALTH_RUNTIME_ERRORS as exc:
                self._logger.warning(
                    "plugin_health_exception plugin_id=%s stage_id=%s error=%s",
                    pid,
                    stage,
                    exc,
                )
                if allow_stale_on_error and stale_report is not None:
                    return replace(stale_report, cached=True)
                issues.append(
                    PluginHealthIssue(
                        code="health_check_exception",
                        severity="error",
                        summary="Health check crashed.",
                        detail=str(exc),
                        hint="Retry health check or inspect plugin/action logs.",
                    )
                )

        if issues:
            issues = self._dedupe_issues(issues)
        healthy = not any(issue.severity == "error" for issue in issues)
        report = PluginHealthReport(
            plugin_id=pid,
            stage_id=stage,
            healthy=healthy,
            checked_at=now,
            cached=False,
            checks=tuple(checks),
            issues=tuple(issues),
        )
        expiry = now + max(0.0, float(max_age_seconds or 0.0))
        self._cache[cache_key] = (expiry, report)
        self._logger.info(
            "plugin_health_result plugin_id=%s stage_id=%s healthy=%s checks=%s issues=%s cached=%s",
            pid,
            stage,
            report.healthy,
            ",".join(report.checks),
            ",".join(issue.code for issue in report.issues),
            report.cached,
        )
        return report

    def invoke_quick_fix(
        self, plugin_id: str, fix: PluginHealthQuickFix
    ) -> tuple[bool, str]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return False, "plugin_id_missing"
        if not fix or not str(fix.action_id or "").strip():
            return False, "quick_fix_missing"
        try:
            result = self._action_service.invoke_action(
                pid, str(fix.action_id), dict(fix.payload or {})
            )
        except _EXPECTED_HEALTH_RUNTIME_ERRORS as exc:
            self._logger.warning(
                "plugin_health_quick_fix_failed plugin_id=%s action_id=%s error=%s",
                pid,
                fix.action_id,
                exc,
            )
            return False, str(exc)
        status, message, _data, _warnings = PluginHealthActionProbeController.unpack_action_result(result)
        self.invalidate_plugin_cache(pid)
        return _is_success_status(status), (message or status or "unknown")

    def invalidate_plugin_cache(self, plugin_id: str = "") -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            self._cache.clear()
            return
        for key in list(self._cache.keys()):
            if key.startswith(f"{pid}|") or f"|{pid}|" in key:
                self._cache.pop(key, None)

    def _cache_key(
        self,
        stamp: str,
        plugin_id: str,
        stage_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        full_check: bool,
        allow_disabled: bool,
    ) -> str:
        payload = {
            "stamp": str(stamp or ""),
            "plugin_id": str(plugin_id or ""),
            "stage_id": str(stage_id or ""),
            "settings": settings,
            "stage_params": stage_params,
            "full_check": bool(full_check),
            "allow_disabled": bool(allow_disabled),
        }
        blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
        return f"{plugin_id}|{stage_id}|{digest}"

    def _plugin_capabilities(self, plugin_id: str) -> dict[str, Any]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return {}
        try:
            plugin = self._catalog_service.load().catalog.plugin_by_id(pid)
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            self._logger.warning("plugin_health_catalog_load_failed plugin_id=%s error=%s", pid, exc)
            return {}
        caps = getattr(plugin, "capabilities", None) if plugin else None
        return dict(caps) if isinstance(caps, dict) else {}

    def _provider_label(self, plugin_id: str) -> str:
        pid = str(plugin_id or "").strip()
        if not pid:
            return ""
        try:
            plugin = self._catalog_service.load().catalog.plugin_by_id(pid)
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            self._logger.warning("plugin_health_provider_label_failed plugin_id=%s error=%s", pid, exc)
            return ""
        if not plugin:
            return ""
        provider = str(getattr(plugin, "provider_name", "") or "").strip()
        if provider:
            return provider
        name = str(getattr(plugin, "name", "") or "").strip()
        return name

    def _run_required_settings_checks(
        self,
        plugin_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        issues: list[PluginHealthIssue],
    ) -> list[str]:
        checks, new_issues = PluginHealthSettingsController.run_required_settings_checks(
            stage_params=stage_params,
            settings=settings,
            groups=self._required_setting_groups(plugin_id, settings),
            value_resolver=self._value,
            issue_factory=lambda code, summary, hint: PluginHealthIssue(
                code=code,
                severity="error",
                summary=summary,
                hint=hint,
            ),
            normalize_code=lambda label, fallback: _normalize_code(label, fallback=fallback),
        )
        for issue in new_issues:
            if isinstance(issue, PluginHealthIssue):
                issues.append(issue)
        return checks

    def _run_local_prereq_checks(
        self,
        plugin_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        issues: list[PluginHealthIssue],
    ) -> list[str]:
        checks, new_issues = PluginHealthLocalPrereqController.run_local_prereq_checks(
            plugin_id,
            settings,
            stage_params,
            capabilities=self._plugin_capabilities(plugin_id),
            value_resolver=self._value,
            coerce_bool=self._coerce_bool,
            resolve_existing_path=lambda raw, env_key, executable: self._resolve_existing_path(
                raw,
                env_key=env_key,
                executable=executable,
            ),
            resolve_existing_dir=lambda raw, env_key: self._resolve_existing_dir(raw, env_key=env_key),
            local_model_present=lambda cache_dir, globs: self._local_model_present(cache_dir, globs=globs),
            issue_factory=lambda code, summary, detail, hint: PluginHealthIssue(
                code=code,
                severity="error",
                summary=summary,
                detail=detail,
                hint=hint,
            ),
        )
        for issue in new_issues:
            if isinstance(issue, PluginHealthIssue):
                issues.append(issue)
        return checks

    def _check_local_binary_prerequisites(
        self,
        plugin_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        issues: list[PluginHealthIssue],
    ) -> bool:
        new_issues: list[PluginHealthIssue] = []
        ran = PluginHealthLocalPrereqController.check_local_binary_prerequisites(
            settings,
            stage_params,
            capabilities=self._plugin_capabilities(plugin_id),
            value_resolver=self._value,
            coerce_bool=self._coerce_bool,
            resolve_existing_path=lambda raw, env_key, executable: self._resolve_existing_path(
                raw,
                env_key=env_key,
                executable=executable,
            ),
            issue_factory=lambda code, summary, detail, hint: PluginHealthIssue(
                code=code,
                severity="error",
                summary=summary,
                detail=detail,
                hint=hint,
            ),
            issues=new_issues,
        )
        issues.extend(new_issues)
        return ran

    def _local_model_cache_spec(self, plugin_id: str) -> dict[str, Any]:
        return PluginHealthLocalPrereqController.local_model_cache_spec(self._plugin_capabilities(plugin_id))

    def _check_local_model_cache_prerequisites(
        self,
        plugin_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        issues: list[PluginHealthIssue],
    ) -> bool:
        new_issues: list[PluginHealthIssue] = []
        ran = PluginHealthLocalPrereqController.check_local_model_cache_prerequisites(
            settings,
            stage_params,
            capabilities=self._plugin_capabilities(plugin_id),
            value_resolver=self._value,
            coerce_bool=self._coerce_bool,
            resolve_existing_path=lambda raw, env_key, executable: self._resolve_existing_path(
                raw,
                env_key=env_key,
                executable=executable,
            ),
            resolve_existing_dir=lambda raw, env_key: self._resolve_existing_dir(raw, env_key=env_key),
            local_model_present=lambda cache_dir, globs: self._local_model_present(cache_dir, globs=globs),
            issue_factory=lambda code, summary, detail, hint: PluginHealthIssue(
                code=code,
                severity="error",
                summary=summary,
                detail=detail,
                hint=hint,
            ),
            issues=new_issues,
        )
        issues.extend(new_issues)
        return ran

    def _run_action_checks(
        self,
        plugin_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        full_check: bool,
        issues: list[PluginHealthIssue],
    ) -> list[str]:
        checks, new_issues = PluginHealthActionCheckController.run_action_checks(
            plugin_id=plugin_id,
            settings=settings,
            stage_params=stage_params,
            full_check=full_check,
            action_ids=self._available_action_ids(plugin_id),
            plugin_capabilities=self._plugin_capabilities(plugin_id),
            coerce_bool=self._coerce_bool,
            cap_get=_cap_get,
            resolve_model_id=PluginHealthModelPolicyController.resolve_model_id,
            settings_override_for_actions=PluginHealthActionProbeController.settings_override_for_actions,
            preflight_settings_override=PluginHealthModelPolicyController.preflight_settings_override,
            models_storage_is_local=PluginHealthModelPolicyController.models_storage_is_local,
            probe_sequence=PluginHealthActionProbeController.probe_sequence,
            invoke_action=lambda pid, action_id, payload, settings_override: self._action_service.invoke_action(
                pid,
                action_id,
                payload,
                settings_override=settings_override,
            ),
            unpack_action_result=PluginHealthActionProbeController.unpack_action_result,
            is_success_status=_is_success_status,
            extract_installed_models=self._extract_installed_models,
            extract_models=self._extract_models,
            issue_from_action_failure=lambda action_id, message, data, model_id: self._issue_from_action_failure(
                plugin_id,
                action_id,
                message,
                data,
                model_id,
            ),
            issue_from_action_warnings=self._issue_from_action_warnings,
        )
        for issue in new_issues:
            if isinstance(issue, PluginHealthIssue):
                issues.append(issue)
        return checks

    def _issue_from_action_warnings(
        self,
        *,
        action_id: str,
        message: str,
        data: object,
        warnings: list[str],
        model_id: str,
        full_check: bool,
    ) -> PluginHealthIssue | None:
        issue = PluginHealthActionInterpretationController.issue_from_action_warnings(
            action_id=action_id,
            message=message,
            data=data,
            warnings=warnings,
            model_id=model_id,
            full_check=full_check,
            normalize_code=lambda value, fallback: f"action_{_normalize_code(value, fallback=fallback)}_warning",
            issue_factory=lambda code, summary, detail, hint: PluginHealthIssue(
                code=code,
                severity="error",
                summary=summary,
                detail=detail,
                hint=hint,
            ),
        )
        return issue if isinstance(issue, PluginHealthIssue) else None

    def _available_action_ids(self, plugin_id: str) -> set[str]:
        try:
            actions = self._action_service.list_actions(plugin_id)
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            self._logger.warning("plugin_health_list_actions_failed plugin_id=%s error=%s", plugin_id, exc)
            return set()
        ids: set[str] = set()
        for item in actions:
            action_id = str(getattr(item, "action_id", "") or "").strip()
            if action_id:
                ids.add(action_id)
        return ids

    def _issue_from_action_failure(
        self,
        plugin_id: str,
        action_id: str,
        message: str,
        data: object,
        model_id: str,
    ) -> PluginHealthIssue:
        issue = PluginHealthActionInterpretationController.issue_from_action_failure(
            plugin_id=plugin_id,
            action_id=action_id,
            message=message,
            data=data,
            model_id=model_id,
            plugin_capabilities=self._plugin_capabilities(plugin_id),
            normalize_code=lambda value, fallback: _normalize_code(value, fallback=fallback),
            quick_fix_factory=lambda action_id, label, payload: PluginHealthQuickFix(
                action_id=action_id,
                label=label,
                payload=payload,
            ),
            issue_factory=lambda code, summary, detail, hint, quick_fix: PluginHealthIssue(
                code=code,
                severity="error",
                summary=summary,
                detail=detail,
                hint=hint,
                quick_fix=quick_fix if isinstance(quick_fix, PluginHealthQuickFix) else None,
            ),
        )
        return issue if isinstance(issue, PluginHealthIssue) else PluginHealthIssue(
            code=f"action_{action_id}_failed",
            severity="error",
            summary=f"Health action '{action_id}' failed.",
        )

    @staticmethod
    def _extract_models(data: object) -> list[str]:
        return PluginHealthActionInterpretationController.extract_models(data)

    @staticmethod
    def _extract_installed_models(data: object) -> list[str]:
        return PluginHealthActionInterpretationController.extract_installed_models(data)

    def _required_setting_groups(
        self, plugin_id: str, settings: dict[str, Any]
    ) -> list[tuple[str, list[str]]]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return []
        schema = self._catalog_service.load().catalog.schema_for(pid)
        return PluginHealthSettingsController.required_setting_groups(
            pid,
            settings,
            capabilities=self._plugin_capabilities(pid),
            schema=schema,
            looks_like_secret_key=_looks_like_secret_key,
        )

    def _settings_with_defaults(self, plugin_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        try:
            schema = self._catalog_service.load().catalog.schema_for(plugin_id)
        except (AttributeError, OSError, RuntimeError, ValueError) as exc:
            self._logger.warning("plugin_health_schema_load_failed plugin_id=%s error=%s", plugin_id, exc)
            schema = None
        if schema:
            for item in schema.settings:
                key = str(item.key or "").strip()
                if not key:
                    continue
                merged[key] = self._coerce_setting_value(item.value)
        merged.update(dict(settings or {}))
        return merged

    @staticmethod
    def _value(
        stage_params: dict[str, Any], settings: dict[str, Any], key: str
    ) -> object:
        value = stage_params.get(key, None)
        if value is None or str(value).strip() == "":
            value = settings.get(key, None)
        return value

    def _resolve_existing_path(self, raw: str, *, env_key: str, executable: bool) -> str:
        candidate = str(raw or "").strip()
        env_val = str(os.getenv(env_key, "") or "").strip() if env_key else ""
        if env_val:
            candidate = env_val
        if not candidate:
            return ""
        path = Path(candidate)
        probes: list[Path] = []
        if path.is_absolute():
            probes.append(path)
        else:
            probes.append((self._app_root / path).resolve())
            probes.append(path)
        if executable and path.suffix == "":
            for probe in list(probes):
                probes.append(probe.with_suffix(".exe"))
        for probe in probes:
            if probe.exists() and probe.is_file():
                return str(probe)
        if executable:
            found = shutil.which(candidate) or shutil.which(Path(candidate).name)
            if found:
                return str(Path(found))
        return ""

    def _resolve_existing_dir(self, raw: str, *, env_key: str) -> str:
        candidate = str(raw or "").strip()
        env_val = str(os.getenv(env_key, "") or "").strip() if env_key else ""
        if env_val:
            candidate = env_val
        if not candidate:
            return ""
        path = Path(candidate)
        probes: list[Path] = []
        if path.is_absolute():
            probes.append(path)
        else:
            probes.append((self._app_root / path).resolve())
            probes.append(path)
        for probe in probes:
            if probe.exists() and probe.is_dir():
                return str(probe)
        return ""

    @staticmethod
    def _coerce_setting_value(value: object) -> object:
        if isinstance(value, (bool, int, float)):
            return value
        text = str(value or "").strip()
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            if "." in text:
                return float(text)
            return int(text)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _coerce_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "on"}

    @staticmethod
    def _local_model_present(cache_dir: str, *, globs: list[str]) -> bool:
        root = Path(str(cache_dir or "").strip())
        if not root.exists() or not root.is_dir():
            return False
        for pattern in globs or []:
            clean_pattern = str(pattern or "").strip()
            if not clean_pattern:
                continue
            for entry in root.glob(clean_pattern):
                if entry.exists() and entry.is_file():
                    return True
        return False

    @staticmethod
    def _dedupe_issues(issues: list[PluginHealthIssue]) -> list[PluginHealthIssue]:
        deduped: list[PluginHealthIssue] = []
        seen: set[tuple[str, str, str]] = set()
        for issue in issues:
            key = (issue.code, issue.severity, issue.summary)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(issue)
        return deduped
