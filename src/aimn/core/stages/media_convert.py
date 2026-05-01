from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aimn.core.contracts import KIND_AUDIO
from aimn.core.fingerprinting import compute_fingerprint, compute_source_fingerprint
from aimn.core.lineage import apply_branching, find_node_by_fingerprint
from aimn.core.meeting_store import FileMeetingStore
from aimn.core.media_conversion import convert_to_wav, is_supported_media
from aimn.core.node_registry import allocate_alias, register_lineage_node
from aimn.core.plugins_config import PluginsConfig
from aimn.core.pipeline import StageAdapter, StageContext, StageEvent, StagePolicy, StageResult
from aimn.core.stages.base import PluginStageAdapter
from aimn.domain.meeting import ArtifactRef


class MediaConvertAdapter(StageAdapter):
    def __init__(self, policy: StagePolicy, config: PluginsConfig) -> None:
        super().__init__(stage_id="media_convert", policy=policy)
        self._config = config

    def run(self, context: StageContext) -> StageResult:
        if not context.meeting.source.items:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="missing_input",
            )

        output_dir = context.output_dir
        if not output_dir:
            return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error="output_dir missing")
        output_root = Path(output_dir)
        store = FileMeetingStore(output_root)

        source = context.meeting.source.items[0]
        if not source.content_fingerprint:
            source.content_fingerprint = compute_source_fingerprint(source.input_path)

        input_path = Path(source.input_path)
        if not is_supported_media(input_path):
            return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error="unsupported media")

        plugin_id = f"core.{self.stage_id}"
        plugin_version = "1.0"
        stage_params = self._config.plugin_params_for(self.stage_id)
        channels = int(stage_params.get("channels", 1) or 1)
        sample_rate_hz = int(stage_params.get("sample_rate_hz", 16000) or 16000)
        normalize = _coerce_bool(stage_params.get("normalize", False))
        params = {
            "channels": channels,
            "sample_rate_hz": sample_rate_hz,
            "normalize": normalize,
        }
        source_fps = [source.content_fingerprint]
        node_fp = compute_fingerprint(
            self.stage_id,
            plugin_id,
            plugin_version,
            params,
            source_fps,
        )

        apply_branching(
            context.meeting,
            self.stage_id,
            node_fp,
            output_dir=output_root,
            store=store,
        )

        if not context.force_run:
            existing_alias = find_node_by_fingerprint(context.meeting, node_fp)
            if existing_alias and PluginStageAdapter._node_artifacts_exist(
                context.meeting,
                alias=existing_alias,
                output_dir=output_root,
                required_kinds={KIND_AUDIO},
            ):
                node = context.meeting.nodes[existing_alias]
                for artifact in node.artifacts:
                    if artifact.kind == KIND_AUDIO:
                        context.meeting.audio_relpath = artifact.path
                if context.event_callback:
                    context.event_callback(
                        StageEvent(
                            event_type="cache_hit",
                            stage_id=self.stage_id,
                            message=f"{existing_alias}",
                        )
                    )
                return StageResult(stage_id=self.stage_id, status="success", cache_hit=True)

        alias = allocate_alias(context.meeting, self.stage_id, params, [])
        use_alias = alias if context.meeting.naming_mode == "branched" else None
        relpath = store.resolve_artifact_path(context.meeting.base_name, use_alias, KIND_AUDIO, "wav")
        output_path = output_root / relpath
        convert_to_wav(
            input_path,
            output_path,
            context.ffmpeg_path,
            channels=channels,
            sample_rate_hz=sample_rate_hz,
            normalize=normalize,
        )
        context.meeting.audio_relpath = relpath

        artifacts = [
            ArtifactRef(
                kind=KIND_AUDIO,
                path=relpath,
                content_type="audio/wav",
                user_visible=False,
            )
        ]

        if context.event_callback:
            context.event_callback(
                StageEvent(
                    event_type="artifact_written",
                    stage_id=self.stage_id,
                    message=relpath,
                    alias=use_alias,
                    kind=KIND_AUDIO,
                    relpath=relpath,
                )
            )

        register_lineage_node(
            manifest=context.meeting,
            alias=alias,
            stage_id=self.stage_id,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            params=params,
            parent_aliases=[],
            source_fps=source_fps,
            artifacts=artifacts,
            created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )

        return StageResult(stage_id=self.stage_id, status="success", cache_hit=False)


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)
