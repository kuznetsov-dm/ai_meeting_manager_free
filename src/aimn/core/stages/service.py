from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aimn.core.contracts import KIND_INDEX, KIND_SUMMARY
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


class ServiceAdapter(PluginStageAdapter):
    def __init__(self, policy: StagePolicy, config: PluginsConfig) -> None:
        super().__init__(stage_id="service", policy=policy, config=config)

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
            plugin_id = self._config.plugin_id_for(self.stage_id)
        except Exception:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )
        stage_params = self._config.plugin_params_for(self.stage_id)
        public_params, run_params = self._resolve_plugin_params(context, plugin_id, stage_params)
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

        plugin_version = "unknown"
        if context.plugin_manager:
            manifest = context.plugin_manager.manifest_for(plugin_id)
            if manifest:
                plugin_version = manifest.version
        node_fp = compute_fingerprint(
            self.stage_id,
            plugin_id,
            plugin_version,
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

        execution = self._run_hook(context, "derive.after_summary", plugin_id, run_params)
        if execution is None:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )
        if execution.error:
            return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error=execution.error)
        if execution.result is None:
            return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error="empty_plugin_result")
        result = execution.result
        output = next((item for item in result.outputs if item.kind == KIND_INDEX), None)
        if not output:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error=f"service plugin produced no '{KIND_INDEX}' output",
            )

        store = FileMeetingStore(output_dir)
        writer = ArtifactWriter(
            output_dir,
            store,
            stage_id=self.stage_id,
            validator=self._validate_artifact_file,
            event_callback=context.event_callback,
        )
        alias = allocate_alias(
            context.meeting, self.stage_id, public_params, [parent_alias] if parent_alias else []
        )
        use_alias = alias
        index_output = output.__class__(
            kind=KIND_INDEX,
            content=output.content,
            content_type=output.content_type or "text",
            user_visible=False,
        )
        ext = "json" if str(index_output.content_type or "").strip().lower() == "json" else "txt"
        artifact, relpath, error = writer.write_output(
            context.meeting.base_name,
            use_alias,
            index_output,
            ext=ext,
        )
        if error:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error=f"{KIND_INDEX}_{error}:{relpath}",
            )
        artifacts = [
            artifact
            if artifact
            else ArtifactRef(kind=KIND_INDEX, path=relpath, content_type="text", user_visible=False)
        ]

        parent_aliases = [parent_alias] if parent_alias else []
        cacheable = self._parents_cacheable(context, parent_aliases) and not self._is_mock_fallback(result)
        register_lineage_node(
            manifest=context.meeting,
            alias=alias,
            stage_id=self.stage_id,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
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
