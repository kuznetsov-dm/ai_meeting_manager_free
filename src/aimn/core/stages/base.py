from __future__ import annotations

from pathlib import Path
from typing import Optional

from aimn.core.contracts import Artifact, ArtifactMeta, HookContext, PluginResult, StageEvent
from aimn.domain.meeting import MeetingManifest
from aimn.core.hook_runner import run_hook_subprocess
from aimn.core.pipeline import StageAdapter, StageContext, StageResult
from aimn.core.plugins_config import PluginsConfig


def _looks_like_secret_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if not lowered:
        return False
    if lowered in {
        "key",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
    }:
        return True
    if lowered.startswith("api_key_") or lowered.endswith("_api_key") or lowered.endswith("apikey"):
        return True
    if lowered.endswith("_token") or lowered.endswith("_secret") or lowered.endswith("_password"):
        return True
    if lowered.endswith("_key") or lowered.endswith("_keys"):
        return True
    return lowered.startswith("key_")


class PluginStageAdapter(StageAdapter):
    def __init__(self, stage_id: str, policy, config: PluginsConfig) -> None:
        super().__init__(stage_id=stage_id, policy=policy)
        self._config = config
        self._context: StageContext | None = None

    def _resolve_plugin_params(
        self, context: StageContext, plugin_id: str, stage_params: dict
    ) -> tuple[dict, dict]:
        if not context.plugin_manager:
            return stage_params, stage_params
        public_settings = context.plugin_manager.get_settings(plugin_id, include_secrets=False)
        secret_settings = context.plugin_manager.get_settings_with_secrets(plugin_id)
        plugin_config_params = self._config.plugin_params_for_id(plugin_id)
        stage_params = stage_params or {}
        merged_public = dict(public_settings)
        merged_secret = dict(secret_settings)
        self._apply_runtime_params(merged_public, merged_secret, plugin_config_params)
        self._apply_runtime_params(merged_public, merged_secret, stage_params)
        return merged_public, merged_secret

    @staticmethod
    def _node_artifacts_exist(
        manifest: MeetingManifest,
        *,
        alias: str,
        output_dir: Path | str | None,
        required_kinds: set[str] | None = None,
    ) -> bool:
        if not output_dir:
            return False
        node = manifest.nodes.get(str(alias or "").strip())
        if not node:
            return False
        wanted = set(required_kinds or set())
        artifacts = list(getattr(node, "artifacts", []) or [])
        if wanted:
            artifacts = [artifact for artifact in artifacts if str(getattr(artifact, "kind", "") or "") in wanted]
        if not artifacts:
            return False
        root = Path(output_dir)
        for artifact in artifacts:
            relpath = str(getattr(artifact, "path", "") or "").strip()
            if not relpath:
                return False
            if not (root / relpath).is_file():
                return False
        return True

    @staticmethod
    def _stable_fingerprint_params(params: dict) -> dict:
        if not isinstance(params, dict):
            return {}
        volatile_top_level = {
            "models",
            "_models_catalog_meta",
            "options",
            "hidden_model_ids",
            "hidden_model_files",
        }
        return {
            str(key): PluginStageAdapter._strip_volatile_runtime_state(value)
            for key, value in params.items()
            if str(key or "").strip() not in volatile_top_level
        }

    @staticmethod
    def _strip_volatile_runtime_state(value: object) -> object:
        volatile_nested = {
            "last_ok_at",
            "last_failure_at",
            "last_failure_code",
            "last_pipeline_at",
            "last_pipeline_quality",
            "pipeline_failure_streak",
            "failure_code",
            "cooldown_until",
            "status",
            "availability_status",
            "selectable",
            "blocked_for_account",
            "favorite",
            "observed_success",
            "download_job_active",
            "installed",
        }
        if isinstance(value, dict):
            sanitized: dict[str, object] = {}
            for key, nested in value.items():
                marker = str(key or "").strip()
                if marker in volatile_nested:
                    continue
                sanitized[marker] = PluginStageAdapter._strip_volatile_runtime_state(nested)
            return sanitized
        if isinstance(value, list):
            return [PluginStageAdapter._strip_volatile_runtime_state(item) for item in value]
        return value

    @classmethod
    def _find_cacheable_node_by_stable_params(
        cls,
        manifest: MeetingManifest,
        *,
        stage_id: str,
        plugin_id: str,
        plugin_version: str,
        stable_params: dict,
        source_fps: list[str],
        parent_fps: list[str] | None = None,
    ) -> str | None:
        wanted_params = cls._stable_fingerprint_params(stable_params)
        wanted_sources = [str(item or "").strip() for item in (source_fps or []) if str(item or "").strip()]
        wanted_parents = [str(item or "").strip() for item in (parent_fps or []) if str(item or "").strip()]
        for alias, node in manifest.nodes.items():
            if not bool(getattr(node, "cacheable", True)):
                continue
            if str(getattr(node, "stage_id", "") or "").strip() != str(stage_id or "").strip():
                continue
            tool = getattr(node, "tool", None)
            node_plugin_id = str(getattr(tool, "plugin_id", "") or "").strip()
            node_plugin_version = str(getattr(tool, "version", "") or "").strip()
            if node_plugin_id != str(plugin_id or "").strip():
                continue
            if node_plugin_version != str(plugin_version or "").strip():
                continue
            inputs = getattr(node, "inputs", None)
            node_sources = [str(item or "").strip() for item in (getattr(inputs, "source_ids", None) or []) if str(item or "").strip()]
            if node_sources != wanted_sources:
                continue
            node_parent_aliases = [str(item or "").strip() for item in (getattr(inputs, "parent_nodes", None) or []) if str(item or "").strip()]
            node_parent_fps: list[str] = []
            for parent_alias in node_parent_aliases:
                parent_node = manifest.nodes.get(parent_alias)
                if not parent_node:
                    node_parent_fps = []
                    break
                node_parent_fps.append(str(getattr(parent_node, "fingerprint", "") or "").strip())
            if wanted_parents and node_parent_fps != wanted_parents:
                continue
            node_params = cls._stable_fingerprint_params(getattr(node, "params", {}) or {})
            if node_params != wanted_params:
                continue
            return alias
        return None

    @staticmethod
    def _apply_runtime_params(
        merged_public: dict,
        merged_secret: dict,
        params: dict,
    ) -> None:
        if not isinstance(params, dict):
            return
        merged_public.update(params)
        # Do not let empty/None stage params shadow secrets (common after UI experiments where
        # secret fields were serialized as empty strings into pipeline presets).
        for key, value in params.items():
            if _looks_like_secret_key(key):
                if value is None or str(value).strip() == "":
                    continue
            merged_secret[key] = value

    def _run_hook(
        self,
        context: StageContext,
        connector: str,
        plugin_id: str,
        plugin_params: dict,
        *,
        input_text: str | None = None,
        input_media_path: str | None = None,
        alias: str | None = None,
    ):
        if not context.plugin_manager:
            raise ValueError("plugin_manager not configured")
        if not context.plugin_manager.manifest_for(plugin_id):
            return None
        if context.plugin_manager.should_isolate_hook(plugin_id):
            artifacts: list[dict] = []
            latest: dict[str, dict] = {}
            for node in context.meeting.nodes.values():
                created_at = str(node.created_at or "")
                for artifact in node.artifacts:
                    meta = {
                        "kind": artifact.kind,
                        "path": artifact.path,
                        "content_type": artifact.content_type,
                        "user_visible": artifact.user_visible,
                        "created_at": created_at,
                    }
                    artifacts.append(meta)
                    prev = latest.get(artifact.kind)
                    if not prev or created_at > str(prev.get("created_at", "")):
                        latest[artifact.kind] = meta
            payload = {
                "meeting_id": context.meeting.meeting_id,
                "alias": alias,
                "input_text": input_text,
                "input_media_path": input_media_path,
                "force_run": context.force_run,
                "plugin_config": plugin_params,
                "output_dir": context.output_dir,
                "storage_dir": str(context.plugin_manager.get_storage_path(plugin_id)),
                "artifacts": artifacts,
                "latest_artifacts": latest,
            }
            repo_root = Path(context.plugin_manager._repo_root)
            return run_hook_subprocess(repo_root, plugin_id, connector, payload)
        hook_ctx = HookContext(
            plugin_id=plugin_id,
            meeting_id=context.meeting.meeting_id,
            alias=alias,
            input_text=input_text,
            input_media_path=input_media_path,
            force_run=context.force_run,
            progress_callback=context.progress_callback,
            cancel_requested=context.cancel_requested,
            plugin_config=plugin_params,
            _output_dir=context.output_dir,
            _storage_dir=str(context.plugin_manager.get_storage_path(plugin_id)),
            _get_artifact=lambda kind: self._get_artifact(context, kind),
            _list_artifacts=lambda: self._list_artifacts(context),
            _get_secret=lambda key: context.plugin_manager.get_secret(plugin_id, key),
            _resolve_service=context.plugin_manager.get_service,
            _notice_callback=(
                (lambda message: context.event_callback(StageEvent(
                    event_type="plugin_notice",
                    stage_id=self.stage_id,
                    message=str(message or "").strip(),
                )))
                if context.event_callback
                else None
            ),
            _schema_resolver=(
                context.plugin_manager.artifact_schema if context.plugin_manager else None
            ),
        )
        results = context.plugin_manager.execute_connector(
            connector, hook_ctx, allowed_plugin_ids=[plugin_id]
        )
        if not results:
            return None
        return results[0]

    @staticmethod
    def _list_artifacts(context: StageContext) -> list[ArtifactMeta]:
        metas: list[ArtifactMeta] = []
        for node in context.meeting.nodes.values():
            for artifact in node.artifacts:
                metas.append(
                    ArtifactMeta(
                        kind=artifact.kind,
                        path=artifact.path,
                        content_type=artifact.content_type,
                        user_visible=artifact.user_visible,
                    )
                )
        return metas

    @staticmethod
    def _get_artifact(context: StageContext, kind: str) -> Artifact | None:
        if not context.output_dir:
            return None
        active_aliases = getattr(context.meeting, "active_aliases", {}) or {}
        active_alias = {
            str(alias or "").strip()
            for alias in active_aliases.values()
            if str(alias or "").strip()
        }
        latest_node = None
        latest_artifact = None
        active_node = None
        active_artifact = None
        for alias, node in context.meeting.nodes.items():
            node_alias = str(alias or "").strip()
            for artifact in node.artifacts:
                if artifact.kind != kind:
                    continue
                if node_alias and node_alias in active_alias:
                    if active_node is None or (node.created_at or "") > (active_node.created_at or ""):
                        active_node = node
                        active_artifact = artifact
                if latest_node is None or (node.created_at or "") > (latest_node.created_at or ""):
                    latest_node = node
                    latest_artifact = artifact
        if active_artifact:
            latest_artifact = active_artifact
        if not latest_artifact:
            return None
        path = Path(context.output_dir) / latest_artifact.path
        if not path.exists():
            return None
        content = ""
        content_type = latest_artifact.content_type or ""
        if content_type.startswith("text") or content_type.endswith("json"):
            content = path.read_text(encoding="utf-8", errors="ignore")
        meta = ArtifactMeta(
            kind=latest_artifact.kind,
            path=latest_artifact.path,
            content_type=latest_artifact.content_type,
            user_visible=latest_artifact.user_visible,
        )
        return Artifact(meta=meta, content=content)

    def _validate_artifact_file(
        self, output_dir: Path, relpath: str, kind: str | None = None
    ) -> Optional[str]:
        root = output_dir.resolve()
        path = (output_dir / relpath).resolve()
        if not path.is_relative_to(root):
            return "artifact_path_outside_output_dir"
        if not path.exists():
            return "artifact_missing"
        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            return "artifact_empty"
        if kind and self._context and self._context.plugin_manager:
            schema = self._context.plugin_manager.artifact_schema(kind)
            if schema:
                expected = schema.allowed_extensions or self._default_extensions(schema.content_type)
                if expected:
                    ext = path.suffix.lstrip(".").lower()
                    if ext not in expected:
                        return "artifact_extension_invalid"
                if schema.max_size_bytes is not None and size_bytes > schema.max_size_bytes:
                    return "artifact_too_large"
        return None

    @staticmethod
    def _default_extensions(content_type: str) -> list[str] | None:
        ct = (content_type or "").lower()
        if ct == "text/markdown":
            return ["md"]
        if ct == "text" or ct.startswith("text/"):
            return ["txt"]
        if ct.endswith("json") or ct == "json" or ct == "application/json":
            return ["json"]
        if ct == "audio/wav" or ct.endswith("/wav"):
            return ["wav"]
        return None

    @staticmethod
    def _is_mock_fallback(result: PluginResult) -> bool:
        for warning in result.warnings:
            marker = str(warning).strip()
            if marker in {"mock_fallback", "mock_output"}:
                return True
        return False

    @staticmethod
    def _parents_cacheable(context: StageContext, parent_aliases: list[str]) -> bool:
        for alias in parent_aliases:
            node = context.meeting.nodes.get(alias)
            if node and not getattr(node, "cacheable", True):
                return False
        return True

    def run(self, context: StageContext) -> StageResult:
        self._context = context
        plugin_id = self._config.plugin_id_for(self.stage_id)
        stage_params = self._config.plugin_params_for(self.stage_id)
        public_params, run_params = self._resolve_plugin_params(context, plugin_id, stage_params)
        connector = f"{self.stage_id}.run"
        execution = self._run_hook(context, connector, plugin_id, run_params)
        if execution is None:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )
        if execution.error:
            return StageResult(stage_id=self.stage_id, status="failed", cache_hit=False, error=execution.error)
        status = "success" if execution.result is not None else "failed"
        return StageResult(stage_id=self.stage_id, status=status, cache_hit=False)
