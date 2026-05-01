from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import inspect
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from aimn.core.app_paths import get_plugin_roots
from aimn.core.contracts import (
    ActionDescriptor,
    ArtifactSchema,
    HookContext,
    PluginResult,
)
from aimn.core.plugin_discovery import PluginDiscovery
from aimn.core.plugin_distribution import PluginDistributionResolver
from aimn.core.plugin_manifest import HookSpec, PluginManifest
from aimn.core.plugin_policy import PluginPolicy
from aimn.core.plugins_config import PluginsConfig
from aimn.core.settings_store import SettingsStore

StageEventHandler = Callable[[str, dict], None]

@dataclass(frozen=True)
class HookHandler:
    plugin_id: str
    handler_id: str
    name: str
    mode: str
    priority: int
    func: Callable[[HookContext], PluginResult]


@dataclass(frozen=True)
class HookExecution:
    plugin_id: str
    handler_id: str
    result: Optional[PluginResult]
    error: Optional[str]
    mode: str


class PluginContext:
    def __init__(
        self,
        registry: "PluginRegistry",
        settings: "PluginSettingsService",
        plugin_id: str,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._plugin_id = plugin_id

    def register_hook_handler(
        self,
        hook_name: str,
        handler: Callable[[HookContext], PluginResult],
        *,
        mode: str = "optional",
        priority: int = 100,
        handler_id: str | None = None,
    ) -> None:
        self._registry.register_hook_handler(
            plugin_id=self._plugin_id,
            hook_name=hook_name,
            handler=handler,
            mode=mode,
            priority=priority,
            handler_id=handler_id,
        )

    def register_artifact_kind(self, kind: str, schema: ArtifactSchema | dict) -> None:
        self._registry.register_artifact_kind(kind, schema, self._plugin_id)

    def subscribe(self, event_name: str, handler) -> None:
        self._registry.subscribe(event_name, handler, self._plugin_id)

    def register_settings_schema(self, provider_callable) -> None:
        self._registry.register_settings_schema(self._plugin_id, provider_callable)

    def register_actions(self, provider_callable) -> None:
        self._registry.register_actions(self._plugin_id, provider_callable)

    def register_job_provider(self, provider_callable) -> None:
        self._registry.register_job_provider(self._plugin_id, provider_callable)

    def register_service(self, service_name: str, provider_callable) -> None:
        self._registry.register_service(self._plugin_id, service_name, provider_callable)

    def get_service(self, service_name: str):
        return self._registry.get_service(service_name)

    def get_settings(self) -> dict:
        return self._settings.get_settings(self._plugin_id, include_secrets=True)

    def set_settings(self, new_settings: dict, *, secret_fields: Iterable[str]) -> None:
        self._settings.set_settings(self._plugin_id, new_settings, secret_fields=secret_fields)

    def get_plugin_config(self) -> dict:
        return self._settings.get_settings(self._plugin_id, include_secrets=True)

    def get_setting(self, key: str, default=None):
        return self.get_settings().get(str(key), default)

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        return self._settings.get_secret(self._plugin_id, key, default=default)

    def set_secret(self, key: str, value: str | None) -> None:
        self._settings.set_secret(self._plugin_id, key, value)

    def get_storage_path(self) -> str:
        return str(self._settings.get_storage_path(self._plugin_id))

    def get_logger(self):
        return logging.getLogger(f"aimn.plugin.{self._plugin_id}")


class PluginRegistry:
    def __init__(self) -> None:
        self._manifests: Dict[str, PluginManifest] = {}
        self._hooks: Dict[str, List[HookHandler]] = {}
        self._artifact_kinds: Dict[str, ArtifactSchema] = {}
        self._event_handlers: Dict[str, List[tuple[str, Callable]]] = {}
        self._plugin_errors: Dict[str, List[str]] = {}
        self._settings_schema_providers: Dict[str, Callable[[], dict]] = {}
        self._actions_providers: Dict[str, Callable[[], List[ActionDescriptor]]] = {}
        self._job_providers: Dict[str, Callable[[], dict]] = {}
        self._services: Dict[str, tuple[str, object]] = {}

    def clear(self) -> None:
        self._manifests.clear()
        self._hooks.clear()
        self._artifact_kinds.clear()
        self._event_handlers.clear()
        self._plugin_errors.clear()
        self._settings_schema_providers.clear()
        self._actions_providers.clear()
        self._job_providers.clear()
        self._services.clear()

    def add_manifest(self, manifest: PluginManifest) -> None:
        self._manifests[manifest.plugin_id] = manifest

    def manifests(self) -> Iterable[PluginManifest]:
        return self._manifests.values()

    def manifest_for(self, plugin_id: str) -> Optional[PluginManifest]:
        return self._manifests.get(plugin_id)

    def handlers_for(self, hook_name: str) -> List[HookHandler]:
        return list(self._hooks.get(hook_name, []))

    def register_artifact_kind(self, kind: str, schema: ArtifactSchema | dict, plugin_id: str) -> None:
        manifest = self._manifests.get(plugin_id)
        if not manifest:
            self._record_error(plugin_id, f"artifact_register_failed:unknown_plugin:{kind}")
            return
        if kind not in manifest.artifacts:
            self._record_error(plugin_id, f"artifact_not_declared:{kind}")
            return
        schema_obj = _coerce_schema(schema)
        if not schema_obj:
            self._record_error(plugin_id, f"artifact_schema_invalid:{kind}")
            return
        if kind not in self._artifact_kinds:
            self._artifact_kinds[kind] = schema_obj
        else:
            existing = self._artifact_kinds[kind]
            if existing != schema_obj:
                self._record_error(plugin_id, f"artifact_kind_conflict:{kind}")

    def register_hook_handler(
        self,
        plugin_id: str,
        hook_name: str,
        handler: Callable[[HookContext], PluginResult],
        *,
        mode: str = "optional",
        priority: int = 100,
        handler_id: str | None = None,
    ) -> None:
        manifest = self._manifests.get(plugin_id)
        if not manifest:
            self._record_error(plugin_id, f"hook_register_failed:unknown_plugin:{hook_name}")
            return
        hook_spec = _find_manifest_hook(manifest, hook_name, handler_id)
        if not hook_spec:
            self._record_error(plugin_id, f"hook_register_blocked:{hook_name}")
            return
        normalized_mode = hook_spec.mode if hook_spec.mode in {"optional", "required"} else "optional"
        resolved_id = handler_id or hook_spec.handler_id or getattr(handler, "__name__", "handler")
        existing = self._hooks.get(hook_name, [])
        for entry in existing:
            if entry.plugin_id == plugin_id and entry.handler_id == resolved_id:
                return
        self._hooks.setdefault(hook_name, []).append(
            HookHandler(
                plugin_id=plugin_id,
                handler_id=resolved_id,
                name=hook_name,
                mode=normalized_mode,
                priority=hook_spec.priority,
                func=handler,
            )
        )

    def artifact_schema(self, kind: str) -> Optional[ArtifactSchema]:
        return self._resolve_schema(kind)

    def subscribe(self, event_name: str, handler: Callable, plugin_id: str) -> None:
        handlers = self._event_handlers.setdefault(event_name, [])
        handlers.append((plugin_id, handler))

    def emit(self, event_name: str, payload: dict) -> None:
        handlers = list(self._event_handlers.get(event_name, []))
        for plugin_id, handler in handlers:
            try:
                handler(payload)
            except Exception as exc:
                self._record_error(plugin_id, str(exc))
                logging.getLogger("aimn.plugins").warning(
                    "plugin_event_failed id=%s event=%s error=%s", plugin_id, event_name, exc
                )

    def register_settings_schema(self, plugin_id: str, provider: Callable[[], dict]) -> None:
        self._settings_schema_providers[plugin_id] = provider

    def register_actions(self, plugin_id: str, provider: Callable[[], List[ActionDescriptor]]) -> None:
        self._actions_providers[plugin_id] = provider

    def register_job_provider(self, plugin_id: str, provider: Callable[[], dict]) -> None:
        self._job_providers[plugin_id] = provider

    def register_service(self, plugin_id: str, service_name: str, provider: object) -> None:
        name = str(service_name or "").strip()
        if not name:
            self._record_error(plugin_id, "service_name_missing")
            return
        existing = self._services.get(name)
        if existing and existing[0] != plugin_id:
            self._record_error(plugin_id, f"service_conflict:{name}")
            return
        self._services[name] = (plugin_id, provider)

    def get_service(self, service_name: str):
        name = str(service_name or "").strip()
        if not name:
            return None
        entry = self._services.get(name)
        if not entry:
            return None
        plugin_id, provider = entry
        try:
            return provider() if callable(provider) else provider
        except Exception as exc:
            self._record_error(plugin_id, f"service_provider_failed:{name}:{exc}")
            return None

    def settings_schema_for(self, plugin_id: str) -> Optional[dict]:
        provider = self._settings_schema_providers.get(plugin_id)
        if not provider:
            return None
        try:
            schema = provider()
        except Exception as exc:
            self._record_error(plugin_id, f"settings_schema_failed:{exc}")
            return None
        return schema if isinstance(schema, dict) else None

    def actions_for(self, plugin_id: str) -> List[ActionDescriptor]:
        provider = self._actions_providers.get(plugin_id)
        if not provider:
            return []
        try:
            actions = provider()
        except Exception as exc:
            self._record_error(plugin_id, f"actions_provider_failed:{exc}")
            return []
        return [action for action in actions if isinstance(action, ActionDescriptor)]

    def job_provider_for(self, plugin_id: str) -> Optional[Callable[[], dict]]:
        return self._job_providers.get(plugin_id)

    def plugin_errors(self) -> Dict[str, List[str]]:
        return {key: list(values) for key, values in self._plugin_errors.items()}

    def clear_errors(self) -> None:
        self._plugin_errors.clear()

    def _record_error(self, plugin_id: str, message: str) -> None:
        self._plugin_errors.setdefault(plugin_id, []).append(message)
        logging.getLogger("aimn.plugins").warning(
            "plugin_error plugin_id=%s error=%s", plugin_id, message
        )

    def _resolve_schema(self, kind: str) -> Optional[ArtifactSchema]:
        return self._artifact_kinds.get(kind)


class PluginSettingsService:
    def __init__(self, repo_root: Path, registry: PluginRegistry) -> None:
        self._repo_root = repo_root
        self._registry = registry
        self._settings_store = SettingsStore(
            repo_root / "config" / "settings",
            repo_root=repo_root,
        )

    def get_settings(self, plugin_id: str, *, include_secrets: bool = False) -> dict:
        return self._settings_store.get_settings(plugin_id, include_secrets=include_secrets)

    def get_settings_with_secrets(self, plugin_id: str) -> dict:
        return self._settings_store.get_settings(plugin_id, include_secrets=True)

    def get_secret_flags(self, plugin_id: str) -> dict:
        return self._settings_store.get_secret_flags(plugin_id)

    def get_secret(self, plugin_id: str, key: str, *, default: str | None = None) -> str | None:
        payload = self._settings_store.get_settings(plugin_id, include_secrets=True)
        value = payload.get(str(key))
        if value is None:
            return default
        return str(value)

    def set_secret(self, plugin_id: str, key: str, value: str | None) -> None:
        payload = self._settings_store.get_settings(plugin_id, include_secrets=False)
        field = str(key or "").strip()
        if not field:
            return
        if value is None or str(value).strip() == "":
            payload[field] = ""
        else:
            payload[field] = str(value)
        self._settings_store.set_settings(
            plugin_id,
            payload,
            secret_fields=[field],
            preserve_secrets=[],
        )
        self._registry.emit("settings.updated", {"plugin_id": plugin_id})

    def get_storage_path(self, plugin_id: str) -> Path:
        safe_id = str(plugin_id or "").strip().replace("/", "_").replace("\\", "_")
        path = self._repo_root / "config" / "plugin_state" / safe_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def set_settings(self, plugin_id: str, settings: dict, *, secret_fields: Iterable[str]) -> None:
        preserve = []
        for key in secret_fields:
            if not settings.get(key):
                preserve.append(key)
        self._settings_store.set_settings(
            plugin_id,
            settings,
            secret_fields=secret_fields,
            preserve_secrets=preserve,
        )
        self._registry.emit("settings.updated", {"plugin_id": plugin_id})


class PluginRuntime:
    def __init__(self, registry: PluginRegistry, config: PluginsConfig) -> None:
        self._registry = registry
        self._config = config

    def execute_connector(
        self,
        name: str,
        ctx: HookContext,
        allowed_plugin_ids: Optional[Iterable[str]] = None,
    ) -> List[HookExecution]:
        handlers = self._registry.handlers_for(name)
        if allowed_plugin_ids is not None:
            allowed = {pid for pid in allowed_plugin_ids}
            handlers = [handler for handler in handlers if handler.plugin_id in allowed]
        handlers.sort(key=lambda item: (item.priority, item.plugin_id, item.handler_id))

        executions: List[HookExecution] = []
        for handler in handlers:
            mode = self._normalize_mode(handler)
            try:
                raw_result = handler.func(ctx)
                if inspect.isawaitable(raw_result):
                    raw_result = _await_plugin_result(raw_result)
                if raw_result is None:
                    result = ctx.build_result()
                elif isinstance(raw_result, PluginResult):
                    result = raw_result
                    if ctx._collected_outputs:
                        result.outputs.extend(ctx._collected_outputs)
                    if ctx._collected_warnings:
                        result.warnings.extend(ctx._collected_warnings)
                else:
                    raise ValueError("invalid_plugin_result")
                self._validate_outputs(handler.plugin_id, result)
                executions.append(
                    HookExecution(
                        plugin_id=handler.plugin_id,
                        handler_id=handler.handler_id,
                        result=result,
                        error=None,
                        mode=mode,
                    )
                )
            except Exception as exc:
                message = str(exc)
                self._registry._record_error(handler.plugin_id, f"hook_failed:{handler.name}:{message}")
                executions.append(
                    HookExecution(
                        plugin_id=handler.plugin_id,
                        handler_id=handler.handler_id,
                        result=None,
                        error=message,
                        mode=mode,
                    )
                )
                if mode == "required":
                    raise
        return executions

    def _normalize_mode(self, handler: HookHandler) -> str:
        if handler.mode != "required":
            return "optional"
        trusted = self._config.trusted_plugins()
        if handler.plugin_id in trusted:
            return "required"
        self._registry._record_error(handler.plugin_id, f"required_hook_downgraded:{handler.name}")
        return "optional"

    def _validate_outputs(self, plugin_id: str, result: PluginResult) -> None:
        for output in result.outputs:
            schema = self._registry.artifact_schema(output.kind)
            if not schema:
                raise ValueError(f"artifact_kind_unregistered:{output.kind}")
            if not isinstance(output.content_type, str) or not output.content_type:
                raise ValueError(f"artifact_content_type_invalid:{output.kind}")
            if schema.content_type != output.content_type:
                raise ValueError(
                    f"artifact_content_type_mismatch:{output.kind}:{schema.content_type}!={output.content_type}"
                )
            if not isinstance(output.user_visible, bool):
                raise ValueError(f"artifact_user_visible_invalid:{output.kind}")
            if schema.user_visible != output.user_visible:
                raise ValueError(
                    f"artifact_user_visible_mismatch:{output.kind}:{schema.user_visible}!={output.user_visible}"
                )
            if not isinstance(output.content, str):
                raise ValueError(f"artifact_content_invalid:{output.kind}")
            if output.content == "":
                raise ValueError(f"artifact_empty:{output.kind}")
            if schema.max_size_bytes is not None:
                try:
                    size_bytes = len(output.content.encode("utf-8"))
                except Exception:
                    size_bytes = len(output.content)
                if size_bytes > schema.max_size_bytes:
                    raise ValueError(
                        f"artifact_too_large:{output.kind}:{size_bytes}>{schema.max_size_bytes}"
                    )


class PluginLoader:
    def __init__(
        self,
        repo_root: Path,
        config: PluginsConfig,
        registry: PluginRegistry,
        settings: PluginSettingsService,
    ) -> None:
        self._repo_root = repo_root
        self._plugin_roots = get_plugin_roots(repo_root)
        try:
            import sys

            # Support both module styles used by manifests/registry:
            # - package-qualified plugin modules require repo root on sys.path
            # - plugin-root relative modules require plugin dirs on sys.path
            repo_path = str(self._repo_root.resolve())
            plugin_paths = [str(path.resolve()) for path in self._plugin_roots]
            for path in (repo_path, *plugin_paths):
                if path and path not in sys.path:
                    sys.path.insert(0, path)
        except Exception:
            pass
        self._config = config
        self._registry = registry
        self._settings = settings
        self._loaded: Dict[str, object] = {}
        self._manifest_paths: Dict[str, Path] = {}
        self._discovery = PluginDiscovery(self._plugin_roots)
        self._policy = PluginPolicy(config)
        self._distribution = PluginDistributionResolver(repo_root)

    def _discover_manifests(self) -> None:
        self._registry.clear()
        self._manifest_paths = {}
        for entry in self._discovery.discover_entries():
            self._registry.add_manifest(entry.manifest)
            self._manifest_paths[entry.manifest.plugin_id] = entry.manifest_path

    def load(self) -> None:
        self._discover_manifests()
        for manifest in self._registry.manifests():
            if not self._policy.is_enabled(manifest.plugin_id):
                continue
            manifest_path = self._manifest_paths.get(manifest.plugin_id)
            if manifest_path is not None:
                access = self._distribution.resolve_plugin(
                    manifest.plugin_id,
                    manifest.distribution,
                    manifest_path,
                )
                if not access.can_run:
                    self._registry._record_error(
                        manifest.plugin_id,
                        f"plugin_access_denied:{access.access_state}",
                    )
                    continue
            self._load_plugin(manifest)

    def shutdown(self) -> None:
        for plugin_id, plugin in list(self._loaded.items()):
            try:
                if hasattr(plugin, "shutdown"):
                    plugin.shutdown()
            except Exception as exc:
                self._registry._record_error(plugin_id, str(exc))

    def manifest_path_for(self, plugin_id: str) -> Path | None:
        return self._manifest_paths.get(str(plugin_id or "").strip())

    def _load_plugin(self, manifest: PluginManifest) -> None:
        if manifest.plugin_id in self._loaded:
            return
        if manifest.api_version != "1":
            self._registry._record_error(
                manifest.plugin_id, f"unsupported_api_version:{manifest.api_version}"
            )
            return
        try:
            module_name, class_name = manifest.entrypoint.split(":")
        except ValueError as exc:
            self._registry._record_error(manifest.plugin_id, f"invalid entrypoint: {manifest.entrypoint}")
            logging.getLogger("aimn.plugins").warning(
                "plugin_entrypoint_invalid id=%s error=%s", manifest.plugin_id, exc
            )
            return
        if not _entrypoint_allows_core_imports(module_name):
            self._registry._record_error(manifest.plugin_id, "forbidden_core_import")
            logging.getLogger("aimn.plugins").warning(
                "plugin_core_import_blocked id=%s module=%s", manifest.plugin_id, module_name
            )
            return
        try:
            module = importlib.import_module(module_name)
            plugin_cls = getattr(module, class_name)
            plugin = plugin_cls()
            ctx = PluginContext(self._registry, self._settings, manifest.plugin_id)
            plugin.register(ctx)
            self._loaded[manifest.plugin_id] = plugin
        except Exception as exc:
            self._registry._record_error(manifest.plugin_id, str(exc))
            logging.getLogger("aimn.plugins").exception(
                "plugin_load_failed id=%s error=%s", manifest.plugin_id, exc
            )


def _find_manifest_hook(
    manifest: PluginManifest, hook_name: str, handler_id: str | None
) -> Optional[HookSpec]:
    for hook in manifest.hooks:
        if hook.name != hook_name:
            continue
        if not handler_id:
            return hook
        if hook.handler_id == handler_id:
            return hook
    return None


def _entrypoint_allows_core_imports(module_name: str) -> bool:
    paths: list[Path] = []
    spec = importlib.util.find_spec(module_name)
    if spec and spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            root = Path(location)
            if root.exists():
                paths.extend(root.rglob("*.py"))
    if spec and spec.origin and spec.origin.endswith(".py"):
        paths.append(Path(spec.origin))
    if "." in module_name:
        parent_name = module_name.rsplit(".", 1)[0]
        parent_spec = importlib.util.find_spec(parent_name)
        if parent_spec and parent_spec.submodule_search_locations:
            for location in parent_spec.submodule_search_locations:
                root = Path(location)
                if root.exists():
                    paths.extend(root.rglob("*.py"))
    if not paths:
        return True
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if _file_imports_core(resolved):
            return False
    return True


def _file_imports_core(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "aimn.core" or alias.name.startswith("aimn.core."):
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "aimn.core" or node.module.startswith("aimn.core.")):
                return True
    return False


def _coerce_schema(schema: ArtifactSchema | dict) -> Optional[ArtifactSchema]:
    if isinstance(schema, ArtifactSchema):
        return schema
    if isinstance(schema, dict):
        content_type = schema.get("content_type")
        user_visible = schema.get("user_visible", True)
        max_size_bytes = schema.get("max_size_bytes")
        allowed_extensions = _normalize_extensions(schema.get("allowed_extensions"))
        if max_size_bytes is not None and not isinstance(max_size_bytes, int):
            max_size_bytes = None
        if isinstance(content_type, str) and content_type and isinstance(user_visible, bool):
            return ArtifactSchema(
                content_type=content_type,
                user_visible=user_visible,
                max_size_bytes=max_size_bytes,
                allowed_extensions=allowed_extensions,
            )
    return None


def _normalize_extensions(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        ext = item.strip().lower().lstrip(".")
        if ext:
            normalized.append(ext)
    return normalized or None


def _await_plugin_result(awaitable) -> object:
    try:
        return asyncio.run(awaitable)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(awaitable)
        finally:
            try:
                loop.close()
            except Exception:
                pass
            asyncio.set_event_loop(None)
