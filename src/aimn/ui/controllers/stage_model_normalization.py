from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


def selection_key(*, model_id: str = "", model_path: str = "") -> str:
    mid = str(model_id or "").strip()
    mpath = str(model_path or "").strip()
    if mpath:
        return f"path:{mpath}"
    if mid:
        return f"id:{mid}"
    return ""


@dataclass(frozen=True)
class VariantSelectionState:
    plugin_ids: list[str] = field(default_factory=list)
    params_by_plugin: dict[str, dict] = field(default_factory=dict)
    model_ids_by_plugin: dict[str, list[str]] = field(default_factory=dict)
    selection_keys_by_plugin: dict[str, list[str]] = field(default_factory=dict)
    selection_params_by_plugin: dict[str, list[dict]] = field(default_factory=dict)


def parse_variant_selection_state(variants: object) -> VariantSelectionState:
    plugin_ids: list[str] = []
    params_by_plugin: dict[str, dict] = {}
    model_ids_by_plugin: dict[str, list[str]] = {}
    selection_keys_by_plugin: dict[str, list[str]] = {}
    selection_params_by_plugin: dict[str, list[dict]] = {}

    if not isinstance(variants, list):
        return VariantSelectionState()

    for entry in variants:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("plugin_id", "") or "").strip()
        if not pid:
            continue
        plugin_ids.append(pid)
        params = entry.get("params")
        normalized_params = dict(params) if isinstance(params, dict) else {}
        if pid not in params_by_plugin and normalized_params:
            params_by_plugin[pid] = normalized_params
        model_path = str(normalized_params.get("model_path", "") or "").strip()
        model_id = str(normalized_params.get("model_id", "") or normalized_params.get("model", "") or "").strip()
        if model_id:
            model_ids_by_plugin.setdefault(pid, []).append(model_id)
        key = selection_key(model_id=model_id, model_path=model_path)
        if key:
            selection_keys_by_plugin.setdefault(pid, []).append(key)
            selection_params_by_plugin.setdefault(pid, []).append(normalized_params)

    return VariantSelectionState(
        plugin_ids=plugin_ids,
        params_by_plugin=params_by_plugin,
        model_ids_by_plugin=model_ids_by_plugin,
        selection_keys_by_plugin=selection_keys_by_plugin,
        selection_params_by_plugin=selection_params_by_plugin,
    )


def normalize_stage_variants(
    variants: object,
    *,
    sanitize_params_for_plugin: Callable[[str, dict], dict[str, object]] | None = None,
) -> list[dict]:
    normalized: list[dict] = []
    if not isinstance(variants, list):
        return normalized
    for entry in variants:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("plugin_id", "") or "").strip()
        if not pid:
            continue
        params = entry.get("params")
        normalized_params = dict(params) if isinstance(params, dict) else {}
        if sanitize_params_for_plugin is not None:
            normalized_params = sanitize_params_for_plugin(pid, normalized_params)
        normalized.append({"plugin_id": pid, "params": normalized_params})
    return normalized
