from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_MEETING_LOAD_ERRORS = (FileNotFoundError, OSError, RuntimeError, ValueError)


@dataclass(frozen=True)
class ArtifactLineageResolution:
    meeting: object | None
    node: object | None


class ArtifactLineageController:
    @staticmethod
    def resolve_lineage_node(
        *,
        stage_id: str,
        alias: str,
        active_meeting_manifest: object | None,
        active_meeting_base_name: str,
        load_meeting: Callable[[str], object],
        log_load_error: Callable[[str, Exception], None],
    ) -> ArtifactLineageResolution:
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        meeting = active_meeting_manifest
        if not sid or not al:
            return ArtifactLineageResolution(meeting=meeting, node=None)
        if meeting is None and str(active_meeting_base_name or "").strip():
            base = str(active_meeting_base_name or "").strip()
            try:
                meeting = load_meeting(base)
            except _MEETING_LOAD_ERRORS as exc:
                log_load_error(base, exc)
                meeting = None
        if meeting is None:
            return ArtifactLineageResolution(meeting=None, node=None)
        nodes = getattr(meeting, "nodes", {})
        if not isinstance(nodes, dict):
            return ArtifactLineageResolution(meeting=meeting, node=None)
        node = nodes.get(al)
        if node is not None and str(getattr(node, "stage_id", "") or "").strip() == sid:
            return ArtifactLineageResolution(meeting=meeting, node=node)
        for node_alias, candidate in nodes.items():
            if str(node_alias or "").strip() != al:
                continue
            if str(getattr(candidate, "stage_id", "") or "").strip() == sid:
                return ArtifactLineageResolution(meeting=meeting, node=candidate)
        return ArtifactLineageResolution(meeting=meeting, node=None)

    @staticmethod
    def provider_id_for_node(node: object | None) -> str:
        if node is None:
            return ""
        tool = getattr(node, "tool", None)
        return str(getattr(tool, "plugin_id", "") or "").strip()

    @staticmethod
    def enable_stage_in_runtime_config(runtime_config: dict[str, object], stage_id: str) -> None:
        sid = str(stage_id or "").strip()
        if not sid:
            return
        pipeline = runtime_config.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
            runtime_config["pipeline"] = pipeline
        raw_disabled = pipeline.get("disabled_stages")
        disabled = [str(item or "").strip() for item in raw_disabled] if isinstance(raw_disabled, list) else []
        disabled_set = {item for item in disabled if item}
        disabled_set.discard(sid)
        pipeline["disabled_stages"] = sorted(disabled_set)

    @staticmethod
    def build_runtime_config_for_node(
        *,
        runtime_config: dict[str, object],
        stage_id: str,
        node: object | None,
        sanitize_params_for_plugin: Callable[[str, dict], dict[str, object]],
    ) -> dict[str, object] | None:
        sid = str(stage_id or "").strip()
        if not sid or node is None:
            return None
        tool = getattr(node, "tool", None)
        plugin_id = str(getattr(tool, "plugin_id", "") or "").strip()
        if not plugin_id:
            return None
        raw_params = getattr(node, "params", {})
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        params = sanitize_params_for_plugin(plugin_id, params)

        ArtifactLineageController.enable_stage_in_runtime_config(runtime_config, sid)
        stages = runtime_config.get("stages")
        if not isinstance(stages, dict):
            return None
        stage_cfg_raw = stages.get(sid)
        stage_cfg = dict(stage_cfg_raw) if isinstance(stage_cfg_raw, dict) else {}
        variants = stage_cfg.get("variants")
        if isinstance(variants, list):
            stage_cfg["variants"] = [
                {
                    "plugin_id": plugin_id,
                    "params": dict(params),
                    "enabled": True,
                }
            ]
            stage_cfg["plugin_id"] = plugin_id
            stage_cfg["params"] = dict(params)
        else:
            stage_cfg["plugin_id"] = plugin_id
            stage_cfg["params"] = dict(params)
        stages[sid] = stage_cfg
        return runtime_config
