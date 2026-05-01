from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aimn.ui.controllers.stage_model_normalization import normalize_stage_variants


class PipelineRuntimeConfigController:
    @staticmethod
    def restore_required_stage_plugins(
        config_data: dict[str, object],
        *,
        default_plugin_for_stage: Callable[[str], Any | None],
    ) -> bool:
        stages = config_data.get("stages")
        changed = False
        if not isinstance(stages, dict):
            stages = {}
            config_data["stages"] = stages
            changed = True

        changed = (
            PipelineRuntimeConfigController._restore_management_stage(
                stages,
                default_plugin_for_stage=default_plugin_for_stage,
            )
            or changed
        )
        changed = (
            PipelineRuntimeConfigController._restore_service_stage(
                stages,
                default_plugin_for_stage=default_plugin_for_stage,
            )
            or changed
        )
        return changed

    @staticmethod
    def _restore_management_stage(
        stages: dict[str, object],
        *,
        default_plugin_for_stage: Callable[[str], Any | None],
    ) -> bool:
        stage = stages.get("management")
        if isinstance(stage, dict):
            plugin_ids = stage.get("plugin_ids")
            if isinstance(plugin_ids, list) and any(str(item or "").strip() for item in plugin_ids):
                return False
        else:
            stage = {}
            stages["management"] = stage

        plugin = default_plugin_for_stage("management")
        plugin_id = str(getattr(plugin, "plugin_id", "") or "").strip()
        if not plugin_id:
            return False

        changed = False
        if stage.get("plugin_ids") != [plugin_id]:
            stage["plugin_ids"] = [plugin_id]
            changed = True
        if "plugin_id" in stage:
            stage.pop("plugin_id", None)
            changed = True
        if "module" in stage:
            stage.pop("module", None)
            changed = True
        if "class" in stage:
            stage.pop("class", None)
            changed = True
        params = stage.get("params")
        if not isinstance(params, dict):
            stage["params"] = {}
            changed = True
        return changed

    @staticmethod
    def _restore_service_stage(
        stages: dict[str, object],
        *,
        default_plugin_for_stage: Callable[[str], Any | None],
    ) -> bool:
        stage = stages.get("service")
        if isinstance(stage, dict):
            plugin_id = str(stage.get("plugin_id", "") or "").strip()
            if plugin_id:
                return False
        else:
            stage = {}
            stages["service"] = stage

        plugin = default_plugin_for_stage("service")
        plugin_id = str(getattr(plugin, "plugin_id", "") or "").strip()
        if not plugin_id:
            return False

        changed = False
        if stage.get("plugin_id") != plugin_id:
            stage["plugin_id"] = plugin_id
            changed = True

        module = str(getattr(plugin, "module", "") or "").strip()
        if module:
            if stage.get("module") != module:
                stage["module"] = module
                changed = True
        elif "module" in stage:
            stage.pop("module", None)
            changed = True

        class_name = str(getattr(plugin, "class_name", "") or "").strip()
        if class_name:
            if stage.get("class") != class_name:
                stage["class"] = class_name
                changed = True
        elif "class" in stage:
            stage.pop("class", None)
            changed = True

        params = stage.get("params")
        if not isinstance(params, dict):
            stage["params"] = {}
            changed = True
        return changed

    @staticmethod
    def _check_params(check: dict) -> dict:
        params = check.get("params")
        return dict(params) if isinstance(params, dict) else {}

    @staticmethod
    def _variant_matches(entry: object, *, plugin_id: str, params: dict) -> bool:
        if not isinstance(entry, dict):
            return False
        pid = str(entry.get("plugin_id", "") or "").strip()
        if plugin_id and pid != plugin_id:
            return False
        entry_params = entry.get("params")
        normalized_params = dict(entry_params) if isinstance(entry_params, dict) else {}
        if params:
            return normalized_params == params
        return True

    @staticmethod
    def prune_unavailable_plugins(
        config_data: dict[str, object],
        *,
        plugin_available: Callable[[str], bool],
    ) -> bool:
        stages = config_data.get("stages")
        if not isinstance(stages, dict):
            return False
        changed = False
        for stage_id, stage in stages.items():
            if not isinstance(stage, dict):
                continue

            plugin_ids = stage.get("plugin_ids")
            if isinstance(plugin_ids, list):
                normalized_plugin_ids = [str(item).strip() for item in plugin_ids if str(item).strip()]
                filtered_plugin_ids = [pid for pid in normalized_plugin_ids if bool(plugin_available(pid))]
                if filtered_plugin_ids:
                    if plugin_ids != filtered_plugin_ids:
                        stage["plugin_ids"] = filtered_plugin_ids
                        changed = True
                elif plugin_ids:
                    stage.pop("plugin_ids", None)
                    changed = True

            variants = stage.get("variants")
            if isinstance(variants, list):
                filtered_variants: list[dict] = []
                for entry in variants:
                    if not isinstance(entry, dict):
                        continue
                    pid = str(entry.get("plugin_id", "") or "").strip()
                    if not pid:
                        continue
                    if not bool(plugin_available(pid)):
                        changed = True
                        continue
                    filtered_variants.append(dict(entry))
                if filtered_variants != variants:
                    stage["variants"] = filtered_variants
                    changed = True
                if not filtered_variants:
                    stage.pop("variants", None)

            plugin_id = str(stage.get("plugin_id", "") or "").strip()
            if plugin_id and not bool(plugin_available(plugin_id)):
                stage.pop("plugin_id", None)
                stage.pop("module", None)
                stage.pop("class", None)
                changed = True

            if str(stage_id or "").strip() == "transcription" and "variants" in stage:
                current_plugin_id = str(stage.get("plugin_id", "") or "").strip()
                if current_plugin_id:
                    continue
                candidates = stage.get("variants")
                if not isinstance(candidates, list):
                    continue
                first = next(
                    (
                        str(item.get("plugin_id", "") or "").strip()
                        for item in candidates
                        if isinstance(item, dict) and str(item.get("plugin_id", "") or "").strip()
                    ),
                    "",
                )
                if first:
                    stage["plugin_id"] = first
                    changed = True
        return changed

    @staticmethod
    def build_runtime_config(
        config_data: dict[str, object],
        *,
        pipeline_preset: str,
        sanitize_params_for_plugin: Callable[[str, dict], dict[str, object]],
        model_available_for_plugin: Callable[[str, dict], bool] | None = None,
        compute_llm_prompt_signature: Callable[[str, str], str] | None = None,
    ) -> dict[str, object]:
        payload = dict(config_data)
        pipeline = payload.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
        pipeline["preset"] = pipeline_preset
        payload["pipeline"] = pipeline
        PipelineRuntimeConfigController.sanitize_runtime_config(
            payload,
            sanitize_params_for_plugin=sanitize_params_for_plugin,
            model_available_for_plugin=model_available_for_plugin,
            compute_llm_prompt_signature=compute_llm_prompt_signature,
        )
        return payload

    @staticmethod
    def sanitize_runtime_config(
        payload: dict[str, object],
        *,
        sanitize_params_for_plugin: Callable[[str, dict], dict[str, object]],
        model_available_for_plugin: Callable[[str, dict], bool] | None = None,
        compute_llm_prompt_signature: Callable[[str, str], str] | None = None,
    ) -> None:
        stages = payload.get("stages")
        if not isinstance(stages, dict):
            return
        for _stage_id, stage in stages.items():
            if not isinstance(stage, dict):
                continue
            stage_id = str(_stage_id or "").strip()
            plugin_id = str(stage.get("plugin_id", "") or "").strip()
            params = stage.get("params")
            if isinstance(params, dict):
                if plugin_id and stage_id != "management":
                    sanitized_params = sanitize_params_for_plugin(plugin_id, params)
                    if (
                        model_available_for_plugin
                        and stage_id != "transcription"
                        and not model_available_for_plugin(plugin_id, sanitized_params)
                    ):
                        stage.pop("plugin_id", None)
                        stage.pop("module", None)
                        stage.pop("class", None)
                else:
                    sanitized_params = dict(params)
                if stage_id == "llm_processing":
                    sanitized_params = PipelineRuntimeConfigController._with_llm_prompt_signature(
                        sanitized_params,
                        compute_signature=compute_llm_prompt_signature,
                    )
                stage["params"] = sanitized_params
            variants = stage.get("variants")
            if not isinstance(variants, list):
                continue
            normalized_variants = normalize_stage_variants(
                variants,
                sanitize_params_for_plugin=sanitize_params_for_plugin,
            )
            if model_available_for_plugin and stage_id != "transcription":
                normalized_variants = [
                    entry
                    for entry in normalized_variants
                    if model_available_for_plugin(
                        str(entry.get("plugin_id", "") or "").strip(),
                        dict(entry.get("params", {})) if isinstance(entry.get("params"), dict) else {},
                    )
                ]
            stage["variants"] = normalized_variants

    @staticmethod
    def _with_llm_prompt_signature(
        params: dict[str, object],
        *,
        compute_signature: Callable[[str, str], str] | None = None,
    ) -> dict[str, object]:
        merged = dict(params)
        if not compute_signature:
            return merged
        profile_id = str(merged.get("prompt_profile", "") or "").strip()
        custom_prompt = str(merged.get("prompt_custom", "") or "")
        try:
            signature = str(compute_signature(profile_id, custom_prompt) or "").strip()
        except Exception:
            return merged
        if signature:
            merged["prompt_signature"] = signature
        else:
            merged.pop("prompt_signature", None)
        return merged

    @staticmethod
    def disable_stage_in_runtime_config(runtime_config: dict[str, object], stage_id: str) -> None:
        pipeline = runtime_config.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
            runtime_config["pipeline"] = pipeline
        raw = pipeline.get("disabled_stages")
        disabled = set(raw) if isinstance(raw, list) else set()
        disabled.add(stage_id)
        pipeline["disabled_stages"] = sorted({str(item) for item in disabled if str(item)})

    @staticmethod
    def disable_stage_in_preset(config_data: dict[str, object], stage_id: str) -> None:
        pipeline = config_data.get("pipeline")
        if not isinstance(pipeline, dict):
            pipeline = {}
            config_data["pipeline"] = pipeline
        raw = pipeline.get("disabled_stages")
        disabled = set(raw) if isinstance(raw, list) else set()
        disabled.add(stage_id)
        pipeline["disabled_stages"] = sorted({str(item) for item in disabled if str(item)})

    @staticmethod
    def apply_skip_once(runtime_config: dict[str, object], check: dict) -> None:
        stage_id = str(check.get("stage_id", "") or "").strip()
        plugin_id = str(check.get("plugin_id", "") or "").strip()
        check_params = PipelineRuntimeConfigController._check_params(check)
        if not stage_id:
            return
        stages = runtime_config.get("stages")
        if not isinstance(stages, dict):
            return
        stage = stages.get(stage_id)
        if not isinstance(stage, dict):
            PipelineRuntimeConfigController.disable_stage_in_runtime_config(runtime_config, stage_id)
            return

        variant_index = check.get("variant_index")
        variants = stage.get("variants")
        if isinstance(variants, list):
            remove_idx: int | None = None

            if variant_index is not None:
                try:
                    idx = int(variant_index)
                except Exception:
                    idx = -1
                if 0 <= idx < len(variants):
                    candidate = variants[idx]
                    if PipelineRuntimeConfigController._variant_matches(
                        candidate,
                        plugin_id=plugin_id,
                        params=check_params,
                    ):
                        remove_idx = idx

            if remove_idx is None:
                for idx, entry in enumerate(variants):
                    if PipelineRuntimeConfigController._variant_matches(
                        entry,
                        plugin_id=plugin_id,
                        params=check_params,
                    ):
                        remove_idx = idx
                        break

            if remove_idx is None and plugin_id:
                for idx, entry in enumerate(variants):
                    if PipelineRuntimeConfigController._variant_matches(
                        entry,
                        plugin_id=plugin_id,
                        params={},
                    ):
                        remove_idx = idx
                        break

            if remove_idx is None:
                return

            variants.pop(remove_idx)
            if variants:
                stage["variants"] = variants
                return
            PipelineRuntimeConfigController.disable_stage_in_runtime_config(runtime_config, stage_id)
            return

        stage_plugin_id = str(stage.get("plugin_id", "") or "").strip()
        if not plugin_id or not stage_plugin_id or stage_plugin_id == plugin_id:
            PipelineRuntimeConfigController.disable_stage_in_runtime_config(runtime_config, stage_id)

    @staticmethod
    def apply_disable_preset(config_data: dict[str, object], check: dict) -> str:
        stage_id = str(check.get("stage_id", "") or "").strip()
        plugin_id = str(check.get("plugin_id", "") or "").strip()
        if not stage_id:
            return ""

        stages = config_data.get("stages")
        if not isinstance(stages, dict):
            stages = {}
            config_data["stages"] = stages
        stage = stages.get(stage_id)
        if not isinstance(stage, dict):
            stage = {}
            stages[stage_id] = stage

        variants = stage.get("variants")
        if isinstance(variants, list) and plugin_id:
            filtered = []
            for entry in variants:
                if not isinstance(entry, dict):
                    continue
                pid = str(entry.get("plugin_id", "") or "").strip()
                if pid != plugin_id:
                    filtered.append(entry)
            if filtered:
                stage["variants"] = filtered
                return stage_id

        PipelineRuntimeConfigController.disable_stage_in_preset(config_data, stage_id)
        return stage_id
