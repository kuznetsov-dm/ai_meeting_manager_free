from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aimn.core.contracts import KIND_SUMMARY
from aimn.core.fingerprinting import compute_fingerprint
from aimn.core.lineage import find_node_by_fingerprint
from aimn.core.meeting_store import FileMeetingStore
from aimn.core.node_registry import allocate_alias, register_lineage_node
from aimn.core.plugins_config import PluginsConfig
from aimn.core.pipeline import StageContext, StageEvent, StagePolicy, StageResult
from aimn.core.stages.base import PluginStageAdapter
from aimn.core.services.artifact_writer import ArtifactWriter
from aimn.core.services.artifact_reader import ArtifactReader
from aimn.domain.meeting import ArtifactRef, MeetingManifest


class ManagementAdapter(PluginStageAdapter):
    def __init__(self, policy: StagePolicy, config: PluginsConfig) -> None:
        super().__init__(stage_id="management", policy=policy, config=config)

    def run(self, context: StageContext) -> StageResult:
        self._context = context
        if not context.output_dir:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error="output_dir missing for artifacts",
            )
        try:
            plugin_ids = self._config.plugin_ids_for(self.stage_id)
        except Exception:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )
        if not plugin_ids:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )
        stage_params = self._config.plugin_params_for(self.stage_id)
        summary_item = self._latest_summary_item(context.meeting)
        if not summary_item:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="missing_input",
            )
        parent_alias, summary_relpath = summary_item
        output_dir = Path(context.output_dir)
        reader = ArtifactReader(output_dir)
        summary_input = reader.fingerprint(summary_relpath)
        if summary_input.fingerprint is None:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error=f"{KIND_SUMMARY} not found: {summary_relpath}",
            )
        summary_fp = summary_input.fingerprint
        parent_fps = [context.meeting.nodes[parent_alias].fingerprint] if parent_alias else []

        # Filter plugin ids to those that are actually available (enabled + loaded).
        effective_plugin_ids: list[str] = []
        plugin_versions: dict[str, str] = {}
        plugin_public_params: dict[str, dict] = {}
        plugin_run_params: dict[str, dict] = {}
        for pid in plugin_ids:
            if not context.plugin_manager:
                continue
            manifest = context.plugin_manager.manifest_for(pid)
            if not manifest:
                continue
            public_params, run_params = self._resolve_plugin_params(context, pid, stage_params)
            effective_plugin_ids.append(pid)
            plugin_versions[pid] = manifest.version
            plugin_public_params[pid] = public_params
            plugin_run_params[pid] = run_params

        if not effective_plugin_ids:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )

        if len(effective_plugin_ids) == 1:
            plugin_id = effective_plugin_ids[0]
            plugin_version = plugin_versions.get(plugin_id, "unknown")
            public_params = plugin_public_params.get(plugin_id, {})
            node_fp = compute_fingerprint(
                self.stage_id,
                plugin_id,
                plugin_version,
                public_params,
                parent_fps + [summary_fp],
            )
        else:
            joined_id = "+".join(effective_plugin_ids)
            joined_version = "+".join([plugin_versions.get(pid, "unknown") for pid in effective_plugin_ids])
            public_params = {"plugins": dict(plugin_public_params)}
            node_fp = compute_fingerprint(
                self.stage_id,
                joined_id,
                joined_version,
                public_params,
                parent_fps + [summary_fp],
            )

        if not context.force_run:
            existing_alias = find_node_by_fingerprint(context.meeting, node_fp)
            if existing_alias:
                if context.event_callback:
                    context.event_callback(
                        StageEvent(
                            event_type="cache_hit",
                            stage_id=self.stage_id,
                            message=f"{existing_alias}",
                        )
                    )
                return StageResult(stage_id=self.stage_id, status="success", cache_hit=True)

        outputs_by_kind = {}
        warnings: list[str] = []
        any_success = False
        for pid in effective_plugin_ids:
            execution = self._run_hook(context, "derive.after_summary", pid, plugin_run_params.get(pid, {}))
            if execution is None:
                continue
            if execution.error:
                if execution.mode == "required":
                    return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error=execution.error)
                warnings.append(f"plugin_failed:{pid}:{execution.error}")
                continue
            if execution.result is None:
                warnings.append(f"empty_plugin_result:{pid}")
                continue
            any_success = True
            for item in execution.result.outputs:
                if item.kind in outputs_by_kind:
                    warnings.append(f"duplicate_output_kind:{item.kind}")
                    continue
                outputs_by_kind[item.kind] = item
            for warning in execution.result.warnings:
                if warning:
                    warnings.append(str(warning))

        if not any_success:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_outputs",
            )

        alias = allocate_alias(
            context.meeting, self.stage_id, public_params, [parent_alias] if parent_alias else []
        )
        use_alias = alias
        artifacts: list[ArtifactRef] = []
        if outputs_by_kind:
            store = FileMeetingStore(output_dir)
            writer = ArtifactWriter(
                output_dir,
                store,
                stage_id=self.stage_id,
                validator=self._validate_artifact_file,
                event_callback=context.event_callback,
            )
            for kind, output in outputs_by_kind.items():
                artifact, relpath, error = writer.write_output(
                    context.meeting.base_name,
                    use_alias,
                    output,
                    meta={"producer": "management", "warnings": list(warnings)[:10]} if warnings else {},
                )
                if error:
                    return StageResult(
                        stage_id=self.stage_id,
                        status="failed",
                        cache_hit=False,
                        error=f"{kind}_{error}:{relpath}",
                    )
                if artifact:
                    artifacts.append(artifact)
        elif context.event_callback:
            context.event_callback(
                StageEvent(
                    event_type="plugin_notice",
                    stage_id=self.stage_id,
                    message="management_side_effects_only",
                    alias=use_alias,
                )
            )
        if warnings and context.event_callback:
            context.event_callback(
                StageEvent(
                    event_type="warning",
                    stage_id=self.stage_id,
                    message=";".join(warnings[:10]),
                    alias=use_alias,
                )
            )

        parent_aliases = [parent_alias] if parent_alias else []
        cacheable = self._parents_cacheable(context, parent_aliases) and not any(
            str(w).strip() in {"mock_fallback", "mock_output"} for w in warnings
        )
        register_lineage_node(
            manifest=context.meeting,
            alias=alias,
            stage_id=self.stage_id,
            plugin_id=(effective_plugin_ids[0] if len(effective_plugin_ids) == 1 else "+".join(effective_plugin_ids)),
            plugin_version=(
                plugin_versions.get(effective_plugin_ids[0], "unknown")
                if len(effective_plugin_ids) == 1
                else "+".join([plugin_versions.get(pid, "unknown") for pid in effective_plugin_ids])
            ),
            params=public_params,
            parent_aliases=parent_aliases,
            source_fps=[summary_fp],
            artifacts=artifacts,
            created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            cacheable=cacheable,
        )

        return StageResult(stage_id=self.stage_id, status="success", cache_hit=False)

    @staticmethod
    def _latest_summary_item(manifest: MeetingManifest) -> tuple[str | None, str] | None:
        pinned = getattr(manifest, "pinned_aliases", None)
        if isinstance(pinned, dict):
            pinned_alias = str(pinned.get("llm_processing", "") or "").strip()
            if pinned_alias and pinned_alias in manifest.nodes:
                node = manifest.nodes.get(pinned_alias)
                if node and node.stage_id == "llm_processing":
                    for artifact in node.artifacts:
                        if artifact.kind == KIND_SUMMARY:
                            return pinned_alias, artifact.path

        latest_node = None
        latest_alias = None
        for alias, node in manifest.nodes.items():
            if node.stage_id != "llm_processing":
                continue
            for artifact in node.artifacts:
                if artifact.kind != KIND_SUMMARY:
                    continue
                if latest_node is None or (node.created_at or "") > (latest_node.created_at or ""):
                    latest_node = node
                    latest_alias = alias
        if not latest_node or latest_alias is None:
            return None
        for artifact in latest_node.artifacts:
            if artifact.kind == KIND_SUMMARY:
                return latest_alias, artifact.path
        return None
