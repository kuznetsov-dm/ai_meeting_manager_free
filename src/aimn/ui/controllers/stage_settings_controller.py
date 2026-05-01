from __future__ import annotations

from typing import Callable

from aimn.ui.controllers.stage_model_normalization import normalize_stage_variants, parse_variant_selection_state


class StageSettingsController:
    @staticmethod
    def apply_stage_settings(
        config_data: dict[str, object],
        *,
        stage_id: str,
        payload: dict,
        supports_transcription_quality_presets: Callable[[str], bool],
        sanitize_params_for_plugin: Callable[[str, dict], dict[str, object]],
        get_plugin_by_id: Callable[[str], object | None],
        coerce_bool: Callable[[object], bool],
    ) -> tuple[str, str]:
        stages = config_data.setdefault("stages", {})
        if not isinstance(stages, dict):
            stages = {}
            config_data["stages"] = stages
        stage_config = stages.setdefault(stage_id, {})
        if not isinstance(stage_config, dict):
            stage_config = {}
            stages[stage_id] = stage_config

        prev_plugin_id = str(stage_config.get("plugin_id", "") or "").strip()
        plugin_id = str((payload or {}).get("plugin_id", "") or "").strip()
        variants = (payload or {}).get("variants")
        if isinstance(variants, list):
            normalized = normalize_stage_variants(
                variants,
                sanitize_params_for_plugin=sanitize_params_for_plugin,
            )
            variant_plugin_ids = parse_variant_selection_state(normalized).plugin_ids
            if normalized:
                stage_config["variants"] = normalized
            else:
                stage_config.pop("variants", None)
            if stage_id == "transcription":
                if plugin_id not in set(variant_plugin_ids) and variant_plugin_ids:
                    plugin_id = variant_plugin_ids[0]
            else:
                stage_config.pop("plugin_id", None)
                stage_config.pop("module", None)
                stage_config.pop("class", None)
                plugin_id = ""

        if plugin_id:
            stage_config["plugin_id"] = plugin_id
            plugin = get_plugin_by_id(plugin_id)
            if plugin is not None:
                stage_config["module"] = getattr(plugin, "module", "")
                stage_config["class"] = getattr(plugin, "class_name", "")

        params = (payload or {}).get("params")
        if isinstance(params, dict):
            if stage_id == "transcription" and supports_transcription_quality_presets(plugin_id):
                mapped = dict(params)
                mode = str(mapped.get("language_mode", "") or "").strip()
                if mode == "auto_two_pass":
                    mapped["language_mode"] = "auto"
                    mapped["two_pass"] = True
                mode = str(mapped.get("language_mode", "") or "").strip()
                two_pass = coerce_bool(mapped.get("two_pass"))
                mapped["two_pass"] = two_pass if mode in {"auto", "none"} else False
                if str(mapped.get("language_mode", "") or "").strip() == "forced":
                    code = str(mapped.get("language_code", "") or "").strip()
                    if not code:
                        mapped["language_code"] = "en"
                params = mapped

            current = stage_config.get("params", {})
            if not isinstance(current, dict):
                current = {}
            merged = dict(current)
            remove = (payload or {}).get("params_remove")
            if isinstance(remove, list):
                for key in remove:
                    clean_key = str(key or "").strip()
                    if clean_key:
                        merged.pop(clean_key, None)
            merged.update(params)
            effective_plugin_id = plugin_id or str(stage_config.get("plugin_id", "") or "").strip()
            if effective_plugin_id and stage_id != "management":
                merged = sanitize_params_for_plugin(effective_plugin_id, merged)
            stage_config["params"] = merged

        return prev_plugin_id, plugin_id

    @staticmethod
    def set_stage_enabled(config_data: dict[str, object], *, stage_id: str, enabled: bool) -> None:
        pipeline = config_data.get("pipeline", {})
        if not isinstance(pipeline, dict):
            pipeline = {}
            config_data["pipeline"] = pipeline
        disabled = pipeline.get("disabled_stages", [])
        if not isinstance(disabled, list):
            disabled = []
        disabled_set = {str(item or "").strip() for item in disabled if str(item or "").strip()}
        if enabled:
            disabled_set.discard(str(stage_id or "").strip())
        else:
            disabled_set.add(str(stage_id or "").strip())
        pipeline["disabled_stages"] = sorted(disabled_set)
