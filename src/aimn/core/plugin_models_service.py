from __future__ import annotations

import json
import time
from pathlib import Path

from aimn.core.app_paths import get_config_dir
from aimn.core.atomic_io import atomic_write_text
from aimn.core.release_profile import resolve_release_config_path


_PIPELINE_RATE_LIMIT_COOLDOWN_SECONDS = 30 * 60
_PIPELINE_TRANSIENT_COOLDOWN_SECONDS = 10 * 60
_PIPELINE_DEGRADED_COOLDOWN_SECONDS = 15 * 60
_PIPELINE_TRANSPORT_QUARANTINE_SECONDS = 20 * 60


class PluginModelsService:
    def __init__(self, app_root: Path) -> None:
        self._app_root = app_root

    def load_models_config(self, plugin_id: str) -> list[dict]:
        local_path = get_config_dir(self._app_root) / "settings" / "plugins" / f"{plugin_id}.json"
        path = local_path
        if not path.exists():
            release_default = resolve_release_config_path(
                Path("settings") / "plugins" / f"{plugin_id}.json",
                fallback_path=path,
            )
            if not release_default.exists():
                return []
            path = release_default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return []
        migrated = [self._normalize_model_entry(entry) for entry in models if isinstance(entry, dict)]
        if path == local_path and migrated != [entry for entry in models if isinstance(entry, dict)]:
            payload["models"] = migrated
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return migrated

    def model_files(self, plugin_id: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for entry in self.load_models_config(plugin_id):
            model_id = str(entry.get("model_id", "")).strip()
            filename = str(entry.get("file", "") or entry.get("filename", "")).strip()
            if model_id and filename:
                mapping[model_id] = filename
        return mapping

    def update_model_enabled(self, plugin_id: str, model_id: str, enabled: bool) -> None:
        path = get_config_dir(self._app_root) / "settings" / "plugins" / f"{plugin_id}.json"
        payload: dict = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            models = []
        updated = False
        for entry in models:
            if not isinstance(entry, dict):
                continue
            mid = str(entry.get("model_id", "")).strip()
            if mid == str(model_id or "").strip():
                entry["enabled"] = bool(enabled)
                updated = True
                break
        if not updated:
            models.append(
                {
                    "model_id": str(model_id or "").strip(),
                    "enabled": bool(enabled),
                    "availability_status": "unknown",
                }
            )
        normalized_models: list[dict] = []
        for entry in models:
            if not isinstance(entry, dict):
                continue
            row = self._normalize_model_entry(entry)
            if "favorite" not in entry:
                row.pop("favorite", None)
            normalized_models.append(row)
        payload["models"] = normalized_models
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))

    def update_model_favorite(self, plugin_id: str, model_id: str, favorite: bool) -> None:
        self.update_model_enabled(plugin_id, model_id, favorite)

    def update_model_runtime_status(
        self,
        plugin_id: str,
        model_id: str,
        *,
        availability_status: str,
        failure_code: str = "",
        summary_quality: str = "",
        selectable: bool | None = None,
    ) -> None:
        pid = str(plugin_id or "").strip()
        mid = str(model_id or "").strip()
        if not pid or not mid:
            return
        path = get_config_dir(self._app_root) / "settings" / "plugins" / f"{pid}.json"
        payload: dict = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            models = []
        now_ts = int(time.time())
        normalized_status = self._normalize_runtime_availability_status(availability_status, failure_code)
        row_failure_code = str(failure_code or "").strip().lower()
        row_selectable = (
            bool(selectable)
            if isinstance(selectable, bool)
            else normalized_status in {"ready", "unknown", "limited"}
        )
        updated = False
        for entry in models:
            if not isinstance(entry, dict):
                continue
            row_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            if row_id != mid:
                continue
            self._apply_runtime_outcome_to_entry(
                entry,
                now_ts=now_ts,
                availability_status=normalized_status,
                failure_code=row_failure_code,
                summary_quality=summary_quality,
                selectable=row_selectable,
            )
            updated = True
            break
        if not updated:
            row: dict[str, object] = {
                "model_id": mid,
                "product_name": mid,
            }
            self._apply_runtime_outcome_to_entry(
                row,
                now_ts=now_ts,
                availability_status=normalized_status,
                failure_code=row_failure_code,
                summary_quality=summary_quality,
                selectable=row_selectable,
            )
            models.append(row)
        payload["models"] = [self._normalize_model_entry(entry) for entry in models if isinstance(entry, dict)]
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))

    @staticmethod
    def _normalize_model_entry(entry: dict) -> dict:
        row = dict(entry)
        favorite = row.get("favorite")
        enabled = row.get("enabled")
        if isinstance(favorite, bool):
            row["favorite"] = favorite
            if isinstance(enabled, bool) and enabled != favorite:
                row["enabled"] = favorite
        elif isinstance(enabled, bool):
            row["favorite"] = enabled
        status = str(row.get("availability_status", "") or "").strip().lower()
        if not status:
            raw = str(row.get("status", "") or "").strip().lower()
            if raw in {"installed", "enabled", "ready", "ok", "success"}:
                status = "ready"
            elif raw in {"not_installed", "missing", "model_missing", "setup_required", "api_key_missing", "auth_missing", "download_required", "available"}:
                status = "needs_setup"
            elif raw in {"rate_limited", "cooling_down", "cooldown", "quota_limited"}:
                status = "limited"
            elif raw in {"request_failed", "failed", "error", "unavailable", "blocked", "forbidden", "auth_required", "timeout", "transport_error", "network_error"}:
                status = "unavailable"
            else:
                installed = row.get("installed")
                if isinstance(installed, bool):
                    status = "ready" if installed else "needs_setup"
                else:
                    status = "unknown"
            row["availability_status"] = status
        return row

    @staticmethod
    def _normalize_runtime_availability_status(status: object, failure_code: object) -> str:
        raw = str(status or "").strip().lower()
        if raw in {"ready", "needs_setup", "unknown", "unavailable", "limited"}:
            return raw
        code = str(failure_code or "").strip().lower()
        if code in {"", "ok", "success"}:
            return "ready" if raw == "ready" else "unknown"
        if code in {"auth_error", "api_key_missing", "model_missing", "setup_required", "download_required"}:
            return "needs_setup"
        if code in {
            "rate_limited",
            "cooling_down",
            "cooldown",
            "quota_limited",
            "empty_response",
            "llm_degraded_summary_artifact",
        }:
            return "limited"
        return "unavailable"

    @classmethod
    def _apply_runtime_outcome_to_entry(
        cls,
        entry: dict,
        *,
        now_ts: int,
        availability_status: str,
        failure_code: str,
        summary_quality: str,
        selectable: bool,
    ) -> None:
        normalized_status = cls._normalize_runtime_availability_status(availability_status, failure_code)
        quality = str(summary_quality or "").strip().lower()
        failure = str(failure_code or "").strip().lower()
        entry["status"] = "ready" if normalized_status == "ready" else (failure or normalized_status)
        entry["availability_status"] = normalized_status
        entry["failure_code"] = failure
        entry["selectable"] = bool(selectable)
        entry["last_pipeline_at"] = now_ts
        if quality:
            entry["last_pipeline_quality"] = quality

        if normalized_status == "ready":
            entry["last_ok_at"] = now_ts
            entry["pipeline_failure_streak"] = 0
            entry["last_failure_at"] = 0
            entry["last_failure_code"] = ""
            entry["cooldown_until"] = 0
            entry["blocked_for_account"] = False
            return

        streak = int(entry.get("pipeline_failure_streak", 0) or 0) + 1
        entry["pipeline_failure_streak"] = streak
        entry["last_failure_at"] = now_ts
        entry["last_failure_code"] = failure
        if failure == "provider_blocked":
            entry["blocked_for_account"] = True
            entry["selectable"] = False
            entry["cooldown_until"] = 0
            return
        entry["blocked_for_account"] = False
        if failure == "rate_limited":
            entry["cooldown_until"] = now_ts + _PIPELINE_RATE_LIMIT_COOLDOWN_SECONDS
            entry["selectable"] = False
            return
        if failure in {"transport_error", "network_error", "timeout"}:
            entry["cooldown_until"] = (
                now_ts + _PIPELINE_TRANSPORT_QUARANTINE_SECONDS if streak >= 2 else now_ts + _PIPELINE_TRANSIENT_COOLDOWN_SECONDS
            )
            entry["selectable"] = False
            return
        if failure in {"empty_response", "llm_degraded_summary_artifact"} or quality == "degraded":
            entry["cooldown_until"] = now_ts + _PIPELINE_DEGRADED_COOLDOWN_SECONDS
            entry["selectable"] = streak < 2
            return
        if failure:
            entry["cooldown_until"] = now_ts + _PIPELINE_TRANSIENT_COOLDOWN_SECONDS if streak >= 2 else 0
            if streak >= 2:
                entry["selectable"] = False
