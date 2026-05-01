from __future__ import annotations

import sys
from pathlib import Path

# Allow running the script without installing the package (PYTHONPATH not required).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
for _p in (str(_SRC), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse
import json
import re

from aimn.core.meeting_store import FileMeetingStore
from aimn.core.pipeline import StageContext, StagePolicy
from aimn.core.plugin_manager import PluginManager
from aimn.core.plugins_config import PluginsConfig
from aimn.core.plugins_registry import ensure_plugins_enabled, load_registry_payload
from aimn.core.stages.text_processing import TextProcessingAdapter


def _split_list(raw: str) -> list[str]:
    parts = re.split(r"[;,|\n]+", str(raw or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _pick_latest_edited_relpath(meeting: dict, plugin_id: str) -> str | None:
    nodes = meeting.get("nodes", {})
    if not isinstance(nodes, dict):
        return None
    best_created = ""
    best_path = None
    for _alias, node in nodes.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("stage_id", "") or "") != "text_processing":
            continue
        tool = node.get("tool", {}) if isinstance(node.get("tool"), dict) else {}
        if str(tool.get("plugin_id", "") or "") != plugin_id:
            continue
        created_at = str(node.get("created_at", "") or "")
        if created_at and created_at < best_created:
            continue
        artifacts = node.get("artifacts", [])
        if not isinstance(artifacts, list):
            continue
        for art in artifacts:
            if not isinstance(art, dict):
                continue
            if str(art.get("kind", "") or "") != "edited":
                continue
            rel = str(art.get("path", "") or "").strip()
            if not rel:
                continue
            best_created = created_at
            best_path = rel
            break
    return best_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run a single text_processing plugin for selected meetings.")
    parser.add_argument("--output-dir", type=str, default="output", help="Output dir (default: output).")
    parser.add_argument("--plugin", type=str, required=True, help="text_processing plugin id (e.g. text_processing.semantic_blocks_v1).")
    parser.add_argument("--bases", type=str, required=True, help="Comma/semicolon-separated list of base names (output/<base>__MEETING.json).")
    parser.add_argument("--force", action="store_true", help="Force re-run (no cache hits).")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (repo_root / args.output_dir).resolve()
    if not output_dir.exists():
        raise SystemExit(f"output_dir_not_found: {output_dir}")

    plugin_id = str(args.plugin or "").strip()
    if not plugin_id:
        raise SystemExit("plugin_id_required")

    base_names = _split_list(args.bases)
    if not base_names:
        raise SystemExit("no_bases")

    registry_payload, _source, _path = load_registry_payload(repo_root)
    registry_payload = ensure_plugins_enabled(registry_payload, [plugin_id])
    registry_config = PluginsConfig(registry_payload)
    plugin_manager = PluginManager(repo_root, registry_config)
    plugin_manager.load()

    try:
        stage_policy = StagePolicy(stage_id="text_processing", required=True, continue_on_error=True, depends_on=[])
        config_data = {
            "pipeline": {"preset": "sample_text_processing"},
            "stages": {
                "text_processing": {
                    "params": {"cleanup_pre_edit": True},
                    "variants": [
                        {"plugin_id": plugin_id, "params": {}},
                    ],
                }
            },
        }
        config = PluginsConfig(config_data)
        adapter = TextProcessingAdapter(stage_policy, config)
        store = FileMeetingStore(output_dir)

        for base_name in base_names:
            base = str(base_name).strip()
            if not base:
                continue
            meeting_path = output_dir / f"{base}__MEETING.json"
            if not meeting_path.exists():
                print(f"missing_meeting: {base}")
                continue
            meeting = store.load(base)
            ctx = StageContext(
                meeting=meeting,
                force_run=bool(args.force),
                output_dir=str(output_dir),
                plugin_manager=plugin_manager,
            )
            result = adapter.run(ctx)
            store.save(meeting)
            payload = json.loads(meeting_path.read_text(encoding="utf-8"))
            edited_rel = _pick_latest_edited_relpath(payload, plugin_id)
            status = result.status
            rel = edited_rel or ""
            print(f"{base}\t{status}\t{rel}")
    finally:
        plugin_manager.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

