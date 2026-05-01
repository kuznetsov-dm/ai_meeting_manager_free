from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aimn.core.contracts import (
    KIND_ASR_SEGMENTS_JSON,
    KIND_SEGMENTS,
    KIND_TRANSCRIPT,
)
from aimn.core.fingerprinting import compute_fingerprint, compute_source_fingerprint
from aimn.core.lineage import apply_branching, find_node_by_fingerprint
from aimn.core.meeting_store import FileMeetingStore
from aimn.core.node_registry import allocate_alias, register_lineage_node
from aimn.core.pipeline import StageContext, StageEvent, StagePolicy, StageResult
from aimn.core.plugins_config import PluginsConfig
from aimn.core.services.artifact_writer import ArtifactWriter
from aimn.core.services.transcription_artifacts import persist_transcription_outputs
from aimn.core.stages.base import PluginStageAdapter


class TranscriptionAdapter(PluginStageAdapter):
    def __init__(self, policy: StagePolicy, config: PluginsConfig) -> None:
        super().__init__(stage_id="transcription", policy=policy, config=config)

    @classmethod
    def _stable_fingerprint_params(cls, params: dict) -> dict:
        normalized = dict(super()._stable_fingerprint_params(params))
        model_value = str(normalized.get("model", "") or "").strip()
        model_id_value = str(normalized.get("model_id", "") or "").strip()
        if not model_value and model_id_value:
            normalized["model"] = model_id_value
        normalized.pop("model_id", None)
        return normalized

    def run(self, context: StageContext) -> StageResult:
        self._context = context
        if not context.meeting.source.items:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="missing_input",
            )

        source = context.meeting.source.items[0]
        if not source.content_fingerprint:
            source.content_fingerprint = compute_source_fingerprint(source.input_path)

        input_path = Path(source.input_path)
        output_dir = Path(context.output_dir) if context.output_dir else None
        audio_relpath = getattr(context.meeting, "audio_relpath", None)

        if output_dir and audio_relpath:
            converted_audio_path = output_dir / audio_relpath
            if converted_audio_path.exists():
                input_path = converted_audio_path
            else:
                return StageResult(
                    stage_id=self.stage_id,
                    status="failed",
                    cache_hit=False,
                    error=f"missing_dependency:media_convert_artifact_not_found:{audio_relpath}",
                )

        stage_params = self._config.plugin_params_for(self.stage_id)
        variants = self._variants()
        if not variants:
            try:
                plugin_id = self._config.plugin_id_for(self.stage_id)
            except Exception:
                return StageResult(
                    stage_id=self.stage_id,
                    status="skipped",
                    cache_hit=False,
                    skip_reason="no_plugin",
                )
            variants = [(plugin_id, stage_params)]
        if not output_dir:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error="output_dir missing for artifacts",
            )

        source_fps = [source.content_fingerprint]
        store = FileMeetingStore(output_dir)
        writer = ArtifactWriter(
            output_dir,
            store,
            stage_id=self.stage_id,
            validator=self._validate_artifact_file,
            event_callback=context.event_callback,
        )
        force_branch = len(variants) > 1
        cache_hits: list[bool] = []
        wrote_any = False

        for plugin_id, plugin_params in variants:
            merged_params = dict(stage_params)
            if isinstance(plugin_params, dict):
                merged_params.update(plugin_params)
            public_params, run_params = self._resolve_plugin_params(context, plugin_id, merged_params)
            fingerprint_params = self._stable_fingerprint_params(public_params)

            plugin_version = "unknown"
            if context.plugin_manager:
                manifest = context.plugin_manager.manifest_for(plugin_id)
                if manifest:
                    plugin_version = manifest.version
            node_fp = compute_fingerprint(
                self.stage_id,
                plugin_id,
                plugin_version,
                fingerprint_params,
                source_fps,
            )
            legacy_node_fp = compute_fingerprint(
                self.stage_id,
                plugin_id,
                plugin_version,
                public_params,
                source_fps,
            )

            apply_branching(
                context.meeting,
                self.stage_id,
                node_fp,
                force_branch=force_branch,
                output_dir=output_dir,
                store=store,
            )

            if not context.force_run:
                existing_alias = find_node_by_fingerprint(context.meeting, node_fp)
                if not existing_alias and legacy_node_fp != node_fp:
                    existing_alias = find_node_by_fingerprint(context.meeting, legacy_node_fp)
                if not existing_alias:
                    existing_alias = self._find_cacheable_node_by_stable_params(
                        context.meeting,
                        stage_id=self.stage_id,
                        plugin_id=plugin_id,
                        plugin_version=plugin_version,
                        stable_params=public_params,
                        source_fps=source_fps,
                    )
                if existing_alias and self._node_artifacts_exist(
                    context.meeting,
                    alias=existing_alias,
                    output_dir=output_dir,
                    required_kinds={KIND_TRANSCRIPT},
                ):
                    node = context.meeting.nodes[existing_alias]
                    for artifact in node.artifacts:
                        if artifact.kind == KIND_TRANSCRIPT:
                            context.meeting.transcript_relpath = artifact.path
                        if artifact.kind == KIND_SEGMENTS:
                            context.meeting.segments_relpath = artifact.path
                    self._set_active_transcription_alias(context, existing_alias)
                    if context.event_callback:
                        context.event_callback(
                            StageEvent(
                                event_type="cache_hit",
                                stage_id=self.stage_id,
                                message=f"{existing_alias}",
                            )
                        )
                    cache_hits.append(True)
                    continue

            alias = allocate_alias(context.meeting, self.stage_id, fingerprint_params, [])
            use_alias = alias if context.meeting.naming_mode == "branched" else None
            execution = self._run_hook(
                context,
                "transcribe.run",
                plugin_id,
                run_params,
                input_media_path=str(input_path),
                alias=use_alias,
            )
            if execution is None:
                continue
            if execution.error:
                return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error=execution.error)
            result = execution.result
            if result is None:
                return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error="empty_plugin_result")

            persist_result, persist_error = persist_transcription_outputs(
                base_name=context.meeting.base_name,
                alias=use_alias,
                outputs=result.outputs,
                writer=writer,
            )
            if persist_error:
                kind, relpath, error = persist_error
                return StageResult(
                    stage_id=self.stage_id,
                    status="failed",
                    cache_hit=False,
                    error=f"{kind}_{error}:{relpath}",
                )
            artifacts = persist_result.artifacts if persist_result else []
            # Never register raw Whisper ASR debug artifacts in lineage.
            if artifacts:
                artifacts = [
                    a
                    for a in artifacts
                    if a.kind not in {KIND_ASR_SEGMENTS_JSON, "asr_diagnostics_json"}
                ]
            if persist_result:
                if persist_result.transcript_relpath:
                    context.meeting.transcript_relpath = persist_result.transcript_relpath
                if persist_result.segments_relpath:
                    context.meeting.segments_relpath = persist_result.segments_relpath
                if persist_result.segments_index:
                    context.meeting.segments_index = persist_result.segments_index

            cacheable = self._parents_cacheable(context, []) and not self._is_mock_fallback(result)
            register_lineage_node(
                manifest=context.meeting,
                alias=alias,
                stage_id=self.stage_id,
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                params=fingerprint_params,
                parent_aliases=[],
                source_fps=source_fps,
                artifacts=artifacts,
                created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                cacheable=cacheable,
            )
            try:
                self._set_active_transcription_alias(context, alias)
            except Exception:
                pass
            detected_language = persist_result.detected_language if persist_result else None
            if detected_language:
                meta = getattr(context.meeting, "transcription_meta", None)
                if not isinstance(meta, dict):
                    meta = {}
                meta["detected_language"] = detected_language
                setattr(context.meeting, "transcription_meta", meta)

            wrote_any = True
            cache_hits.append(False)

        if not wrote_any and cache_hits:
            return StageResult(stage_id=self.stage_id, status="success", cache_hit=all(cache_hits))
        if not wrote_any and not cache_hits:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )
        return StageResult(stage_id=self.stage_id, status="success", cache_hit=False)

    def _variants(self) -> list[tuple[str, dict]]:
        variants = self._config.variants_for_stage(self.stage_id)
        resolved: list[tuple[str, dict]] = []
        for variant in variants:
            plugin_id = variant.get("plugin_id")
            if not plugin_id:
                continue
            params = variant.get("params", {})
            if not isinstance(params, dict):
                params = {}
            resolved.append((str(plugin_id), params))
        return resolved

    @staticmethod
    def _set_active_transcription_alias(context: StageContext, alias: str) -> None:
        active = getattr(context.meeting, "active_aliases", None)
        if not isinstance(active, dict):
            active = {}
        active["transcription"] = str(alias or "").strip()
        context.meeting.active_aliases = active
