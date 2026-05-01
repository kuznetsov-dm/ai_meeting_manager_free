from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable


OFFLINE_PRESET_ID = "offline"


def offline_preset_config(app_root: Path, optional_stage_retries: int = 1) -> dict:
    data = _load_offline_preset(app_root)
    if not data:
        return {
            "pipeline": {
                "optional_stage_retries": max(0, int(optional_stage_retries)),
                "preset": OFFLINE_PRESET_ID,
            },
            "stages": {},
        }
    pipeline = data.get("pipeline", {})
    if not isinstance(pipeline, dict):
        pipeline = {}
    pipeline = dict(pipeline)
    pipeline["preset"] = OFFLINE_PRESET_ID
    pipeline["optional_stage_retries"] = max(0, int(optional_stage_retries))
    updated = dict(data)
    updated["pipeline"] = pipeline
    return updated


def offline_plugin_ids(app_root: Path) -> list[str]:
    data = _load_offline_preset(app_root)
    stages = data.get("stages", {})
    if not isinstance(stages, dict):
        return []
    return list(_extract_plugin_ids(stages.values()))


def _extract_plugin_ids(stage_entries: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in stage_entries:
        if not isinstance(entry, dict):
            continue
        plugin_id = str(entry.get("plugin_id", "")).strip()
        if plugin_id and plugin_id not in seen:
            seen.add(plugin_id)
            ordered.append(plugin_id)
        plugin_ids = entry.get("plugin_ids")
        if isinstance(plugin_ids, list):
            for item in plugin_ids:
                pid = str(item or "").strip()
                if pid and pid not in seen:
                    seen.add(pid)
                    ordered.append(pid)
        variants = entry.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_id = str(variant.get("plugin_id", "")).strip()
                if variant_id and variant_id not in seen:
                    seen.add(variant_id)
                    ordered.append(variant_id)
    return ordered


def _load_offline_preset(app_root: Path) -> Dict[str, object]:
    path = Path(app_root) / "config" / "settings" / "pipeline" / "offline.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
