from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from aimn.core.action_runner import run_action_subprocess
from aimn.core.contracts import ActionDescriptor, ActionResult, HookContext, JobStatus, PluginResult
from aimn.core.import_guard import ensure_core_does_not_import_plugins
from aimn.core.plugin_services import (
    HookExecution,
    PluginLoader,
    PluginRegistry,
    PluginRuntime,
    PluginSettingsService,
)
from aimn.core.plugin_trust import PluginTrustResolver
from aimn.core.plugins_config import PluginsConfig


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class _AsyncJobEntry:
    plugin_id: str
    action_id: str
    status: JobStatus
    cancel_event: threading.Event


class _AsyncActionJobs:
    def __init__(self) -> None:
        self._jobs: dict[tuple[str, str], _AsyncJobEntry] = {}
        self._lock = threading.RLock()

    def start(
        self,
        plugin_id: str,
        action_id: str,
        runner: Callable[[dict, dict], ActionResult] | None,
        settings: dict,
        params: dict,
    ) -> ActionResult:
        if not callable(runner):
            return ActionResult(status="error", message="action_not_found")
        job_id = f"job-{uuid4().hex[:12]}"
        cancel_event = threading.Event()
        status = JobStatus(
            job_id=job_id,
            status="queued",
            progress=0.0,
            message="queued",
            updated_at=_utc_now_iso(),
        )
        entry = _AsyncJobEntry(
            plugin_id=str(plugin_id),
            action_id=str(action_id),
            status=status,
            cancel_event=cancel_event,
        )
        key = (str(plugin_id), job_id)
        with self._lock:
            self._jobs[key] = entry

        thread = threading.Thread(
            target=self._run_job,
            args=(entry, runner, dict(settings or {}), dict(params or {})),
            daemon=True,
        )
        thread.start()
        return ActionResult(status="accepted", message="job_started", job_id=job_id)

    def get_status(self, plugin_id: str, job_id: str) -> JobStatus | None:
        key = (str(plugin_id), str(job_id))
        with self._lock:
            entry = self._jobs.get(key)
            if not entry:
                return None
            status = entry.status
            return JobStatus(
                job_id=status.job_id,
                status=status.status,
                progress=status.progress,
                message=status.message,
                data=status.data,
                updated_at=status.updated_at,
            )

    def cancel(self, plugin_id: str, job_id: str) -> bool:
        key = (str(plugin_id), str(job_id))
        with self._lock:
            entry = self._jobs.get(key)
            if not entry:
                return False
            entry.cancel_event.set()
            if entry.status.status in {"queued", "running"}:
                entry.status = JobStatus(
                    job_id=entry.status.job_id,
                    status="cancelled",
                    progress=entry.status.progress,
                    message="cancel_requested",
                    data=entry.status.data,
                    updated_at=_utc_now_iso(),
                )
            return True

    def _run_job(
        self,
        entry: _AsyncJobEntry,
        runner: Callable[[dict, dict], ActionResult],
        settings: dict,
        params: dict,
    ) -> None:
        key = (entry.plugin_id, entry.status.job_id)
        with self._lock:
            current = self._jobs.get(key)
            if not current:
                return
            if current.cancel_event.is_set():
                current.status = JobStatus(
                    job_id=current.status.job_id,
                    status="cancelled",
                    progress=0.0,
                    message="cancel_requested",
                    updated_at=_utc_now_iso(),
                )
                return
            current.status = JobStatus(
                job_id=current.status.job_id,
                status="running",
                progress=0.0,
                message="running",
                updated_at=_utc_now_iso(),
            )

        params_with_cancel = dict(params)
        params_with_cancel["_cancel_requested"] = entry.cancel_event.is_set
        try:
            raw = runner(settings, params_with_cancel)
            result = _coerce_action_result(raw)
            if entry.cancel_event.is_set():
                status = JobStatus(
                    job_id=entry.status.job_id,
                    status="cancelled",
                    progress=1.0,
                    message="cancel_requested",
                    updated_at=_utc_now_iso(),
                )
            else:
                final_state = "success" if result.status in {"ok", "success", "accepted"} else "failed"
                status = JobStatus(
                    job_id=entry.status.job_id,
                    status=final_state,
                    progress=1.0,
                    message=str(result.message or final_state),
                    data=result.data,
                    updated_at=_utc_now_iso(),
                )
        except Exception as exc:
            status = JobStatus(
                job_id=entry.status.job_id,
                status="failed",
                progress=1.0,
                message=str(exc),
                updated_at=_utc_now_iso(),
            )
        with self._lock:
            current = self._jobs.get(key)
            if not current:
                return
            current.status = status


