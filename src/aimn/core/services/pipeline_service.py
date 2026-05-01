from __future__ import annotations

import logging
import os
import shutil
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aimn.core.app_paths import get_output_dir
from aimn.core.builtin_search import BuiltinSearchService
from aimn.core.contracts import StageEvent
from aimn.core.meeting_ids import utc_now_iso
from aimn.core.pipeline import PipelineEngine, PipelineResult, StageContext
from aimn.core.pipeline_presets import OFFLINE_PRESET_ID, offline_plugin_ids
from aimn.core.plugin_activation_service import PluginActivationService
from aimn.core.plugin_catalog_service import PluginCatalogService
from aimn.core.plugin_models_service import PluginModelsService
from aimn.core.plugins_config import PluginsConfig
from aimn.core.plugins_registry import ensure_plugins_enabled, load_registry_payload
from aimn.core.run_logging import append_run, failed_run, pipeline_result_to_run
from aimn.core.services.transcription_artifacts import purge_asr_debug_artifacts
from aimn.core.stages import StagesRegistry
from aimn.domain.meeting import MeetingManifest, PipelineRun


@dataclass
class PipelineRuntime:
    pipeline_config: PluginsConfig
    registry_config: PluginsConfig
    plugin_manager: "PluginManager"
    engine: PipelineEngine

    def shutdown(self) -> None:
        self.plugin_manager.shutdown()


def build_pipeline_runtime(repo_root: Path, config_data: dict) -> PipelineRuntime:
    from aimn.core.plugin_manager import PluginManager

    pipeline_config = PluginsConfig(config_data)
    registry_payload, _source, _path = load_registry_payload(repo_root)
    activation = PluginActivationService(repo_root)
    if pipeline_preset_id(config_data) == OFFLINE_PRESET_ID:
        registry_payload = ensure_plugins_enabled(
            registry_payload,
            offline_plugin_ids(repo_root),
        )
    registry_payload = activation.apply_to_registry_payload(registry_payload)
    registry_config = PluginsConfig(registry_payload)
    plugin_manager = PluginManager(repo_root, registry_config)
    plugin_manager.load()
    stages = StagesRegistry(pipeline_config).build()
    engine = PipelineEngine(stages)
    return PipelineRuntime(
        pipeline_config=pipeline_config,
        registry_config=registry_config,
        plugin_manager=plugin_manager,
        engine=engine,
    )


@dataclass
class PipelineRunOutcome:
    meeting: MeetingManifest
    result: PipelineResult | None
    run: PipelineRun
    error: str | None = None


