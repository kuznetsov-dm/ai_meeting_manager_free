from __future__ import annotations

import socket
import time
from collections.abc import Callable
from pathlib import Path

from aimn.ui.controllers.stage_model_normalization import parse_variant_selection_state, selection_key
from aimn.ui.tabs.contracts import SettingOption


def _cap_get(payload: object, *keys: str, default: object = None) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(str(key))
    return current if current is not None else default


class ModelCatalogController:
    _MODELS_META_KEY = "_models_catalog_meta"
    _STATUS_READY = {"installed", "enabled", "ready", "ok", "success"}
    _STATUS_NEEDS_SETUP = {
        "not_installed",
        "missing",
        "model_missing",
        "setup_required",
        "api_key_missing",
        "auth_missing",
        "download_required",
    }
    _STATUS_LIMITED = {"rate_limited", "cooling_down", "cooldown", "quota_limited"}
    _STATUS_UNAVAILABLE = {
        "request_failed",
        "failed",
        "error",
        "unavailable",
        "blocked",
        "forbidden",
        "auth_required",
        "timeout",
        "transport_error",
        "network_error",
    }

    def __init__(
        self,
        *,
        app_root: Path,
        config_data_provider: Callable[[], dict],
        settings_store,
        models_service,
        action_service,
        get_catalog: Callable[[], object],
        plugin_capabilities: Callable[[str], dict],
        is_transcription_local_plugin: Callable[[str], bool],
        first_transcription_local_plugin_id: Callable[[], str],
        is_secret_field_name: Callable[[str], bool],
    ) -> None:
        self._app_root = Path(app_root)
        self._config_data_provider = config_data_provider
        self._settings_store = settings_store
        self._models_service = models_service
        self._action_service = action_service
        self._get_catalog = get_catalog
        self._plugin_capabilities = plugin_capabilities
        self._is_transcription_local_plugin = is_transcription_local_plugin
        self._first_transcription_local_plugin_id = first_transcription_local_plugin_id
        self._is_secret_field_name = is_secret_field_name
        self._llm_models_cache: dict[str, tuple[float, list[dict]]] = {}
        self._host_id = self._current_host_id()

    def invalidate_provider_cache(self, plugin_id: str) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        self._llm_models_cache.pop(pid, None)

    def refresh_models_from_provider(self, plugin_id: str) -> tuple[bool, str]:
        """
        Refresh provider models via plugin action and persist them to settings.

        This method is intended for background prewarm jobs only and must not be
        called from latency-sensitive UI paint/refresh paths.
        """
        pid = str(plugin_id or "").strip()
        if not pid:
            return False, "plugin_id_missing"
        models_caps = self._models_caps(pid)
        list_action = self._list_models_action_id(pid, models_caps)
        is_local_plugin = self._is_local_models_plugin(pid)
        requires_installed = self._requires_installed_selection(pid)
        models_all: list[dict] | None = None
        failure_reason = "list_action_missing"
        if list_action:
            models_all = self._load_models_from_action(pid, list_action)
            if models_all is None:
                failure_reason = "provider_list_models_failed"
        if models_all is not None:
            if models_all or is_local_plugin:
                self._persist_models_config(pid, models_all)
            effective_rows = self.load_plugin_models_config(pid) if (models_all or is_local_plugin) else list(models_all)
            models = self._models_payload_from_rows(effective_rows, only_installed=requires_installed)
            if is_local_plugin and not models:
                models = self.local_models_from_capabilities(pid)
            self._llm_models_cache[pid] = (time.monotonic(), list(models))
            return True, "ok"

        fallback_rows = self.load_plugin_models_config(pid)
        if fallback_rows or is_local_plugin:
            models = self._models_payload_from_rows(fallback_rows, only_installed=requires_installed)
            if is_local_plugin and not models:
                models = self.local_models_from_capabilities(pid)
            self._llm_models_cache[pid] = (time.monotonic(), list(models))
            return True, "ok"
        return False, failure_reason

    def whisper_models_state(self) -> tuple[list[str], list[str]]:
        stage = self._config_data_provider().get("stages", {}).get("transcription", {})
        plugin_id = str(stage.get("plugin_id", "")).strip() if isinstance(stage, dict) else ""
        if not self._is_transcription_local_plugin(plugin_id):
            plugin_id = self._first_transcription_local_plugin_id()
        if not plugin_id:
            return [], []
        models = self._models_service.load_models_config(plugin_id)
        caps = self._plugin_capabilities(plugin_id)
        local_files = _cap_get(caps, "models", "local_files", default={})
        root_setting = str(_cap_get(local_files, "root_setting", default="models_dir") or "models_dir").strip()
        default_root = str(
            _cap_get(local_files, "default_root", default="models/whisper") or "models/whisper"
        ).strip()
        known = sorted(
            {
                str(entry.get("model_id", "")).strip()
                for entry in models
                if str(entry.get("model_id", "")).strip()
            }
        )
        settings = self._settings_store.get_settings(plugin_id, include_secrets=False)
        raw_dir = str(settings.get(root_setting, "")).strip()
        root = Path(raw_dir) if raw_dir else (self._app_root / Path(default_root))
        installed: list[str] = []
        for entry in models:
            model_id = str(entry.get("model_id", "")).strip()
            filename = str(entry.get("file", "") or entry.get("filename", "")).strip()
            if not model_id or not filename:
                continue
            if (root / filename).exists():
                installed.append(model_id)
        return installed, known

    def model_options_for(self, plugin_id: str) -> list[SettingOption]:
        pid = str(plugin_id or "").strip()
        models: list[dict]
        if self._requires_installed_selection(pid):
            models = self.llm_installed_models_payload(pid)
        else:
            models = self.available_models_payload(pid)
        options: list[SettingOption] = []
        for entry in models:
            model_id = str(entry.get("model_id", "")).strip()
            if not model_id:
                continue
            if self._requires_installed_selection(pid):
                if "installed" in entry or "status" in entry:
                    installed = self._coerce_model_installed(entry)
                    if installed is not True:
                        continue
            label = str(entry.get("product_name", "")).strip() or model_id
            if label != model_id:
                label = f"{label} ({model_id})"
            options.append(SettingOption(label=label, value=model_id))
        return options

    def load_plugin_models_config(self, plugin_id: str) -> list[dict]:
        pid = str(plugin_id or "").strip()
        settings = self._settings_store.get_settings(plugin_id, include_secrets=False)
        if pid == "llm.ollama":
            raw = settings.get("models") if isinstance(settings, dict) else None
            if not isinstance(raw, list):
                return []
            from_settings = [entry for entry in raw if isinstance(entry, dict)]
            migrated, changed = self._migrate_model_settings_rows(from_settings)
            if changed and isinstance(settings, dict):
                self._persist_migrated_model_rows(pid, settings, migrated)
            return migrated
        local_plugin = self._is_local_models_plugin(pid)
        trusted_local_cache = True
        if local_plugin and isinstance(settings, dict) and settings.get(self._MODELS_META_KEY):
            trusted_local_cache = self._is_local_models_cache_trusted(settings)
        raw = settings.get("models") if isinstance(settings, dict) else None
        if isinstance(raw, list) and (not local_plugin or trusted_local_cache):
            from_settings = [entry for entry in raw if isinstance(entry, dict)]
            if from_settings:
                merged_rows = self._merge_model_rows_with_passport(pid, from_settings)
                merged_rows = self._prune_invalid_local_model_rows(pid, merged_rows)
                migrated, changed = self._migrate_model_settings_rows(merged_rows)
                if changed:
                    self._persist_migrated_model_rows(pid, settings, migrated)
                return migrated
        if not local_plugin or trusted_local_cache:
            models = self._models_service.load_models_config(pid)
            if models:
                merged_rows = self._merge_model_rows_with_passport(pid, models)
                merged_rows = self._prune_invalid_local_model_rows(pid, merged_rows)
                migrated, changed = self._migrate_model_settings_rows(merged_rows)
                if changed and isinstance(settings, dict):
                    self._persist_migrated_model_rows(pid, settings, migrated)
                return migrated
        plugin = self._get_catalog().plugin_by_id(pid)
        if plugin and isinstance(plugin.model_info, dict) and plugin.model_info:
            from_passport: list[dict] = []
            for model_id, meta in plugin.model_info.items():
                mid = str(model_id or "").strip()
                if not mid:
                    continue
                label = ""
                if isinstance(meta, dict):
                    label = str(meta.get("model_name", "")).strip()
                from_passport.append(
                    {
                        "model_id": mid,
                        "product_name": label or mid,
                    }
                )
            if from_passport:
                return from_passport
        return []

    def _prune_invalid_local_model_rows(self, plugin_id: str, rows: list[dict]) -> list[dict]:
        pid = str(plugin_id or "").strip()
        if not pid or not self._is_local_models_plugin(pid):
            return list(rows)
        pruned: list[dict] = []
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            row = dict(entry)
            model_id = str(row.get("model_id", "") or row.get("id", "")).strip()
            model_path = str(row.get("model_path", "") or row.get("path", "")).strip()
            file_name = str(row.get("file", "") or row.get("filename", "")).strip()
            if (
                model_id.lower().endswith(".gguf")
                and not model_path
                and not file_name
            ):
                continue
            pruned.append(row)
        return pruned

    def _merge_model_rows_with_passport(self, plugin_id: str, rows: list[dict]) -> list[dict]:
        pid = str(plugin_id or "").strip()
        plugin = self._get_catalog().plugin_by_id(pid)
        model_info = plugin.model_info if plugin and isinstance(plugin.model_info, dict) else {}
        normalized_rows = [dict(entry) for entry in rows if isinstance(entry, dict)]
        canonical_tail_map: dict[str, str] = {}
        if isinstance(model_info, dict):
            for model_id in model_info:
                mid = str(model_id or "").strip()
                if not mid or "/" not in mid:
                    continue
                tail = mid.split("/", 1)[1].strip()
                if tail and tail not in canonical_tail_map:
                    canonical_tail_map[tail] = mid

        for index, entry in enumerate(normalized_rows):
            row = dict(entry)
            mid = str(row.get("model_id", "") or row.get("id", "")).strip()
            canonical_mid = canonical_tail_map.get(mid, mid)
            if canonical_mid != mid:
                row["model_id"] = canonical_mid
            normalized_rows[index] = row

        merged_rows: list[dict] = []
        by_key: dict[str, int] = {}

        def _score(entry: dict) -> int:
            score = 0
            for key in (
                "model_id",
                "model_path",
                "file",
                "download_url",
                "source_url",
                "description",
                "product_name",
                "last_pipeline_quality",
            ):
                if str(entry.get(key, "") or "").strip():
                    score += 1
            if self._coerce_model_installed(entry) is True:
                score += 2
            if self._coerce_model_observed_success(entry):
                score += 1
            return score

        def _merge_row(existing: dict, incoming: dict) -> dict:
            base = dict(existing)
            for key, value in incoming.items():
                if key not in base or base.get(key) in (None, "", [], {}):
                    base[key] = value
            for preferred in ("favorite", "enabled", "installed", "status", "availability_status"):
                if preferred in incoming:
                    base[preferred] = incoming.get(preferred)
            return base

        for row in normalized_rows:
            key = self._model_payload_key(row)
            if not key:
                merged_rows.append(row)
                continue
            existing_index = by_key.get(key)
            if existing_index is None:
                by_key[key] = len(merged_rows)
                merged_rows.append(row)
                continue
            existing = merged_rows[existing_index]
            preferred_existing = _score(existing) >= _score(row)
            kept = existing if preferred_existing else row
            extra = row if preferred_existing else existing
            merged_rows[existing_index] = _merge_row(kept, extra)

        if not isinstance(model_info, dict) or not model_info:
            return merged_rows

        for index, entry in enumerate(merged_rows):
            key = self._model_payload_key(entry)
            if key:
                by_key[key] = index

        for model_id, meta in model_info.items():
            mid = str(model_id or "").strip()
            if not mid:
                continue
            key = f"id:{mid}"
            product_name = str(meta.get("model_name", "") if isinstance(meta, dict) else "").strip() or mid
            if key in by_key:
                row = dict(merged_rows[by_key[key]])
                if not str(row.get("product_name", "") or "").strip():
                    row["product_name"] = product_name
                merged_rows[by_key[key]] = row
                continue
            merged_rows.append(
                {
                    "model_id": mid,
                    "product_name": product_name,
                }
            )
        return merged_rows

    @staticmethod
    def models_from_action_result(result: object) -> list[dict]:
        if result is None:
            return []
        data = None
        if hasattr(result, "data"):
            try:
                data = result.data
            except Exception:
                data = None
        if data is None and isinstance(result, dict):
            data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            models = data.get("models")
        elif isinstance(result, dict) and isinstance(result.get("models"), list):
            models = result.get("models")
        else:
            models = None
        if not isinstance(models, list):
            return []
        normalized: list[dict] = []
        for entry in models:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            model_path = str(entry.get("model_path", "") or entry.get("path", "")).strip()
            if not model_id and not model_path:
                continue
            product = str(entry.get("product_name", "") or entry.get("name", "") or entry.get("label", "")).strip()
            enabled = entry.get("enabled")
            # Preserve additional metadata provided by plugins (download/source URLs, file, quant, flags).
            row = dict(entry)
            row.pop("favorite", None)
            row.pop("recommended", None)
            row.pop("recommended_by_team", None)
            row.pop("favorite_by_default", None)
            row["model_id"] = model_id
            row["model_path"] = model_path
            row["product_name"] = product or model_id or model_path
            if enabled is None:
                row.pop("enabled", None)
            else:
                row["enabled"] = bool(enabled)
            row["installed"] = entry.get("installed")
            row["status"] = str(entry.get("status", "") or "").strip()
            row["observed_success"] = ModelCatalogController._coerce_model_observed_success(row)
            row["availability_status"] = ModelCatalogController._normalize_availability_status(row)
            normalized.append(row)
        return normalized

    def llm_enabled_models_from_stage(
        self,
        *,
        plugin_id: str,
        stage_params: dict,
        variants: object,
        providers: list[str],
    ) -> tuple[dict[str, list[str]], str]:
        enabled: dict[str, list[str]] = {}
        selected_provider = ""
        variant_state = parse_variant_selection_state(variants)
        seen_plugins: set[str] = set()

        for pid in variant_state.plugin_ids:
            if pid in seen_plugins:
                continue
            seen_plugins.add(pid)
            keys = variant_state.selection_keys_by_plugin.get(pid, [])
            params_list = variant_state.selection_params_by_plugin.get(pid, [])
            for index, key in enumerate(keys):
                params = params_list[index] if index < len(params_list) else variant_state.params_by_plugin.get(pid, {})
                if not key:
                    continue
                if not self.is_model_selection_available(pid, params):
                    continue
                enabled.setdefault(pid, []).append(key)
                if not selected_provider:
                    selected_provider = pid

        if not enabled and plugin_id:
            selected_provider = plugin_id
            model_path = str(stage_params.get("model_path", "") or "").strip()
            model_id = str(stage_params.get("model_id", "") or stage_params.get("model", "") or "").strip()
            key = selection_key(model_id=model_id, model_path=model_path)
            if key and self.is_model_selection_available(plugin_id, stage_params):
                enabled.setdefault(plugin_id, []).append(key)

        if not selected_provider:
            selected_provider = providers[0] if providers else ""

        return enabled, selected_provider

    def llm_provider_models_payload(
        self,
        providers: list[str],
        *,
        enabled_models: dict[str, list[str]] | None = None,
        available_only: bool = False,
        favorites_only: bool = False,
    ) -> dict[str, list[dict]]:
        enabled_models = enabled_models or {}
        payload: dict[str, list[dict]] = {}
        for pid in providers:
            pid = str(pid or "").strip()
            if not pid:
                continue
            models = self.llm_installed_models_payload(pid)
            enabled_keys = {str(key or "").strip() for key in enabled_models.get(pid, []) if str(key or "").strip()}
            requires_installed = self._requires_installed_selection(pid)
            if available_only:
                filtered: list[dict] = []
                for model in models:
                    if not isinstance(model, dict):
                        continue
                    key = self._model_payload_key(model)
                    if favorites_only and not self._coerce_model_favorite(model):
                        continue
                    if self._is_model_available_for_selection(model):
                        filtered.append(model)
                        continue
                    # For local/providers that require installed models, never keep stale
                    # stage selections visible after the file was removed from disk.
                    if not requires_installed and key and key in enabled_keys:
                        filtered.append(model)
                models = filtered
            elif favorites_only:
                models = [model for model in models if isinstance(model, dict) and self._coerce_model_favorite(model)]

            by_key: dict[str, dict] = {}
            ordered: list[str] = []
            for model in models:
                key = f"path:{model.get('model_path')}" if model.get("model_path") else f"id:{model.get('model_id')}"
                if key in by_key:
                    continue
                by_key[key] = model
                ordered.append(key)
            models = [by_key[k] for k in ordered]
            payload[pid] = models
        return payload

    def available_models_payload(self, plugin_id: str) -> list[dict]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return []
        return [
            dict(entry)
            for entry in self.llm_installed_models_payload(pid)
            if isinstance(entry, dict) and self._is_model_available_for_selection(entry)
        ]

    def favorite_models_payload(self, plugin_id: str) -> list[dict]:
        return self.available_models_payload(plugin_id)

    def llm_installed_models_payload(self, plugin_id: str) -> list[dict]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return []
        models_caps = self._models_caps(pid)
        is_local_plugin = self._is_local_models_plugin(pid)
        has_local_files = isinstance(models_caps.get("local_files"), dict)
        now = time.monotonic()
        cached = None if has_local_files else self._llm_models_cache.get(pid)
        if cached and (now - cached[0]) < 8.0:
            return list(cached[1])

        requires_installed = self._requires_installed_selection(pid)

        settings_rows = self.load_plugin_models_config(pid)
        if is_local_plugin and has_local_files:
            filesystem_models = self.local_models_from_capabilities(pid)
            models = self._local_models_payload_from_filesystem(
                settings_rows,
                filesystem_models,
                only_installed=requires_installed,
            )
        else:
            models = self._models_payload_from_rows(settings_rows, only_installed=requires_installed)
        self._llm_models_cache[pid] = (now, list(models))
        return models

    def local_models_from_capabilities(self, plugin_id: str) -> list[dict]:
        models_caps = self._models_caps(plugin_id)
        local = models_caps.get("local_files") if isinstance(models_caps, dict) else None
        if not isinstance(local, dict):
            return []
        glob = str(local.get("glob", "") or "").strip() or "*.gguf"
        default_root = str(local.get("default_root", "") or "").strip()
        root_setting = str(local.get("root_setting", "") or "").strip()

        root_value = ""
        if root_setting:
            settings = self._settings_store.get_settings(plugin_id, include_secrets=False)
            if isinstance(settings, dict):
                root_value = str(settings.get(root_setting, "") or "").strip()
        if not root_value:
            root_value = default_root
        if not root_value:
            return []

        root = (self._app_root / root_value).resolve() if not Path(root_value).is_absolute() else Path(root_value)
        if not root.exists() or not root.is_dir():
            return []
        file_index = self._local_model_file_index(plugin_id)
        models: list[dict] = []
        for path in sorted(root.glob(glob)):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(self._app_root)
                model_path = str(rel).replace("\\", "/")
            except Exception:
                model_path = str(path)
            file_name = path.name
            matched = file_index.get(file_name.lower(), {})
            model_id = str(matched.get("model_id", "") or "").strip()
            product_name = str(matched.get("product_name", "") or "").strip() or file_name
            models.append(
                {
                    "label": product_name,
                    "product_name": product_name,
                    "model_id": model_id,
                    "model_path": model_path,
                    "file": file_name,
                    "installed": True,
                    "status": "installed",
                    "availability_status": "ready",
                }
            )
        return models

    def _local_model_file_index(self, plugin_id: str) -> dict[str, dict[str, str]]:
        pid = str(plugin_id or "").strip()
        if not pid:
            return {}
        index: dict[str, dict[str, str]] = {}

        def _add(model_id: object, file_name: object, product_name: object) -> None:
            mid = str(model_id or "").strip()
            file_key = str(file_name or "").strip().lower()
            if not mid or not file_key or file_key in index:
                return
            label = str(product_name or "").strip() or mid
            index[file_key] = {"model_id": mid, "product_name": label}

        plugin = self._get_catalog().plugin_by_id(pid)
        model_info = plugin.model_info if plugin and isinstance(plugin.model_info, dict) else {}
        if isinstance(model_info, dict):
            for model_id, meta in model_info.items():
                if not isinstance(meta, dict):
                    continue
                _add(model_id, meta.get("file"), meta.get("model_name") or meta.get("product_name"))

        settings = self._settings_store.get_settings(pid, include_secrets=False)
        rows = settings.get("models") if isinstance(settings, dict) else None
        if isinstance(rows, list):
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                _add(
                    entry.get("model_id") or entry.get("id"),
                    entry.get("file") or entry.get("filename"),
                    entry.get("product_name") or entry.get("name") or entry.get("label"),
                )
        return index

    def _models_caps(self, plugin_id: str) -> dict:
        pid = str(plugin_id or "").strip()
        if not pid:
            return {}
        plugin = self._get_catalog().plugin_by_id(pid)
        capabilities = plugin.capabilities if plugin and isinstance(plugin.capabilities, dict) else {}
        models_caps = capabilities.get("models") if isinstance(capabilities, dict) else None
        return dict(models_caps) if isinstance(models_caps, dict) else {}

    def _is_local_models_plugin(self, plugin_id: str) -> bool:
        caps = self._models_caps(plugin_id)
        storage = str(caps.get("storage", "") or "").strip().lower()
        if storage == "local":
            return True
        return isinstance(caps.get("local_files"), dict)

    def _requires_installed_selection(self, plugin_id: str) -> bool:
        caps = self._models_caps(plugin_id)
        raw = caps.get("selection_requires_installed")
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return self._is_local_models_plugin(plugin_id)

    def is_local_models_plugin(self, plugin_id: str) -> bool:
        return self._is_local_models_plugin(plugin_id)

    def is_model_selection_available(self, plugin_id: str, params: dict | None) -> bool:
        pid = str(plugin_id or "").strip()
        if not pid:
            return False
        if not isinstance(params, dict):
            return True
        model_path = str(params.get("model_path", "") or "").strip()
        model_id = str(params.get("model_id", "") or params.get("model", "") or "").strip()
        key = selection_key(model_id=model_id, model_path=model_path)
        if not key:
            return True
        if not self._requires_installed_selection(pid):
            rows = self.load_plugin_models_config(pid)
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                entry_model_path = str(entry.get("model_path", "") or entry.get("path", "")).strip()
                entry_model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
                entry_key = selection_key(model_id=entry_model_id, model_path=entry_model_path)
                if entry_key != key:
                    continue
                return self._is_model_available_for_selection(entry)
            return True
        installed = self.llm_installed_models_payload(pid)
        return any(self._installed_model_matches(item, model_id=model_id, model_path=model_path) for item in installed)

    @staticmethod
    def _installed_model_matches(entry: object, *, model_id: str, model_path: str) -> bool:
        if not isinstance(entry, dict):
            return False
        entry_model_path = str(entry.get("model_path", "") or entry.get("path", "")).strip()
        entry_model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if model_path and entry_model_path == model_path:
            return True
        if model_id and entry_model_id == model_id:
            return True
        return False

    @staticmethod
    def _coerce_model_installed(entry: dict) -> bool | None:
        installed = entry.get("installed")
        if isinstance(installed, bool):
            return installed
        status = str(entry.get("status", "") or "").strip().lower()
        if status in {"installed", "enabled", "ready"}:
            return True
        if status in {"not_installed", "missing", "available"}:
            return False
        return None

    @staticmethod
    def _coerce_boolish(value: object) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return None

    @classmethod
    def _coerce_model_favorite(cls, entry: dict) -> bool:
        explicit = cls._coerce_boolish(entry.get("favorite"))
        if explicit is not None:
            return explicit
        legacy = cls._coerce_boolish(entry.get("enabled"))
        return bool(legacy)

    @classmethod
    def _coerce_model_default_favorite(cls, entry: dict) -> bool:
        for key in ("favorite_by_default", "default_favorite"):
            value = cls._coerce_boolish(entry.get(key))
            if value is not None:
                return value
        return False

    @classmethod
    def _coerce_model_recommended(cls, entry: dict) -> bool:
        for key in ("recommended_by_team", "recommended", "default", "curated"):
            value = cls._coerce_boolish(entry.get(key))
            if value is not None:
                return value
        return str(entry.get("catalog_source", "") or "").strip().lower() == "recommended"

    @classmethod
    def _coerce_model_observed_success(cls, entry: dict) -> bool:
        explicit = cls._coerce_boolish(entry.get("observed_success"))
        if explicit is not None:
            return explicit
        quality = str(entry.get("last_pipeline_quality", "") or "").strip().lower()
        if quality == "usable":
            return True
        last_ok_at = int(entry.get("last_ok_at", 0) or 0)
        return last_ok_at > 0

    @classmethod
    def _is_model_available_for_selection(cls, entry: dict) -> bool:
        if not isinstance(entry, dict):
            return False
        availability = cls._normalize_availability_status(entry)
        selectable = entry.get("selectable")
        if isinstance(selectable, bool) and not selectable:
            if cls._coerce_boolish(entry.get("blocked_for_account")) is True:
                return False
            failure = str(entry.get("last_failure_code", "") or entry.get("failure_code", "") or "").strip().lower()
            if failure in {"provider_blocked", "auth_error", "model_not_found", "not_available"}:
                return False
            if availability in {"needs_setup", "unavailable"}:
                return False
            if failure in {
                "rate_limited",
                "cooling_down",
                "cooldown",
                "quota_limited",
                "transport_error",
                "network_error",
                "timeout",
                "empty_response",
                "request_failed",
                "llm_degraded_summary_artifact",
            }:
                # Keep explicitly selected cloud models runnable/visible while a transient
                # provider-side cooldown is in effect. They should not silently disappear
                # from the stage config after the user presses Run.
                return True
            cooldown_until = int(entry.get("cooldown_until", 0) or 0)
            if cooldown_until > int(time.time()):
                return False
            return False
        installed = cls._coerce_model_installed(entry)
        if installed is True:
            return True
        return availability in {"ready", "unknown", "limited"}

    @classmethod
    def _normalize_availability_status(cls, entry: dict) -> str:
        now_ts = int(time.time())
        cooldown_until = int(entry.get("cooldown_until", 0) or 0)
        if cooldown_until > now_ts:
            return "limited"
        if cls._coerce_boolish(entry.get("blocked_for_account")) is True:
            return "unavailable"
        raw = str(entry.get("availability_status", "") or entry.get("status", "") or "").strip().lower()
        failure = str(entry.get("last_failure_code", "") or entry.get("failure_code", "") or "").strip().lower()
        transient_failure = failure in {
            "rate_limited",
            "cooling_down",
            "cooldown",
            "quota_limited",
            "transport_error",
            "network_error",
            "timeout",
            "empty_response",
            "request_failed",
            "llm_degraded_summary_artifact",
        }
        if raw in cls._STATUS_READY:
            return "ready"
        if raw in cls._STATUS_NEEDS_SETUP:
            return "needs_setup"
        if raw in cls._STATUS_LIMITED:
            if cooldown_until <= now_ts and transient_failure:
                return "unknown"
            return "limited"
        if raw in cls._STATUS_UNAVAILABLE:
            return "unavailable"
        installed = cls._coerce_model_installed(entry)
        if installed is True:
            return "ready"
        if installed is False:
            return "needs_setup"
        return "unknown"

    @classmethod
    def _apply_default_favorites(cls, rows: list[dict]) -> list[dict]:
        return [dict(entry) for entry in rows if isinstance(entry, dict)]

    @classmethod
    def _eligible_for_default_favorite(cls, entry: dict) -> bool:
        if cls._coerce_boolish(entry.get("blocked_for_account")) is True:
            return False
        cooldown_until = int(entry.get("cooldown_until", 0) or 0)
        if cooldown_until > int(time.time()):
            return False
        quality = str(entry.get("last_pipeline_quality", "") or "").strip().lower()
        if quality == "degraded":
            return False
        streak = int(entry.get("pipeline_failure_streak", 0) or 0)
        failure_code = str(entry.get("last_failure_code", "") or entry.get("failure_code", "") or "").strip().lower()
        if streak >= 2 and failure_code in {
            "rate_limited",
            "provider_blocked",
            "timeout",
            "transport_error",
            "network_error",
            "empty_response",
            "request_failed",
            "llm_degraded_summary_artifact",
        }:
            return False
        return True

    @classmethod
    def _migrate_model_settings_rows(cls, rows: list[dict]) -> tuple[list[dict], bool]:
        normalized_rows = [dict(entry) for entry in rows if isinstance(entry, dict)]
        migrated: list[dict] = []
        changed = False
        for original, entry in zip(rows, normalized_rows):
            row = dict(entry)
            availability = cls._normalize_availability_status(row)
            if str(row.get("availability_status", "") or "").strip().lower() != availability:
                row["availability_status"] = availability
            if row != dict(original):
                changed = True
            migrated.append(row)
        return migrated, changed

    def _persist_migrated_model_rows(self, plugin_id: str, settings: dict | object, rows: list[dict]) -> None:
        pid = str(plugin_id or "").strip()
        if not pid or not isinstance(settings, dict):
            return
        try:
            merged = dict(settings)
            merged["models"] = list(rows or [])
            preserve = [
                key
                for key in self._settings_store.get_settings(pid, include_secrets=True).keys()
                if self._is_secret_field_name(key)
            ]
            self._settings_store.set_settings(pid, merged, secret_fields=[], preserve_secrets=preserve)
        except Exception:
            return

    def _list_models_action_id(self, plugin_id: str, models_caps: dict) -> str:
        managed = models_caps.get("managed_actions") if isinstance(models_caps, dict) else None
        if isinstance(managed, dict):
            action_id = str(managed.get("list", "") or "").strip()
            if action_id:
                return action_id
        # Fallback is intentionally broad; for plugins without this action
        # invoke_action will fail and we fallback to stored settings.
        return "list_models"

    @staticmethod
    def _action_status(result: object) -> str:
        if isinstance(result, dict):
            return str(result.get("status", "") or "").strip().lower()
        return str(getattr(result, "status", "") or "").strip().lower()

    def _load_models_from_action(self, plugin_id: str, action_id: str) -> list[dict] | None:
        pid = str(plugin_id or "").strip()
        aid = str(action_id or "").strip()
        if not pid or not aid:
            return None
        try:
            result = self._action_service.invoke_action(pid, aid, {})
        except Exception:
            return None
        status = self._action_status(result)
        if status and status not in {"ok", "success"}:
            return None
        models = self.models_from_action_result(result)
        return list(models)

    def _persist_models_config(self, plugin_id: str, models: list[dict]) -> None:
        pid = str(plugin_id or "").strip()
        if not pid:
            return
        try:
            current_plain = self._settings_store.get_settings(pid, include_secrets=False)
            merged = dict(current_plain) if isinstance(current_plain, dict) else {}
            incoming_models = self._merge_persisted_user_model_state(
                current_plain.get("models") if isinstance(current_plain, dict) else None,
                list(models or []),
            )
            normalized_models, _changed = self._migrate_model_settings_rows(incoming_models)
            merged["models"] = normalized_models
            if self._is_local_models_plugin(pid):
                merged[self._MODELS_META_KEY] = {
                    "host_id": self._host_id,
                    "updated_at": int(time.time()),
                }
            preserve = [
                key
                for key in self._settings_store.get_settings(pid, include_secrets=True).keys()
                if self._is_secret_field_name(key)
            ]
            self._settings_store.set_settings(pid, merged, secret_fields=[], preserve_secrets=preserve)
        except Exception:
            return

    @classmethod
    def _merge_persisted_user_model_state(cls, current_rows: object, incoming_rows: list[dict]) -> list[dict]:
        existing_by_key: dict[str, dict] = {}
        if isinstance(current_rows, list):
            for entry in current_rows:
                if not isinstance(entry, dict):
                    continue
                key = cls._model_payload_key(entry)
                if key:
                    existing_by_key[key] = dict(entry)

        merged_rows: list[dict] = []
        for entry in incoming_rows:
            if not isinstance(entry, dict):
                continue
            row = dict(entry)
            key = cls._model_payload_key(row)
            existing = existing_by_key.get(key, {}) if key else {}
            explicit_favorite = cls._coerce_boolish(existing.get("favorite"))
            explicit_enabled = cls._coerce_boolish(existing.get("enabled"))
            if explicit_favorite is not None:
                row["favorite"] = explicit_favorite
            if explicit_enabled is not None:
                row["enabled"] = explicit_enabled
            merged_rows.append(row)
        return merged_rows

    def _models_payload_from_rows(self, rows: list[dict], *, only_installed: bool) -> list[dict]:
        payload = self._models_payload_from_rows_static(rows)
        if not only_installed:
            return payload
        return [entry for entry in payload if self._coerce_model_installed(entry) is True]

    @classmethod
    def _models_payload_from_rows_static(cls, rows: list[dict]) -> list[dict]:
        payload: list[dict] = []
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
            model_path = str(entry.get("model_path", "") or entry.get("path", "")).strip()
            if not model_id and not model_path:
                continue
            label = str(entry.get("product_name", "") or entry.get("name", "") or entry.get("label", "")).strip()
            if not label:
                label = model_id or (Path(model_path).name if model_path else "")
            payload.append(
                {
                    "label": label,
                    "product_name": label,
                    "model_id": model_id,
                    "model_path": model_path,
                    "file": str(entry.get("file", "") or entry.get("filename", "")).strip(),
                    "installed": cls._coerce_model_installed(entry),
                    "status": str(entry.get("status", "") or "").strip(),
                    "enabled": bool(entry.get("enabled", False)),
                    "observed_success": cls._coerce_model_observed_success(entry),
                    "availability_status": cls._normalize_availability_status(entry),
                    "failure_code": str(entry.get("failure_code", "") or "").strip(),
                    "selectable": entry.get("selectable"),
                    "cooldown_until": int(entry.get("cooldown_until", 0) or 0),
                    "blocked_for_account": bool(entry.get("blocked_for_account", False)),
                    "last_pipeline_quality": str(entry.get("last_pipeline_quality", "") or "").strip(),
                    "last_pipeline_at": int(entry.get("last_pipeline_at", 0) or 0),
                    "last_failure_code": str(entry.get("last_failure_code", "") or "").strip(),
                    "last_failure_at": int(entry.get("last_failure_at", 0) or 0),
                }
            )
        return payload

    @staticmethod
    def _model_payload_key(entry: dict) -> str:
        model_id = str(entry.get("model_id", "") or "").strip()
        if model_id:
            return f"id:{model_id}"
        model_path = str(entry.get("model_path", "") or "").strip()
        if model_path:
            return f"path:{model_path}"
        return ""

    @classmethod
    def _merge_local_models_payload(cls, primary: list[dict], discovered: list[dict]) -> list[dict]:
        if not primary:
            return list(discovered)
        if not discovered:
            return list(primary)

        merged: list[dict] = []
        seen_keys: set[str] = set()
        seen_files: set[str] = set()

        def add(entry: dict) -> None:
            key = cls._model_payload_key(entry)
            file_name = str(entry.get("file", "") or "").strip().lower()
            if key and key in seen_keys:
                return
            if file_name and file_name in seen_files:
                return
            merged.append(dict(entry))
            if key:
                seen_keys.add(key)
            if file_name:
                seen_files.add(file_name)

        for row in primary:
            add(row)
        for row in discovered:
            add(row)
        return merged

    @classmethod
    def _local_models_payload_from_filesystem(
        cls,
        settings_rows: list[dict],
        discovered: list[dict],
        *,
        only_installed: bool,
    ) -> list[dict]:
        settings_payload = cls._models_payload_from_rows_static(settings_rows)
        if not discovered:
            return [] if only_installed else settings_payload

        settings_by_key = {
            cls._model_payload_key(entry): dict(entry)
            for entry in settings_payload
            if isinstance(entry, dict) and cls._model_payload_key(entry)
        }
        settings_by_file = {
            str(entry.get("file", "") or "").strip().lower(): dict(entry)
            for entry in settings_payload
            if isinstance(entry, dict) and str(entry.get("file", "") or "").strip()
        }

        merged: list[dict] = []
        for entry in discovered:
            if not isinstance(entry, dict):
                continue
            row = dict(entry)
            matched = settings_by_key.get(cls._model_payload_key(row))
            if matched is None:
                file_name = str(row.get("file", "") or "").strip().lower()
                if file_name:
                    matched = settings_by_file.get(file_name)
            if isinstance(matched, dict):
                preferred_label = str(matched.get("product_name", "") or matched.get("label", "")).strip()
                if preferred_label:
                    row["label"] = preferred_label
                    row["product_name"] = preferred_label
                for key in (
                    "enabled",
                    "observed_success",
                    "last_pipeline_quality",
                    "last_pipeline_at",
                    "last_failure_code",
                    "last_failure_at",
                ):
                    if key in matched:
                        row[key] = matched.get(key)
            merged.append(row)
        return merged

    @staticmethod
    def _current_host_id() -> str:
        try:
            value = str(socket.gethostname() or "").strip().lower()
        except Exception:
            value = ""
        return value or "unknown"

    def _is_local_models_cache_trusted(self, settings: dict | object) -> bool:
        if not isinstance(settings, dict):
            return False
        meta = settings.get(self._MODELS_META_KEY)
        if not isinstance(meta, dict):
            return False
        stored_host = str(meta.get("host_id", "") or "").strip().lower()
        current_host = str(self._host_id or "").strip().lower()
        return bool(stored_host and current_host and stored_host == current_host)