def _coerce_action_result(raw: object) -> ActionResult:
    if isinstance(raw, ActionResult):
        return raw
    if isinstance(raw, dict):
        return ActionResult(
            status=str(raw.get("status", "error")),
            message=str(raw.get("message", "")),
            data=raw.get("data"),
            warnings=[str(w) for w in raw.get("warnings", []) if str(w)],
            job_id=str(raw.get("job_id", "")).strip() or None,
        )
    return ActionResult(status="error", message="invalid_action_result")


class PluginManager:
    def __init__(self, repo_root: Path, config: PluginsConfig) -> None:
        self._repo_root = repo_root
        self.config = config
        self._registry = PluginRegistry()
        self._settings = PluginSettingsService(repo_root, self._registry)
        self._runtime = PluginRuntime(self._registry, config)
        self._loader = PluginLoader(repo_root, config, self._registry, self._settings)
        self._async_jobs = _AsyncActionJobs()

    def load(self) -> None:
        ensure_core_does_not_import_plugins(self._repo_root)
        self._loader.load()

    def shutdown(self) -> None:
        self._loader.shutdown()

    def manifests(self):
        return self._registry.manifests()

    def manifest_for(self, plugin_id: str):
        return self._registry.manifest_for(plugin_id)

    def execute_connector(
        self,
        name: str,
        ctx: HookContext,
        allowed_plugin_ids: Optional[Iterable[str]] = None,
    ) -> List[HookExecution]:
        return self._runtime.execute_connector(name, ctx, allowed_plugin_ids=allowed_plugin_ids)

    def register_artifact_kind(self, kind: str, schema, plugin_id: str) -> None:
        self._registry.register_artifact_kind(kind, schema, plugin_id)

    def register_hook_handler(
        self,
        plugin_id: str,
        hook_name: str,
        handler: Callable[[HookContext], PluginResult],
        *,
        mode: str = "optional",
        priority: int = 100,
        handler_id: str | None = None,
    ) -> None:
        self._registry.register_hook_handler(
            plugin_id=plugin_id,
            hook_name=hook_name,
            handler=handler,
            mode=mode,
            priority=priority,
            handler_id=handler_id,
        )

    def artifact_schema(self, kind: str):
        return self._registry.artifact_schema(kind)

    def subscribe(self, event_name: str, handler: Callable, plugin_id: str) -> None:
        self._registry.subscribe(event_name, handler, plugin_id)

    def emit(self, event_name: str, payload: dict) -> None:
        self._registry.emit(event_name, payload)

    def register_settings_schema(self, plugin_id: str, provider: Callable[[], dict]) -> None:
        self._registry.register_settings_schema(plugin_id, provider)

    def register_actions(self, plugin_id: str, provider: Callable[[], List[ActionDescriptor]]) -> None:
        self._registry.register_actions(plugin_id, provider)

    def register_job_provider(self, plugin_id: str, provider: Callable[[], dict]) -> None:
        self._registry.register_job_provider(plugin_id, provider)

    def register_service(self, plugin_id: str, service_name: str, provider) -> None:
        self._registry.register_service(plugin_id, service_name, provider)

    def get_service(self, service_name: str):
        return self._registry.get_service(service_name)

    def settings_schema_for(self, plugin_id: str) -> Optional[dict]:
        return self._registry.settings_schema_for(plugin_id)

    def actions_for(self, plugin_id: str) -> List[ActionDescriptor]:
        return self._registry.actions_for(plugin_id)

    def get_settings(self, plugin_id: str, *, include_secrets: bool = False) -> dict:
        return self._settings.get_settings(plugin_id, include_secrets=include_secrets)

    def get_settings_with_secrets(self, plugin_id: str) -> dict:
        return self._settings.get_settings_with_secrets(plugin_id)

    def get_secret_flags(self, plugin_id: str) -> dict:
        return self._settings.get_secret_flags(plugin_id)

    def get_secret(self, plugin_id: str, key: str, *, default: str | None = None) -> str | None:
        return self._settings.get_secret(plugin_id, key, default=default)

    def set_secret(self, plugin_id: str, key: str, value: str | None) -> None:
        self._settings.set_secret(plugin_id, key, value)

    def get_storage_path(self, plugin_id: str) -> Path:
        return self._settings.get_storage_path(plugin_id)

    def set_settings(self, plugin_id: str, settings: dict, *, secret_fields: Iterable[str]) -> None:
        self._settings.set_settings(plugin_id, settings, secret_fields=secret_fields)

    def invoke_action(
        self,
        plugin_id: str,
        action_id: str,
        params: dict,
        *,
        settings_override: dict | None = None,
    ) -> ActionResult:
        actions = self.actions_for(plugin_id)
        action = next((item for item in actions if item.action_id == action_id), None)
        if not action or not action.handler:
            return ActionResult(status="error", message="action_not_found")
        force_sync = os.environ.get("AIMN_ACTION_FORCE_SYNC") == "1"
        settings = (
            settings_override
            if settings_override is not None
            else self.get_settings(plugin_id, include_secrets=True)
        )
        run_mode = str(action.run_mode or "sync").strip().lower()
        if run_mode == "async" and not force_sync:
            if self.should_isolate_action(plugin_id):
                return self._async_jobs.start(
                    plugin_id,
                    action_id,
                    lambda _settings, action_params: run_action_subprocess(
                        self._repo_root,
                        plugin_id,
                        action_id,
                        action_params,
                        settings_override=settings,
                    ),
                    settings,
                    params,
                )
            return self._async_jobs.start(plugin_id, action_id, action.handler, settings, params)
        if self.should_isolate_action(plugin_id):
            return run_action_subprocess(
                self._repo_root,
                plugin_id,
                action_id,
                params,
                settings_override=settings_override,
            )
        try:
            result = action.handler(settings, params)
            return _coerce_action_result(result)
        except Exception as exc:
            self._registry._record_error(plugin_id, f"action_failed:{action_id}:{exc}")
            return ActionResult(status="error", message=str(exc))

    def get_job_status(self, plugin_id: str, job_id: str) -> Optional[JobStatus]:
        async_status = self._async_jobs.get_status(plugin_id, job_id)
        if async_status is not None:
            return async_status
        provider = self._registry.job_provider_for(plugin_id)
        if not provider:
            return None
        try:
            api = provider()
            getter = api.get("get_status") if isinstance(api, dict) else None
            if not callable(getter):
                return None
            status = getter(job_id)
        except Exception as exc:
            self._registry._record_error(plugin_id, f"job_status_failed:{exc}")
            return None
        if isinstance(status, JobStatus):
            return status
        if isinstance(status, dict) and status.get("job_id"):
            return JobStatus(
                job_id=str(status.get("job_id")),
                status=str(status.get("status", "")),
                progress=status.get("progress"),
                message=str(status.get("message", "")) if status.get("message") else "",
                data=status.get("data"),
                updated_at=str(status.get("updated_at")) if status.get("updated_at") else None,
            )
        return None

    def cancel_job(self, plugin_id: str, job_id: str) -> bool:
        if self._async_jobs.cancel(plugin_id, job_id):
            return True
        provider = self._registry.job_provider_for(plugin_id)
        if not provider:
            return False
        try:
            api = provider()
            cancel = api.get("cancel") if isinstance(api, dict) else None
            if not callable(cancel):
                return False
            return bool(cancel(job_id))
        except Exception as exc:
            self._registry._record_error(plugin_id, f"job_cancel_failed:{exc}")
            return False

    def plugin_errors(self) -> Dict[str, List[str]]:
        return self._registry.plugin_errors()

    def clear_errors(self) -> None:
        self._registry.clear_errors()

    def is_plugin_trusted(self, plugin_id: str) -> bool:
        if plugin_id in self.config.trusted_plugins():
            return True
        manifest = self._registry.manifest_for(plugin_id)
        decision = PluginTrustResolver(self._repo_root).trust_for_plugin(
            plugin_id,
            manifest_path=self._loader.manifest_path_for(plugin_id),
            distribution=manifest.distribution if manifest else None,
        )
        return decision.trusted

    def should_isolate_action(self, plugin_id: str) -> bool:
        if plugin_id in self.config.trusted_plugins():
            return False
        if os.environ.get("AIMN_ACTION_ISOLATION") == "0":
            return False
        if plugin_id in set(self.config.isolated_action_plugins()):
            return True
        return not self.is_plugin_trusted(plugin_id)

    def should_isolate_hook(self, plugin_id: str) -> bool:
        if plugin_id in self.config.trusted_plugins():
            return False
        if plugin_id in set(self.config.isolated_hook_plugins()):
            return True
        return not self.is_plugin_trusted(plugin_id)