class PipelineService:
    def __init__(self, repo_root: Path, config_data: dict) -> None:
        self._repo_root = repo_root
        self._runtime = build_pipeline_runtime(repo_root, config_data)
        self._output_dir = get_output_dir(repo_root)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._catalog_service = PluginCatalogService(repo_root)
        self._plugin_models = PluginModelsService(repo_root)
        self._builtin_search = BuiltinSearchService()
        from aimn.core.meeting_store import FileMeetingStore

        self._store = FileMeetingStore(self._output_dir)
        self._plugin_manager = self._runtime.plugin_manager


    def load_meeting(self, file_path: str | Path) -> MeetingManifest:
        from aimn.core.meeting_loader import load_or_create_meeting

        return load_or_create_meeting(self._store, Path(file_path))

    def save_meeting(self, meeting: MeetingManifest) -> None:
        self._store.save(meeting)

    def run_file(
        self,
        file_path: str | Path,
        *,
        force_run: bool = False,
        force_run_from: str | None = None,
        event_callback: Optional[Callable[[StageEvent], None]] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        cancel_requested: Optional[Callable[[], bool]] = None,
    ) -> PipelineRunOutcome:
        meeting = self.load_meeting(file_path)
        return self.run_meeting(
            meeting,
            force_run=force_run,
            force_run_from=force_run_from,
            event_callback=event_callback,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )

    def run_meeting(
        self,
        meeting: MeetingManifest,
        *,
        force_run: bool = False,
        force_run_from: str | None = None,
        event_callback: Optional[Callable[[StageEvent], None]] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        cancel_requested: Optional[Callable[[], bool]] = None,
    ) -> PipelineRunOutcome:
        warnings: list[str] = []
        model_outcomes: list[dict[str, str]] = []
        try:
            setattr(meeting, "processing_status", "running")
            setattr(meeting, "processing_error", "")
            meeting.updated_at = utc_now_iso()
        except Exception:
            pass

        def emit_event(event: StageEvent) -> None:
            if event.event_type == "plugin_notice":
                message = str(event.message or "")
                if message:
                    parsed_outcome = _parse_llm_model_outcome(message)
                    if parsed_outcome:
                        model_outcomes.append(parsed_outcome)
                    else:
                        prefix = f"{event.stage_id}:" if event.stage_id else ""
                        warnings.append(f"{prefix}{message}" if prefix else message)
            if event_callback:
                event_callback(event)
            self._emit_plugin_event(event, meeting)

        context = StageContext(
            meeting=meeting,
            force_run=force_run,
            force_run_from=force_run_from,
            output_dir=str(self._output_dir),
            progress_callback=progress_callback,
            event_callback=emit_event,
            plugin_manager=self._plugin_manager,
            cancel_requested=cancel_requested,
        )
        self._plugin_manager.clear_errors()
        try:
            result = self._runtime.engine.run(context, emit=emit_event)
        except Exception as exc:
            error = str(exc)
            run = failed_run(error)
            try:
                setattr(meeting, "processing_status", "failed")
                setattr(meeting, "processing_error", error)
            except Exception:
                pass
            append_run(meeting, run)
            try:
                purge_asr_debug_artifacts(meeting=meeting, output_dir=self._output_dir)
            except Exception:
                pass
            self._store.save(meeting)
            return PipelineRunOutcome(meeting=meeting, result=None, run=run, error=error)

        run = pipeline_result_to_run(result)
        self._persist_runtime_model_outcomes(model_outcomes)
        _sync_active_transcription_alias(meeting)
        _sync_active_llm_alias(meeting)
        final_status = "failed"
        if result.result in {"success", "partial_success"}:
            final_status = "completed"
        elif cancel_requested and cancel_requested():
            final_status = "cancelled"
        try:
            setattr(meeting, "processing_status", final_status)
            setattr(meeting, "processing_error", str(run.error or "") if final_status == "failed" else "")
        except Exception:
            pass
        if warnings:
            run.warnings.extend(warnings)
        for plugin_id, errors in self._plugin_manager.plugin_errors().items():
            for error in errors:
                run.warnings.append(f"{plugin_id}: {error}")
        append_run(meeting, run)
        try:
            purge_asr_debug_artifacts(meeting=meeting, output_dir=self._output_dir)
        except Exception:
            pass
        self._store.save(meeting)
        return PipelineRunOutcome(meeting=meeting, result=result, run=run)

    def shutdown(self) -> None:
        self._runtime.shutdown()

    def dependency_warnings(self) -> list[str]:
        return _dependency_warnings(
            self._runtime.pipeline_config,
            self._plugin_manager,
            self._repo_root,
            self._catalog_service,
        )

    def _emit_plugin_event(self, event: StageEvent, meeting: MeetingManifest) -> None:
        from aimn.core.meeting_ids import utc_now_iso

        payload = {
            "event_type": event.event_type,
            "meeting_id": meeting.meeting_id,
            "base_name": meeting.base_name,
            "stage_id": event.stage_id,
            "event_message": event.message,
            "alias": event.alias,
            "kind": event.kind,
            "relpath": event.relpath,
            "progress": event.progress,
            "timestamp": event.timestamp or utc_now_iso(),
        }
        logging.getLogger("aimn.pipeline").info("stage_event", extra=payload)
        if event.event_type == "artifact_written":
            try:
                self._builtin_search.on_artifact_written(
                    meeting_id=str(meeting.meeting_id or ""),
                    stage_id=str(event.stage_id or ""),
                    alias=str(event.alias or ""),
                    kind=str(event.kind or ""),
                    relpath=str(event.relpath or event.message or ""),
                )
            except Exception as exc:
                logging.getLogger("aimn.search").warning(
                    "search_index_update_failed meeting_id=%s stage_id=%s alias=%s kind=%s relpath=%s error=%s",
                    str(meeting.meeting_id or ""),
                    str(event.stage_id or ""),
                    str(event.alias or ""),
                    str(event.kind or ""),
                    str(event.relpath or event.message or ""),
                    exc,
                )
            self._plugin_manager.emit("on_artifact_stored", payload)
        if event.event_type == "pipeline_finished":
            self._plugin_manager.emit("on_meeting_completed", payload)
        self._plugin_manager.emit(event.event_type, payload)

    def _persist_runtime_model_outcomes(self, outcomes: list[dict[str, str]]) -> None:
        aggregated = _aggregate_llm_model_outcomes(outcomes)
        for item in aggregated:
            plugin_id = str(item.get("plugin_id", "") or "").strip()
            model_id = str(item.get("model_id", "") or "").strip()
            if not plugin_id or not model_id:
                continue
            self._plugin_models.update_model_runtime_status(
                plugin_id,
                model_id,
                availability_status=str(item.get("availability_status", "") or "").strip().lower(),
                failure_code=str(item.get("failure_code", "") or "").strip().lower(),
                summary_quality=str(item.get("summary_quality", "") or "").strip().lower(),
            )


