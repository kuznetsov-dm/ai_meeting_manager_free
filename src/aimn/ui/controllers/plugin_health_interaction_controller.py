from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QMessageBox, QWidget

from aimn.core.api import PluginHealthQuickFix, PluginHealthReport


def _cap_get(payload: object, *keys: str, default: object = None) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(str(key))
    return current if current is not None else default


class PluginHealthInteractionController:
    _WAIT_POLL_SECONDS = 0.05
    _PROGRESS_PULSE_SECONDS = 0.25

    def __init__(
        self,
        *,
        parent: QWidget | None,
        stage_order: list[str],
        stage_display_name: Callable[[str], str],
        plugin_display_name: Callable[[str], str],
        plugin_available: Callable[[str], bool] | None = None,
        plugin_capabilities: Callable[[str], dict],
        health_service,
        log_message: Callable[[str, str], None],
        open_stage_settings: Callable[[str], None],
        apply_skip_once: Callable[[dict[str, object], dict], None],
        apply_disable_preset: Callable[[dict], None],
        offline_mode: Callable[[], bool],
        report_progress: Callable[[dict[str, object]], None] | None = None,
        tr: Callable[[str, str], str] | None = None,
        fmt: Callable[..., str] | None = None,
    ) -> None:
        self._parent = parent
        self._stage_order = list(stage_order)
        self._stage_display_name = stage_display_name
        self._plugin_display_name = plugin_display_name
        self._plugin_available = plugin_available or (lambda plugin_id: bool(str(plugin_id or "").strip()))
        self._plugin_capabilities = plugin_capabilities
        self._health_service = health_service
        self._log_message = log_message
        self._open_stage_settings = open_stage_settings
        self._apply_skip_once = apply_skip_once
        self._apply_disable_preset = apply_disable_preset
        self._offline_mode = offline_mode
        self._report_progress_cb = report_progress
        self._tr = tr or (lambda _k, default: str(default or ""))
        if fmt is not None:
            self._fmt = fmt
        else:
            def _default_fmt(_k: str, default: str, **kwargs: object) -> str:
                template = str(default or "")
                try:
                    return template.format(**kwargs)
                except Exception:
                    return template

            self._fmt = _default_fmt

    def preflight_plugin_health_checks(
        self,
        runtime_config: dict[str, object],
        *,
        force_run_from: str | None = None,
    ) -> tuple[bool, dict[str, object]]:
        checks = self.health_checks_for_runtime(runtime_config, force_run_from=force_run_from)
        if not checks:
            return True, runtime_config

        updated_runtime = runtime_config
        total = int(len(checks))
        completed = 0
        self._report_progress(
            {
                "state": "running",
                "current": completed,
                "total": total,
                "stage_id": "",
                "plugin_id": "",
            }
        )
        for check in checks:
            stage_id = str(check.get("stage_id", "") or "").strip()
            plugin_id = str(check.get("plugin_id", "") or "").strip()
            if not stage_id or not plugin_id:
                continue
            if not self._check_still_present(updated_runtime, check):
                completed += 1
                self._report_progress(
                    {
                        "state": "running",
                        "current": completed,
                        "total": total,
                        "stage_id": stage_id,
                        "plugin_id": plugin_id,
                    }
                )
                continue
            self._report_progress(
                {
                    "state": "running",
                    "current": completed,
                    "total": total,
                    "stage_id": stage_id,
                    "plugin_id": plugin_id,
                }
            )
            params = check.get("params")
            report = self._check_plugin_with_progress(
                plugin_id=plugin_id,
                stage_id=stage_id,
                stage_params=params if isinstance(params, dict) else {},
                full_check=True,
                force=True,
                max_age_seconds=30.0,
                allow_disabled=bool(self._offline_mode()),
                allow_stale_on_error=False,
                progress_payload={
                    "state": "running",
                    "current": completed,
                    "total": total,
                    "stage_id": stage_id,
                    "plugin_id": plugin_id,
                },
            )
            report = self.attempt_automatic_preflight_fix(
                stage_id=stage_id,
                plugin_id=plugin_id,
                report=report,
                check=check,
            )
            completed += 1
            self._report_progress(
                {
                    "state": "running",
                    "current": completed,
                    "total": total,
                    "stage_id": stage_id,
                    "plugin_id": plugin_id,
                }
            )
            blocking = [issue for issue in report.issues if issue.severity == "error"]
            if not blocking:
                continue
            decision = self.prompt_health_decision(stage_id, plugin_id, report, check)
            if decision == "continue":
                continue
            if decision == "cancel":
                self._report_progress(
                    {
                        "state": "finished",
                        "result": "cancelled",
                        "current": completed,
                        "total": total,
                    }
                )
                return False, updated_runtime
            if decision == "fix_now":
                self._open_stage_settings(stage_id)
                self._report_progress(
                    {
                        "state": "finished",
                        "result": "fix_now",
                        "current": completed,
                        "total": total,
                    }
                )
                return False, updated_runtime
            if decision == "skip_once":
                self._apply_skip_once(updated_runtime, check)
                continue
            if decision == "disable_preset":
                self._apply_disable_preset(check)
                self._apply_skip_once(updated_runtime, check)
                continue
            self._report_progress(
                {
                    "state": "finished",
                    "result": "cancelled",
                    "current": completed,
                    "total": total,
                }
            )
            return False, updated_runtime
        self._report_progress(
            {
                "state": "finished",
                "result": "ok",
                "current": completed,
                "total": total,
            }
        )
        return True, updated_runtime

    def _report_progress(self, payload: dict[str, object]) -> None:
        cb = self._report_progress_cb
        if cb is None:
            return
        try:
            cb(dict(payload or {}))
        except Exception:
            return

    @staticmethod
    def _check_still_present(runtime_config: dict[str, object], check: dict) -> bool:
        stage_id = str(check.get("stage_id", "") or "").strip()
        plugin_id = str(check.get("plugin_id", "") or "").strip()
        if not stage_id or not plugin_id:
            return False
        stages = runtime_config.get("stages")
        if not isinstance(stages, dict):
            return False
        stage = stages.get(stage_id)
        if not isinstance(stage, dict):
            return False

        expected_params = check.get("params")
        normalized_expected = dict(expected_params) if isinstance(expected_params, dict) else {}

        variants = stage.get("variants")
        if isinstance(variants, list):
            variant_index = check.get("variant_index")
            if variant_index is not None:
                try:
                    idx = int(variant_index)
                except Exception:
                    idx = -1
                if 0 <= idx < len(variants):
                    entry = variants[idx]
                    if isinstance(entry, dict):
                        entry_pid = str(entry.get("plugin_id", "") or "").strip()
                        entry_params = entry.get("params")
                        normalized_entry = dict(entry_params) if isinstance(entry_params, dict) else {}
                        if entry_pid == plugin_id and (
                            not normalized_expected or normalized_entry == normalized_expected
                        ):
                            return True
            for entry in variants:
                if not isinstance(entry, dict):
                    continue
                entry_pid = str(entry.get("plugin_id", "") or "").strip()
                if entry_pid != plugin_id:
                    continue
                entry_params = entry.get("params")
                normalized_entry = dict(entry_params) if isinstance(entry_params, dict) else {}
                if not normalized_expected or normalized_entry == normalized_expected:
                    return True
            return False

        stage_plugin_id = str(stage.get("plugin_id", "") or "").strip()
        return stage_plugin_id == plugin_id

    def health_checks_for_runtime(
        self,
        runtime_config: dict[str, object],
        *,
        force_run_from: str | None = None,
    ) -> list[dict]:
        stages = runtime_config.get("stages")
        if not isinstance(stages, dict):
            return []
        pipeline = runtime_config.get("pipeline")
        disabled = set()
        if isinstance(pipeline, dict):
            raw_disabled = pipeline.get("disabled_stages")
            if isinstance(raw_disabled, list):
                disabled = {str(item or "").strip() for item in raw_disabled if str(item or "").strip()}
        stage_order = list(self._stage_order)
        start_stage = str(force_run_from or "").strip()
        start_index = stage_order.index(start_stage) if start_stage in stage_order else 0

        checks: list[dict] = []
        for index, stage_id in enumerate(stage_order):
            if index < start_index:
                continue
            if stage_id in disabled:
                continue
            stage_config = stages.get(stage_id)
            if not isinstance(stage_config, dict):
                continue
            variants = stage_config.get("variants")
            if isinstance(variants, list) and variants:
                for variant_index, entry in enumerate(variants):
                    if not isinstance(entry, dict):
                        continue
                    plugin_id = str(entry.get("plugin_id", "") or "").strip()
                    params = entry.get("params")
                    if not plugin_id:
                        continue
                    if not bool(self._plugin_available(plugin_id)):
                        continue
                    checks.append(
                        {
                            "stage_id": stage_id,
                            "plugin_id": plugin_id,
                            "params": params if isinstance(params, dict) else {},
                            "variant_index": variant_index,
                        }
                    )
                continue
            plugin_id = str(stage_config.get("plugin_id", "") or "").strip()
            if not plugin_id:
                continue
            if not bool(self._plugin_available(plugin_id)):
                continue
            params = stage_config.get("params")
            checks.append(
                {
                    "stage_id": stage_id,
                    "plugin_id": plugin_id,
                    "params": params if isinstance(params, dict) else {},
                    "variant_index": None,
                }
            )
        return checks

    def prompt_health_decision(
        self,
        stage_id: str,
        plugin_id: str,
        report: PluginHealthReport,
        check: dict,
    ) -> str:
        stage_label = self._stage_display_name(stage_id)
        plugin_label = self._plugin_display_name(plugin_id)
        details = self.health_issues_text(report.issues)
        while True:
            box = QMessageBox(self._parent)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(self._tr("health.preflight_title", "Plugin Health Check"))
            box.setText(
                self._fmt(
                    "health.preflight_not_ready",
                    "{stage_label}: {plugin_label} is not ready.",
                    stage_label=stage_label,
                    plugin_label=plugin_label,
                )
            )
            box.setInformativeText(details)
            quick_fix = next((issue.quick_fix for issue in report.issues if issue.quick_fix), None)
            quick_btn = None
            if quick_fix:
                quick_btn = box.addButton(str(quick_fix.label), QMessageBox.ActionRole)
            skip_label = (
                self._tr("health.skip_provider_once", "Skip provider once")
                if check.get("variant_index") is not None
                else self._tr("health.skip_stage_once", "Skip stage once")
            )
            skip_btn = box.addButton(skip_label, QMessageBox.ActionRole)
            disable_btn = box.addButton(self._tr("health.disable_in_preset", "Disable in preset"), QMessageBox.ActionRole)
            fix_btn = box.addButton(self._tr("health.fix_now", "Fix now"), QMessageBox.ActionRole)
            cancel_btn = box.addButton(self._tr("health.cancel_run", "Cancel run"), QMessageBox.RejectRole)
            box.setDefaultButton(fix_btn)
            box.exec()
            clicked = box.clickedButton()
            if quick_btn is not None and clicked is quick_btn:
                self.run_plugin_quick_fix(plugin_id, quick_fix)
                report = self._check_plugin_with_progress(
                    plugin_id=plugin_id,
                    stage_id=stage_id,
                    stage_params=check.get("params", {}) if isinstance(check.get("params"), dict) else {},
                    full_check=True,
                    force=True,
                    max_age_seconds=120.0,
                    allow_disabled=bool(self._offline_mode()),
                    allow_stale_on_error=False,
                )
                if report.healthy:
                    return "continue"
                details = self.health_issues_text(report.issues)
                continue
            if clicked is skip_btn:
                return "skip_once"
            if clicked is disable_btn:
                return "disable_preset"
            if clicked is fix_btn:
                return "fix_now"
            if clicked is cancel_btn:
                return "cancel"
            return "cancel"

    def attempt_automatic_preflight_fix(
        self,
        *,
        stage_id: str,
        plugin_id: str,
        report: PluginHealthReport,
        check: dict,
    ) -> PluginHealthReport:
        if report.healthy:
            return report
        pid = str(plugin_id or "").strip()
        quick_fix = next((issue.quick_fix for issue in report.issues if issue.quick_fix), None)
        if not quick_fix:
            return report
        expected_action = str(
            _cap_get(self._plugin_capabilities(pid), "health", "server", "auto_start_action", default="")
            or ""
        ).strip()
        action_id = str(quick_fix.action_id or "").strip()
        if expected_action:
            if action_id != expected_action:
                return report
        elif action_id != "start_server":
            return report
        payload = dict(quick_fix.payload or {})
        payload["timeout_seconds"] = 60
        auto_fix = PluginHealthQuickFix(
            action_id=action_id or "start_server",
            label=str(quick_fix.label or "Start server"),
            payload=payload,
        )
        self._log_message(f"{pid}: auto-run quick fix '{auto_fix.action_id}' before pipeline run", "ui")
        self.run_plugin_quick_fix(plugin_id, auto_fix)
        refreshed = self._check_plugin_with_progress(
            plugin_id=plugin_id,
            stage_id=stage_id,
            stage_params=check.get("params", {}) if isinstance(check.get("params"), dict) else {},
            full_check=True,
            force=True,
            max_age_seconds=120.0,
            allow_disabled=bool(self._offline_mode()),
            allow_stale_on_error=False,
        )
        return refreshed

    def _check_plugin_with_progress(
        self,
        *,
        plugin_id: str,
        stage_id: str,
        stage_params: dict[str, object],
        full_check: bool,
        force: bool,
        max_age_seconds: float,
        allow_disabled: bool,
        allow_stale_on_error: bool,
        progress_payload: dict[str, object] | None = None,
    ) -> PluginHealthReport:
        result: dict[str, object] = {}
        errors: list[Exception] = []

        def _worker() -> None:
            try:
                report = self._health_service.check_plugin(
                    plugin_id,
                    stage_id=stage_id,
                    stage_params=stage_params,
                    full_check=full_check,
                    force=force,
                    max_age_seconds=max_age_seconds,
                    allow_disabled=allow_disabled,
                    allow_stale_on_error=allow_stale_on_error,
                )
                result["report"] = report
            except Exception as exc:  # pragma: no cover - defensive fallback
                errors.append(exc)

        thread = threading.Thread(target=_worker, daemon=True)
        started = time.monotonic()
        last_pulse = started - self._PROGRESS_PULSE_SECONDS
        thread.start()
        while thread.is_alive():
            now = time.monotonic()
            if progress_payload is not None and now - last_pulse >= self._PROGRESS_PULSE_SECONDS:
                payload = dict(progress_payload)
                payload["elapsed_seconds"] = int(max(0.0, now - started))
                self._report_progress(payload)
                last_pulse = now
            time.sleep(self._WAIT_POLL_SECONDS)
        thread.join()
        if errors:
            raise errors[0]
        report = result.get("report")
        if isinstance(report, PluginHealthReport) or (
            report is not None and hasattr(report, "healthy") and hasattr(report, "issues")
        ):
            return report
        # Fallback to a direct call only if worker did not return a report.
        return self._health_service.check_plugin(
            plugin_id,
            stage_id=stage_id,
            stage_params=stage_params,
            full_check=full_check,
            force=force,
            max_age_seconds=max_age_seconds,
            allow_disabled=allow_disabled,
            allow_stale_on_error=allow_stale_on_error,
        )

    @staticmethod
    def health_issues_text(issues: tuple[Any, ...]) -> str:
        lines: list[str] = []
        for issue in issues:
            if str(getattr(issue, "severity", "") or "") != "error":
                continue
            summary = str(getattr(issue, "summary", "") or "").strip()
            detail = str(getattr(issue, "detail", "") or "").strip()
            hint = str(getattr(issue, "hint", "") or "").strip()
            if summary:
                lines.append(f"- {summary}")
            if detail:
                lines.append(f"  detail: {detail}")
            if hint:
                lines.append(f"  hint: {hint}")
        if not lines:
            return "- Unknown plugin health issue."
        return "\n".join(lines[:14])

    def run_plugin_quick_fix(self, plugin_id: str, quick_fix: PluginHealthQuickFix) -> None:
        ok, message = self._health_service.invoke_quick_fix(plugin_id, quick_fix)
        if ok:
            self._log_message(f"{plugin_id}: quick-fix ok ({message})", "ui")
            return
        self._log_message(f"{plugin_id}: quick-fix failed ({message})", "ui")

    @staticmethod
    def stage_params_for_plugin(config_data: dict[str, object], stage_id: str, plugin_id: str) -> dict:
        stages = config_data.get("stages")
        if not isinstance(stages, dict):
            return {}
        stage = stages.get(stage_id, {})
        if not isinstance(stage, dict):
            return {}
        variants = stage.get("variants")
        if isinstance(variants, list):
            for entry in variants:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("plugin_id", "") or "").strip()
                if pid != plugin_id:
                    continue
                params = entry.get("params")
                return dict(params) if isinstance(params, dict) else {}
        params = stage.get("params")
        return dict(params) if isinstance(params, dict) else {}

    def show_plugin_health_dialog(self, plugin_id: str, issues: tuple[Any, ...]) -> None:
        box = QMessageBox(self._parent)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(self._tr("health.title", "Plugin Health"))
        box.setText(
            self._fmt(
                "health.not_ready_message",
                "{plugin_name} is not ready.",
                plugin_name=self._plugin_display_name(plugin_id),
            )
        )
        box.setInformativeText(self.health_issues_text(issues))
        quick_fix = next((getattr(issue, "quick_fix", None) for issue in issues if getattr(issue, "quick_fix", None)), None)
        quick_btn = None
        if quick_fix:
            quick_btn = box.addButton(str(quick_fix.label), QMessageBox.ActionRole)
        box.addButton(self._tr("button.close", "Close"), QMessageBox.AcceptRole)
        box.exec()
        if quick_btn and box.clickedButton() is quick_btn:
            self.run_plugin_quick_fix(plugin_id, quick_fix)
