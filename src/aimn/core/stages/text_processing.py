from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from aimn.core.contracts import KIND_DEBUG_JSON, KIND_EDITED, KIND_TRANSCRIPT
from aimn.core.fingerprinting import compute_fingerprint
from aimn.core.lineage import apply_branching, find_node_by_fingerprint
from aimn.core.meeting_store import FileMeetingStore
from aimn.core.node_registry import allocate_alias, register_lineage_node
from aimn.core.pipeline import StageContext, StageEvent, StagePolicy, StageResult
from aimn.core.plugins_config import PluginsConfig
from aimn.core.stages.base import PluginStageAdapter
from aimn.core.services.artifact_writer import ArtifactWriter
from aimn.core.services.artifact_reader import ArtifactReader
from aimn.core.services.embeddings_availability import embeddings_available
from aimn.core.services.text_cleanup import cleanup_transcript
from aimn.domain.meeting import ArtifactRef, MeetingManifest


class TextProcessingAdapter(PluginStageAdapter):
    def __init__(self, policy: StagePolicy, config: PluginsConfig) -> None:
        super().__init__(stage_id="text_processing", policy=policy, config=config)

    def run(self, context: StageContext) -> StageResult:
        self._context = context
        if not context.meeting.transcript_relpath:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="missing_input",
            )
        if not context.output_dir:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error="output_dir missing for artifacts",
            )

        output_dir = Path(context.output_dir)
        reader = ArtifactReader(output_dir)
        transcript_input = reader.read_text_with_fingerprint(context.meeting.transcript_relpath)
        if transcript_input.fingerprint is None:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error=f"{KIND_TRANSCRIPT} not found: {context.meeting.transcript_relpath}",
            )

        variants = self._variants()
        stage_params = self._config.plugin_params_for(self.stage_id)
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
        transcript_fp = transcript_input.fingerprint
        parent_alias = self._find_parent_alias(context.meeting, context.meeting.transcript_relpath)
        parent_fps = [context.meeting.nodes[parent_alias].fingerprint] if parent_alias else []
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
            public_params, run_params = self._resolve_plugin_params(
                context, plugin_id, merged_params
            )
            public_params, run_params = self._apply_embeddings_fallback(
                context, plugin_id, public_params, run_params
            )
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
                parent_fps + [transcript_fp],
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
                if existing_alias:
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

            parent_aliases = [parent_alias] if parent_alias else []
            alias = allocate_alias(context.meeting, self.stage_id, public_params, parent_aliases)
            use_alias = alias if context.meeting.naming_mode == "branched" else None

            transcript_text = transcript_input.content or ""
            transcript_text = self._apply_cleanup(context, transcript_text)
            execution = self._run_hook(
                context,
                "postprocess.after_transcribe",
                plugin_id,
                run_params,
                input_text=transcript_text,
                alias=use_alias,
            )
            if execution is None:
                continue
            if execution.error:
                return StageResult(
                    stage_id=self.stage_id,
                    status="failed",
                    cache_hit=False,
                    error=execution.error,
                )
            result = execution.result
            if result is None:
                return StageResult(
                    stage_id=self.stage_id,
                    status="failed",
                    cache_hit=False,
                    error="empty_plugin_result",
                )
            if context.event_callback and result.warnings:
                for warning in result.warnings:
                    context.event_callback(
                        StageEvent(event_type="plugin_notice", stage_id=self.stage_id, message=warning)
                    )

            edited_output = next((output for output in result.outputs if output.kind == KIND_EDITED), None)
            if not edited_output:
                return StageResult(
                    stage_id=self.stage_id,
                    status="failed",
                    cache_hit=False,
                    error=f"text_processing plugin produced no '{KIND_EDITED}' output",
                )

            debug_output = next((output for output in result.outputs if output.kind == KIND_DEBUG_JSON), None)
            debug_export = bool(public_params.get("debug_export")) if public_params else False

            edited_content = edited_output.content
            if debug_export and debug_output:
                debug_payload = debug_output.content
                if debug_output.content_type != "json":
                    debug_payload = json.dumps({"debug": debug_output.content}, ensure_ascii=True)
                edited_content = (
                    f"{edited_content}\n\n---\n\nDebug (JSON):\n\n```json\n{debug_payload}\n```\n"
                )

            edited_output = edited_output.__class__(
                kind=KIND_EDITED,
                content=edited_content,
                content_type=edited_output.content_type or "text/markdown",
                user_visible=True,
            )
            artifact, relpath, error = writer.write_output(
                context.meeting.base_name,
                use_alias,
                edited_output,
                ext="md",
            )
            if error:
                return StageResult(
                    stage_id=self.stage_id,
                    status="failed",
                    cache_hit=False,
                    error=f"{KIND_EDITED}_{error}:{relpath}",
                )
            artifacts: list[ArtifactRef] = [
                artifact if artifact else ArtifactRef(kind=KIND_EDITED, path=relpath, content_type="text/markdown", user_visible=True)
            ]

            if debug_output:
                debug_output = debug_output.__class__(
                    kind=KIND_DEBUG_JSON,
                    content=debug_output.content,
                    content_type=debug_output.content_type or "json",
                    user_visible=False,
                )
                artifact, debug_relpath, error = writer.write_output(
                    context.meeting.base_name,
                    use_alias,
                    debug_output,
                    ext="json",
                )
                if error:
                    return StageResult(
                        stage_id=self.stage_id,
                        status="failed",
                        cache_hit=False,
                        error=f"{KIND_DEBUG_JSON}_{error}:{debug_relpath}",
                    )
                if artifact:
                    artifacts.append(artifact)

            cacheable = self._parents_cacheable(context, parent_aliases) and not self._is_mock_fallback(result)
            register_lineage_node(
                manifest=context.meeting,
                alias=alias,
                stage_id=self.stage_id,
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                params=public_params,
                parent_aliases=parent_aliases,
                source_fps=[transcript_fp],
                artifacts=artifacts,
                created_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                cacheable=cacheable,
            )
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

    def _apply_embeddings_fallback(
        self,
        context: StageContext,
        plugin_id: str,
        public_params: dict,
        run_params: dict,
    ) -> tuple[dict, dict]:
        updated_public = dict(public_params)
        updated_run = dict(run_params)

        model_id = self._resolve_embeddings_model_id(updated_run, updated_public)
        model_path = str(
            updated_run.get("embeddings_model_path", "")
            or updated_public.get("embeddings_model_path", "")
            or ""
        ).strip() or None
        if not model_id and not model_path:
            return updated_public, updated_run

        if model_id:
            updated_public["embeddings_model_id"] = model_id
            updated_run["embeddings_model_id"] = model_id
        allow_download = _coerce_bool(
            updated_run.get("embeddings_allow_download", updated_run.get("allow_download", False))
        ) or _coerce_bool(
            updated_public.get("embeddings_allow_download", updated_public.get("allow_download", False))
        )
        if getattr(sys, "frozen", False):
            allow_download = False

        updated_public["embeddings_enabled"] = True
        updated_run["embeddings_enabled"] = True
        updated_public["embeddings_allow_download"] = allow_download
        updated_run["embeddings_allow_download"] = allow_download
        updated_public["allow_download"] = allow_download
        updated_run["allow_download"] = allow_download

        available = embeddings_available(model_id, model_path)
        if context.event_callback:
            tag = model_id or ("custom_path" if model_path else "embeddings")
            if available:
                message = f"Embeddings ready: {tag}"
            elif allow_download:
                message = f"Downloading embeddings model {tag} for semantic processing."
            else:
                message = f"Embeddings model {tag} is not bundled. Continuing with heuristic processing."
            context.event_callback(
                StageEvent(
                    event_type="plugin_notice",
                    stage_id=self.stage_id,
                    message=message,
                )
            )
        return updated_public, updated_run

    @staticmethod
    def _resolve_embeddings_model_id(run_params: dict, public_params: dict) -> str | None:
        explicit = str(
            run_params.get("embeddings_model_id", "")
            or public_params.get("embeddings_model_id", "")
            or run_params.get("model_id", "")
            or public_params.get("model_id", "")
            or ""
        ).strip()
        if explicit:
            return explicit
        rows = public_params.get("models")
        if not isinstance(rows, list):
            return None
        preferred = TextProcessingAdapter._preferred_embeddings_model_row(rows)
        if not preferred:
            return None
        return str(preferred.get("model_id", "") or "").strip() or None

    @staticmethod
    def _preferred_embeddings_model_row(rows: list[object]) -> dict | None:
        best_row: dict | None = None
        best_score: tuple[int, int, int] | None = None
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id", "") or "").strip()
            if not model_id:
                continue
            score = (
                1 if _coerce_bool(item.get("favorite", False)) else 0,
                1 if _coerce_bool(item.get("enabled", False)) else 0,
                -index,
            )
            if best_score is None or score > best_score:
                best_score = score
                best_row = item
        return dict(best_row) if isinstance(best_row, dict) else None

    def _apply_cleanup(self, context: StageContext, transcript_text: str) -> str:
        if not transcript_text:
            return transcript_text
        stage_params = self._config.plugin_params_for(self.stage_id)
        cleanup_enabled = _coerce_bool(stage_params.get("cleanup_pre_edit", True))
        if not cleanup_enabled:
            return transcript_text
        cleaned, stats = cleanup_transcript(transcript_text)
        if cleaned == transcript_text:
            return transcript_text
        if context.event_callback:
            context.event_callback(
                StageEvent(
                    event_type="plugin_notice",
                    stage_id=self.stage_id,
                    message=(
                        "pre_edit_cleanup_applied"
                        f":lines={stats['lines_removed']}"
                        f":sentences={stats['sentences_removed']}"
                        f":blanks={stats['blank_lines_removed']}"
                    ),
                )
            )
        return cleaned

    @staticmethod
    def _find_parent_alias(manifest: MeetingManifest, transcript_relpath: str | None) -> str | None:
        if not transcript_relpath:
            return None
        for alias, node in manifest.nodes.items():
            if node.stage_id != "transcription":
                continue
            for artifact in node.artifacts:
                if artifact.kind == KIND_TRANSCRIPT and artifact.path == transcript_relpath:
                    return alias
        return None


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)