def pipeline_preset_id(config_data: dict) -> str:
    pipeline = config_data.get("pipeline")
    if isinstance(pipeline, dict):
        preset = pipeline.get("preset")
        if preset:
            return str(preset).strip()
    preset = config_data.get("preset")
    return str(preset).strip() if preset else ""


def _parse_llm_model_outcome(message: str) -> dict[str, str] | None:
    raw = str(message or "").strip()
    prefix = "llm_model_outcome:"
    if not raw.startswith(prefix):
        return None
    payload_raw = raw[len(prefix) :].strip()
    if not payload_raw:
        return None
    try:
        payload = json.loads(payload_raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    plugin_id = str(payload.get("plugin_id", "") or "").strip()
    model_id = str(payload.get("model_id", "") or "").strip()
    if not plugin_id or not model_id:
        return None
    return {
        "plugin_id": plugin_id,
        "model_id": model_id,
        "summary_quality": str(payload.get("summary_quality", "") or "").strip().lower(),
        "failure_code": str(payload.get("failure_code", "") or "").strip().lower(),
    }


def _aggregate_llm_model_outcomes(outcomes: list[dict[str, str]]) -> list[dict[str, str]]:
    by_model: dict[tuple[str, str], list[dict[str, str]]] = {}
    for item in outcomes:
        plugin_id = str(item.get("plugin_id", "") or "").strip()
        model_id = str(item.get("model_id", "") or "").strip()
        if not plugin_id or not model_id:
            continue
        by_model.setdefault((plugin_id, model_id), []).append(item)

    aggregated: list[dict[str, str]] = []
    for (plugin_id, model_id), items in by_model.items():
        qualities = [str(item.get("summary_quality", "") or "").strip().lower() for item in items]
        failure_codes = [
            str(item.get("failure_code", "") or "").strip().lower() for item in items if str(item.get("failure_code", "") or "").strip()
        ]
        if "usable" in qualities:
            aggregated.append(
                {
                    "plugin_id": plugin_id,
                    "model_id": model_id,
                    "summary_quality": "usable",
                    "failure_code": "",
                    "availability_status": "ready",
                }
            )
            continue
        if "degraded" in qualities:
            aggregated.append(
                {
                    "plugin_id": plugin_id,
                    "model_id": model_id,
                    "summary_quality": "degraded",
                    "failure_code": next(iter(failure_codes), "llm_degraded_summary_artifact"),
                    "availability_status": "limited",
                }
            )
            continue
        failure_code = next(iter(failure_codes), "request_failed")
        aggregated.append(
            {
                "plugin_id": plugin_id,
                "model_id": model_id,
                "summary_quality": "failed",
                "failure_code": failure_code,
                "availability_status": _availability_status_from_failure_code(failure_code),
            }
        )
    return aggregated


def _availability_status_from_failure_code(failure_code: str) -> str:
    code = str(failure_code or "").strip().lower()
    if not code:
        return "unknown"
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


def _sync_active_transcription_alias(meeting: MeetingManifest) -> None:
    transcript_relpath = str(getattr(meeting, "transcript_relpath", "") or "").strip()
    if not transcript_relpath:
        return
    alias = _find_alias_for_artifact(
        meeting,
        stage_id="transcription",
        kind="transcript",
        relpath=transcript_relpath,
    )
    if not alias:
        return
    active = getattr(meeting, "active_aliases", None)
    if not isinstance(active, dict):
        active = {}
    active["transcription"] = alias
    meeting.active_aliases = active


def _sync_active_llm_alias(meeting: MeetingManifest) -> None:
    alias = _latest_alias_for_stage_kind(
        meeting,
        stage_id="llm_processing",
        kind="summary",
    )
    if not alias:
        return
    active = getattr(meeting, "active_aliases", None)
    if not isinstance(active, dict):
        active = {}
    active["llm_processing"] = alias
    meeting.active_aliases = active


def _latest_alias_for_stage_kind(
    meeting: MeetingManifest,
    *,
    stage_id: str,
    kind: str,
) -> str:
    target_stage = str(stage_id or "").strip()
    target_kind = str(kind or "").strip()
    if not target_stage or not target_kind:
        return ""
    latest_alias = ""
    latest_created = ""
    for alias, node in (getattr(meeting, "nodes", {}) or {}).items():
        if str(getattr(node, "stage_id", "") or "").strip() != target_stage:
            continue
        has_kind = any(
            str(getattr(artifact, "kind", "") or "").strip() == target_kind
            for artifact in (getattr(node, "artifacts", []) or [])
        )
        if not has_kind:
            continue
        created_at = str(getattr(node, "created_at", "") or "")
        if not latest_alias or created_at > latest_created:
            latest_alias = str(alias or "").strip()
            latest_created = created_at
    return latest_alias


def _find_alias_for_artifact(
    meeting: MeetingManifest,
    *,
    stage_id: str,
    kind: str,
    relpath: str,
) -> str:
    target_stage = str(stage_id or "").strip()
    target_kind = str(kind or "").strip()
    target_relpath = str(relpath or "").strip()
    if not target_stage or not target_kind or not target_relpath:
        return ""
    for alias, node in (getattr(meeting, "nodes", {}) or {}).items():
        if str(getattr(node, "stage_id", "") or "").strip() != target_stage:
            continue
        for artifact in getattr(node, "artifacts", []) or []:
            if str(getattr(artifact, "kind", "") or "").strip() != target_kind:
                continue
            if str(getattr(artifact, "path", "") or "").strip() == target_relpath:
                return str(alias or "").strip()
    return ""


def _dependency_warnings(
    config: PluginsConfig,
    plugin_manager: "PluginManager",
    repo_root: Path,
    catalog_service: PluginCatalogService,
) -> list[str]:
    warnings: list[str] = []
    from aimn.core.media_conversion import get_ffmpeg_path

    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path.exists():
        warnings.append("Missing FFmpeg binary. Set AIMN_FFMPEG_PATH or install bin/ffmpeg/ffmpeg.")
    try:
        transcribe_plugin = str(config.plugin_id_for("transcription") or "").strip()
    except Exception:
        transcribe_plugin = ""
    _append_local_binary_warning(
        warnings,
        plugin_id=transcribe_plugin,
        plugin_manager=plugin_manager,
        repo_root=repo_root,
        catalog_service=catalog_service,
    )
    llm_plugins = _llm_plugin_ids(config)
    for plugin_id in llm_plugins:
        _append_local_binary_warning(
            warnings,
            plugin_id=plugin_id,
            plugin_manager=plugin_manager,
            repo_root=repo_root,
            catalog_service=catalog_service,
        )
    return warnings


def _append_local_binary_warning(
    warnings: list[str],
    *,
    plugin_id: str,
    plugin_manager: "PluginManager",
    repo_root: Path,
    catalog_service: PluginCatalogService,
) -> None:
    pid = str(plugin_id or "").strip()
    if not pid:
        return
    capability = _plugin_local_binary_capability(catalog_service, pid)
    if not capability:
        return
    setting_key = str(capability.get("setting_key", "") or "").strip()
    env_key = str(capability.get("env_key", "") or "").strip()
    fallback = str(capability.get("fallback", "") or capability.get("default_path", "") or "").strip()
    label = str(capability.get("label", "") or f"{pid} binary").strip()
    settings = plugin_manager.get_settings(pid)
    raw = str(settings.get(setting_key, "") or "").strip() if setting_key else ""
    resolved = _resolve_binary(repo_root, raw, env_key)
    if not resolved and fallback:
        resolved = _resolve_binary(repo_root, fallback, env_key)
    if resolved:
        return
    hint_parts: list[str] = []
    if setting_key:
        hint_parts.append(f"Set '{setting_key}' in Settings")
    if env_key:
        hint_parts.append(f"or define {env_key}" if hint_parts else f"Define {env_key}")
    hint = " ".join(hint_parts).strip() or "Configure plugin binary path"
    warnings.append(f"{label} missing. {hint}.")


def _plugin_local_binary_capability(
    catalog_service: PluginCatalogService,
    plugin_id: str,
) -> dict:
    pid = str(plugin_id or "").strip()
    if not pid:
        return {}
    try:
        plugin = catalog_service.load().catalog.plugin_by_id(pid)
    except Exception:
        return {}
    caps = getattr(plugin, "capabilities", None) if plugin else None
    if not isinstance(caps, dict):
        return {}
    runtime = caps.get("runtime")
    if not isinstance(runtime, dict):
        return {}
    local_binary = runtime.get("local_binary")
    return dict(local_binary) if isinstance(local_binary, dict) else {}


def _llm_plugin_ids(config: PluginsConfig) -> list[str]:
    plugin_ids: list[str] = []
    try:
        plugin_ids.append(str(config.plugin_id_for("llm_processing")))
    except Exception:
        pass
    for variant in config.variants_for_stage("llm_processing"):
        plugin_id = str(variant.get("plugin_id", "")).strip()
        if plugin_id:
            plugin_ids.append(plugin_id)
    return sorted({pid for pid in plugin_ids if pid})


def _resolve_binary(repo_root: Path, path_value: str, env_key: str) -> str:
    env_value = os.getenv(env_key, "").strip()
    raw = env_value or path_value
    if not raw:
        return ""
    path = Path(raw)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(repo_root / path)
        candidates.append(path)
    if path.suffix == ".exe":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(""))
    if path.suffix == "" and os.name == "nt":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(".exe"))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    system_match = shutil.which(raw)
    if not system_match:
        system_match = shutil.which(Path(raw).name)
    if system_match:
        return str(Path(system_match))
    return ""
