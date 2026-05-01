from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PluginHealthLocalPrereqController:
    @staticmethod
    def run_local_prereq_checks(
        plugin_id: str,
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        *,
        capabilities: dict[str, Any] | None,
        value_resolver: Callable[[dict[str, Any], dict[str, Any], str], Any],
        coerce_bool: Callable[[object], bool],
        resolve_existing_path: Callable[[str, str, bool], str],
        resolve_existing_dir: Callable[[str, str], str],
        local_model_present: Callable[[str, list[str]], bool],
        issue_factory: Callable[[str, str, str, str], object],
    ) -> tuple[list[str], list[object]]:
        checks: list[str] = []
        issues: list[object] = []
        ran_any = False
        if PluginHealthLocalPrereqController.check_local_binary_prerequisites(
            settings,
            stage_params,
            capabilities=capabilities,
            value_resolver=value_resolver,
            coerce_bool=coerce_bool,
            resolve_existing_path=resolve_existing_path,
            issue_factory=issue_factory,
            issues=issues,
        ):
            ran_any = True
        if PluginHealthLocalPrereqController.check_local_model_cache_prerequisites(
            settings,
            stage_params,
            capabilities=capabilities,
            value_resolver=value_resolver,
            coerce_bool=coerce_bool,
            resolve_existing_path=resolve_existing_path,
            resolve_existing_dir=resolve_existing_dir,
            local_model_present=local_model_present,
            issue_factory=issue_factory,
            issues=issues,
        ):
            ran_any = True
        if ran_any:
            checks.append("local_prerequisites")
        return checks, issues

    @staticmethod
    def check_local_binary_prerequisites(
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        *,
        capabilities: dict[str, Any] | None,
        value_resolver: Callable[[dict[str, Any], dict[str, Any], str], Any],
        coerce_bool: Callable[[object], bool],
        resolve_existing_path: Callable[[str, str, bool], str],
        issue_factory: Callable[[str, str, str, str], object],
        issues: list[object],
    ) -> bool:
        spec = PluginHealthLocalPrereqController._cap_get(capabilities, "runtime", "local_binary", default={})
        if not isinstance(spec, dict):
            return False
        setting_key = str(spec.get("setting_key", "") or "").strip()
        env_key = str(spec.get("env_key", "") or "").strip()
        fallback = str(spec.get("fallback", "") or spec.get("default_path", "") or "").strip()
        label = str(spec.get("label", "") or "").strip() or "Local binary"
        executable = coerce_bool(spec.get("executable", True))
        if not setting_key:
            return False
        configured = str(value_resolver(stage_params, settings, setting_key) or "").strip() or fallback
        resolved = resolve_existing_path(configured, env_key, executable)
        if resolved:
            return True
        issues.append(
            issue_factory(
                "local_binary_missing",
                f"{label} is not available.",
                f"{setting_key}='{configured}'",
                f"Set '{setting_key}' in Settings{f' or define {env_key}' if env_key else ''}.",
            )
        )
        return True

    @staticmethod
    def local_model_cache_spec(capabilities: dict[str, Any] | None) -> dict[str, Any]:
        spec = PluginHealthLocalPrereqController._cap_get(capabilities, "health", "local_model_cache", default={})
        return dict(spec) if isinstance(spec, dict) and spec else {}

    @staticmethod
    def check_local_model_cache_prerequisites(
        settings: dict[str, Any],
        stage_params: dict[str, Any],
        *,
        capabilities: dict[str, Any] | None,
        value_resolver: Callable[[dict[str, Any], dict[str, Any], str], Any],
        coerce_bool: Callable[[object], bool],
        resolve_existing_path: Callable[[str, str, bool], str],
        resolve_existing_dir: Callable[[str, str], str],
        local_model_present: Callable[[str, list[str]], bool],
        issue_factory: Callable[[str, str, str, str], object],
        issues: list[object],
    ) -> bool:
        spec = PluginHealthLocalPrereqController.local_model_cache_spec(capabilities)
        if not isinstance(spec, dict) or not spec:
            return False

        cache_dir_key = str(spec.get("cache_dir_key", "") or "").strip() or "cache_dir"
        cache_dir_default = str(spec.get("cache_dir_default", "") or "").strip()
        cache_dir_env = str(spec.get("cache_dir_env", "") or "").strip()
        model_path_key = str(spec.get("model_path_key", "") or "").strip() or "model_path"
        model_path_env = str(spec.get("model_path_env", "") or "").strip()
        model_id_key = str(spec.get("model_id_key", "") or "").strip() or "model_id"
        allow_download_key = str(spec.get("allow_download_key", "") or "").strip() or "allow_download"
        model_label = str(spec.get("model_label", "") or "").strip() or "Local model"
        file_globs = spec.get("file_globs")
        if not isinstance(file_globs, list) or not file_globs:
            file_globs = ["*.gguf"]
        normalized_globs = [str(item or "").strip() for item in file_globs if str(item or "").strip()]
        if not normalized_globs:
            normalized_globs = ["*.gguf"]

        cache_dir_raw = str(value_resolver(stage_params, settings, cache_dir_key) or "").strip() or cache_dir_default
        cache_dir = resolve_existing_dir(cache_dir_raw, cache_dir_env)
        model_path_raw = str(value_resolver(stage_params, settings, model_path_key) or "").strip()
        model_id = str(value_resolver(stage_params, settings, model_id_key) or "").strip()
        allow_download = coerce_bool(value_resolver(stage_params, settings, allow_download_key))
        has_local_model = local_model_present(cache_dir, normalized_globs)

        path_missing_code = str(spec.get("path_missing_code", "") or "").strip() or "local_model_path_missing"
        missing_code = str(spec.get("missing_code", "") or "").strip() or "local_model_missing"
        not_cached_code = str(spec.get("not_cached_code", "") or "").strip() or "local_model_not_cached"

        if model_path_raw:
            model_path = resolve_existing_path(model_path_raw, model_path_env, False)
            if not model_path:
                issues.append(
                    issue_factory(
                        path_missing_code,
                        "Configured local model file is missing.",
                        f"{model_path_key}='{model_path_raw}'",
                        f"Download/select {model_label.lower()} or update '{model_path_key}'.",
                    )
                )
        elif not model_id and not has_local_model:
            issues.append(
                issue_factory(
                    missing_code,
                    f"No {model_label.lower()} is configured.",
                    "",
                    f"Set '{model_path_key}' or '{model_id_key}' in Settings.",
                )
            )
        elif model_id and not allow_download and not has_local_model:
            issues.append(
                issue_factory(
                    not_cached_code,
                    f"Configured {model_label.lower()} is not cached locally.",
                    f"{cache_dir_key}='{cache_dir_raw}' {model_id_key}='{model_id}'",
                    f"Enable downloads or place the model into {cache_dir_key}.",
                )
            )
        return True

    @staticmethod
    def _cap_get(payload: object, *keys: str, default: object = None) -> object:
        current = payload
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(str(key))
        return current if current is not None else default
