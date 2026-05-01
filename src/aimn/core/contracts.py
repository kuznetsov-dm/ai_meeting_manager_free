from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


KIND_TRANSCRIPT = "transcript"
KIND_SEGMENTS = "segments"
KIND_ASR_SEGMENTS_JSON = "asr_segments_json"
KIND_EDITED = "edited"
KIND_SUMMARY = "summary"
KIND_ACTIONS = "actions"
KIND_DECISIONS = "decisions"
KIND_MANAGEMENT_SUGGESTIONS = "management_suggestions"
KIND_AUDIO = "audio"
KIND_DEBUG_JSON = "debug_json"
KIND_INDEX = "index"
KIND_DETECTED_LANGUAGE = "detected_language"


class PluginLogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class StageEvent:
    event_type: str
    stage_id: str | None = None
    message: str | None = None
    alias: str | None = None
    kind: str | None = None
    relpath: str | None = None
    progress: int | None = None
    timestamp: str = field(default_factory=_utc_now_iso)


@dataclass
class PluginOutput:
    kind: str
    content: str
    content_type: str
    user_visible: bool = True


@dataclass
class PluginResult:
    outputs: List[PluginOutput]
    warnings: List[str]


@dataclass(frozen=True)
class ArtifactSchema:
    content_type: str
    user_visible: bool = True
    max_size_bytes: int | None = None
    allowed_extensions: list[str] | None = None


@dataclass
class ArtifactMeta:
    kind: str
    path: str
    content_type: Optional[str] = None
    user_visible: bool = True


@dataclass
class Artifact:
    meta: ArtifactMeta
    content: str


@dataclass
class ActionResult:
    status: str
    message: str
    data: object | None = None
    job_id: str | None = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = {"status": self.status, "message": self.message}
        if self.data is not None:
            payload["data"] = self.data
        if self.job_id:
            payload["job_id"] = self.job_id
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


@dataclass
class ActionDescriptor:
    action_id: str
    label: str
    description: str = ""
    params_schema: dict | None = None
    dangerous: bool = False
    run_mode: str = "sync"
    handler: Callable[[dict, dict], ActionResult] | None = None

    def to_dict(self) -> dict:
        payload = {
            "id": self.action_id,
            "label": self.label,
            "description": self.description,
            "params_schema": self.params_schema or {"fields": []},
            "dangerous": bool(self.dangerous),
            "run_mode": self.run_mode or "sync",
        }
        return payload


@dataclass
class JobStatus:
    job_id: str
    status: str
    progress: float | None = None
    message: str = ""
    data: object | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        payload: dict = {"job_id": self.job_id, "status": self.status}
        if self.progress is not None:
            payload["progress"] = self.progress
        if self.message:
            payload["message"] = self.message
        if self.data is not None:
            payload["data"] = self.data
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


@dataclass
class HookContext:
    plugin_id: str
    meeting_id: str
    alias: Optional[str]
    input_text: Optional[str] = None
    input_media_path: Optional[str] = None
    force_run: bool = False
    progress_callback: Optional[Callable[[int], None]] = None
    cancel_requested: Optional[Callable[[], bool]] = None
    plugin_config: dict | None = None
    _output_dir: Optional[str] = None
    _get_artifact: Optional[Callable[[str], Optional[Artifact]]] = None
    _list_artifacts: Optional[Callable[[], List[ArtifactMeta]]] = None
    _schema_resolver: Optional[Callable[[str], Optional[ArtifactSchema]]] = None
    _get_secret: Optional[Callable[[str], Optional[str]]] = None
    _storage_dir: Optional[str] = None
    _resolve_service: Optional[Callable[[str], Any]] = None
    _notice_callback: Optional[Callable[[str], None]] = None
    _collected_outputs: List[PluginOutput] = field(default_factory=list)
    _collected_warnings: List[str] = field(default_factory=list)
    _artifacts_view: "_HookArtifactsView | None" = field(default=None, init=False, repr=False)

    def get_artifact(self, kind: str) -> Optional[Artifact]:
        if not self._get_artifact:
            return None
        return self._get_artifact(kind)

    def notice(self, message: str) -> None:
        if not self._notice_callback:
            return
        text = str(message or "").strip()
        if not text:
            return
        self._notice_callback(text)

    def list_artifacts(self) -> List[ArtifactMeta]:
        if not self._list_artifacts:
            return []
        return self._list_artifacts()

    def write_artifact(
        self,
        kind: str,
        content: Any,
        *,
        content_type: str | None = None,
    ) -> None:
        schema = self._schema_resolver(kind) if self._schema_resolver else None
        if not schema:
            raise ValueError(f"artifact_kind_unregistered:{kind}")
        resolved_content_type = content_type or schema.content_type
        resolved_user_visible = schema.user_visible
        if resolved_content_type != schema.content_type:
            raise ValueError(
                f"artifact_content_type_mismatch:{kind}:{schema.content_type}!={resolved_content_type}"
            )
        self._collected_outputs.append(
            PluginOutput(
                kind=kind,
                content=str(content),
                content_type=resolved_content_type,
                user_visible=resolved_user_visible,
            )
        )

    def emit_warning(self, message: str) -> None:
        self._collected_warnings.append(str(message))

    def build_result(self) -> PluginResult:
        return PluginResult(outputs=list(self._collected_outputs), warnings=list(self._collected_warnings))

    @property
    def settings(self) -> dict:
        return dict(self.plugin_config or {})

    def get_setting(self, key: str, default: Any = None) -> Any:
        return dict(self.plugin_config or {}).get(str(key), default)

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        if self._get_secret is None:
            value = dict(self.plugin_config or {}).get(str(key))
            return str(value) if value is not None else default
        value = self._get_secret(str(key))
        if value is None:
            return default
        return str(value)

    @property
    def storage_path(self) -> str | None:
        return self._storage_dir

    def get_service(self, name: str) -> Any:
        if not self._resolve_service:
            return None
        return self._resolve_service(str(name))

    @property
    def logger(self):
        return logging.getLogger(f"aimn.plugin.{self.plugin_id}")

    def log(self, level: PluginLogLevel | str, message: str) -> None:
        logger = self.logger
        normalized = _normalize_log_level(level)
        text = str(message or "")
        if normalized == PluginLogLevel.DEBUG:
            logger.debug(text)
            return
        if normalized == PluginLogLevel.INFO:
            logger.info(text)
            return
        if normalized == PluginLogLevel.WARNING:
            logger.warning(text)
            return
        logger.error(text)

    @property
    def artifacts(self) -> "_HookArtifactsView":
        if self._artifacts_view is None:
            self._artifacts_view = _HookArtifactsView(self)
        return self._artifacts_view


def _normalize_log_level(level: PluginLogLevel | str) -> PluginLogLevel:
    if isinstance(level, PluginLogLevel):
        return level
    raw = str(level or "").strip().upper()
    try:
        return PluginLogLevel(raw)
    except Exception:
        return PluginLogLevel.INFO


class _HookArtifactsView:
    def __init__(self, ctx: HookContext) -> None:
        self._ctx = ctx

    def get_artifact(self, kind: str) -> Artifact | None:
        return self._ctx.get_artifact(kind)

    def list_artifacts(self) -> List[ArtifactMeta]:
        return self._ctx.list_artifacts()

    def save_artifact(self, kind: str, content: Any, *, content_type: str | None = None) -> None:
        self._ctx.write_artifact(kind, content, content_type=content_type)


@dataclass
class PluginDescriptor:
    plugin_id: str
    stage_id: str
    name: str
    module: str
    class_name: str
    version: str = ""
    enabled: bool = True
    installed: bool = True
    product_name: str | None = None
    provider_name: str | None = None
    provider_description: str = ""
    model_info: Dict[str, Dict[str, str]] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    highlights: str = ""
    description: str = ""
    howto: List[str] = field(default_factory=list)
    icon_key: str = ""
    source_kind: str = "bundled"
    source_path: str = ""
    owner_type: str = "first_party"
    pricing_model: str = "free"
    requires_platform_edition: bool = False
    included_in_core: bool = False
    entitled: bool = True
    access_state: str = "active"
    access_reason: str = ""
    catalog_enabled: bool = False
    billing_product_id: str = ""
    fallback_plugin_id: str = ""
    default_visibility: str = "visible"
    runtime_state: str = "available_inactive"
    visible_in_catalog: bool = True
    remote_version: str = ""
    has_update: bool = False
    remote_only: bool = False
    download_url: str = ""
    manifest_url: str = ""
    publisher_id: str = ""
    checksum_sha256: str = ""
    signature: str = ""
    signature_algorithm: str = ""
    signing_key_id: str = ""
    trust_level: str = ""
    trust_source: str = ""
    verification_state: str = ""
    checksum_verified: bool = False
    signature_verified: bool = False
    compatible_app_versions: List[str] = field(default_factory=list)


@dataclass
class PluginSetting:
    key: str
    label: str
    value: str
    options: List["PluginOption"] | None = None
    editable: bool = False
    advanced: bool = False


@dataclass
class PluginOption:
    label: str
    value: str


@dataclass
class PluginUiSchema:
    plugin_id: str
    stage_id: str
    settings: List[PluginSetting]


class PluginCatalogProtocol(Protocol):
    def all_plugins(self) -> List[PluginDescriptor]:
        ...

    def plugin_by_id(self, plugin_id: str) -> Optional[PluginDescriptor]:
        ...

    def plugins_for_stage(self, stage_id: str) -> List[PluginDescriptor]:
        ...

    def enabled_plugins(self) -> List[PluginDescriptor]:
        ...

    def allowlist_ids(self) -> List[str]:
        ...

    def schema_for(self, plugin_id: str) -> Optional[PluginUiSchema]:
        ...

    def display_name(self, plugin_id: str) -> str:
        ...

    def provider_label(self, plugin_id: str) -> str:
        ...

    def provider_description(self, plugin_id: str) -> str:
        ...

    def model_details(self, plugin_id: str, model_id: str) -> Dict[str, str]:
        ...

    def default_plugin_for_stage(self, stage_id: str) -> Optional[PluginDescriptor]:
        ...
