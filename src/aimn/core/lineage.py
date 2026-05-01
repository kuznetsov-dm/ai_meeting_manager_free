from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from aimn.core.alias_registry import resolve_model_code, resolve_provider_code
from aimn.core.fingerprinting import compute_fingerprint
from aimn.core.meeting_store import FileMeetingStore
from aimn.domain.meeting import LineageNode, MeetingManifest


def _is_cacheable(node: LineageNode) -> bool:
    return getattr(node, "cacheable", True)


_NON_BRANCHING_STAGES = {"management", "service"}


def find_node_by_fingerprint(manifest: MeetingManifest, fingerprint: str) -> Optional[str]:
    for alias, node in manifest.nodes.items():
        if not _is_cacheable(node):
            continue
        if node.fingerprint == fingerprint:
            return alias
    return None


def should_use_branched_mode(
    manifest: MeetingManifest,
    stage_id: str,
    fingerprint: str,
) -> bool:
    if stage_id in _NON_BRANCHING_STAGES:
        return False
    for node in manifest.nodes.values():
        if not _is_cacheable(node):
            continue
        if node.stage_id == stage_id and node.fingerprint != fingerprint:
            return True
    return False


def ensure_branched_mode(
    manifest: MeetingManifest,
    stage_id: str,
    fingerprint: str,
    *,
    force_branch: bool = False,
) -> bool:
    if manifest.naming_mode == "branched":
        return True
    if stage_id in _NON_BRANCHING_STAGES:
        return False
    if force_branch or should_use_branched_mode(manifest, stage_id, fingerprint):
        manifest.naming_mode = "branched"
        return True
    return False


def apply_branching(
    manifest: MeetingManifest,
    stage_id: str,
    fingerprint: str,
    *,
    force_branch: bool = False,
    output_dir: Path | str | None = None,
    store: FileMeetingStore | None = None,
) -> bool:
    branched = ensure_branched_mode(
        manifest,
        stage_id,
        fingerprint,
        force_branch=force_branch,
    )
    if not branched:
        return False
    if stage_id in _NON_BRANCHING_STAGES:
        return True
    if output_dir is None:
        return True
    root = Path(output_dir)
    store = store or FileMeetingStore(root)
    _realign_stage_artifacts(manifest, stage_id, root, store)
    return True


_STAGE_PREFIXES = {
    "media_convert": "mc",
    "transcription": "t",
    "text_processing": "s",
    "llm_processing": "ai",
    "management": "m",
    "service": "sv",
}

_MODEL_CODES = {
    "tiny": "tn",
    "base": "bs",
    "small": "sm",
    "medium": "md",
    "large": "lg",
}

_LANG_MODE_CODES = {
    "auto": "au",
    "none": "nn",
    "forced": "fr",
}

def stage_alias_prefix(stage_id: str) -> str:
    if stage_id in _STAGE_PREFIXES:
        return _STAGE_PREFIXES[stage_id]
    parts = [part for part in stage_id.split("_") if part]
    return "".join(part[0] for part in parts) or stage_id[:1]


def _sanitize_alias_code(code: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", code)
    return cleaned.lower()


def _llm_provider_code(params: dict) -> str:
    plugin_id = str(
        params.get("plugin_id", "")
        or params.get("_plugin_id", "")
        or params.get("provider_id", "")
    ).strip()
    return resolve_provider_code(plugin_id)


def _llm_model_code(params: dict) -> str:
    candidates = (
        str(params.get("model_path", "")).strip(),
        str(params.get("model_id", "")).strip(),
        str(params.get("embeddings_model_id", "")).strip(),
        str(params.get("model", "")).strip(),
    )
    raw = next((value for value in candidates if value), "")
    if not raw:
        return "md"
    plugin_id = str(
        params.get("plugin_id", "")
        or params.get("_plugin_id", "")
        or params.get("provider_id", "")
    ).strip()
    token = raw.split("/")[-1]
    if ":" in token:
        token = token.split(":", 1)[0]
    if token.lower().endswith(".gguf"):
        token = token[:-5]
    return resolve_model_code(plugin_id, token)


def alias_code_for_stage(stage_id: str, params: dict) -> str:
    if stage_id == "transcription":
        provider = _sanitize_alias_code(str(params.get("provider", "wh")))
        model = _sanitize_alias_code(str(params.get("model", "base")))
        model_code = _MODEL_CODES.get(model, model[:2] or "md")
        lang_mode = _sanitize_alias_code(str(params.get("language_mode", "auto")))
        lang_code = _LANG_MODE_CODES.get(lang_mode, lang_mode[:2] or "au")
        return f"{provider}{model_code}{lang_code}"
    if stage_id == "llm_processing":
        provider_code = _llm_provider_code(params if isinstance(params, dict) else {})
        model_code = _llm_model_code(params if isinstance(params, dict) else {})
        return f"{provider_code}{model_code}"
    return "gen"


def allocate_stage_alias(manifest: MeetingManifest, stage_id: str, code: str) -> str:
    prefix = stage_alias_prefix(stage_id)
    safe_code = _sanitize_alias_code(code)
    index = 1
    for alias, node in manifest.nodes.items():
        if node.stage_id != stage_id:
            continue
        tail = alias.split("-")[-1]
        if tail.startswith(f"{prefix}{safe_code}"):
            index += 1
    return f"{prefix}{safe_code}{index}"


def build_alias(parent_aliases: Iterable[str], stage_alias: str) -> str:
    chain = [alias for alias in parent_aliases if alias]
    chain.append(stage_alias)
    return "-".join(chain)


def _stage_has_branching(manifest: MeetingManifest, stage_id: str) -> bool:
    fingerprints = {
        node.fingerprint
        for node in manifest.nodes.values()
        if node.stage_id == stage_id and _is_cacheable(node)
    }
    return len(fingerprints) > 1


def _filter_branching_aliases(manifest: MeetingManifest, parent_aliases: Iterable[str]) -> List[str]:
    filtered: List[str] = []
    for alias in parent_aliases:
        node = manifest.nodes.get(alias)
        if not node:
            continue
        if _stage_has_branching(manifest, node.stage_id):
            filtered.append(alias)
    return filtered


def build_alias_with_branching(
    manifest: MeetingManifest,
    parent_aliases: Iterable[str],
    stage_alias: str,
) -> str:
    chain = _filter_branching_aliases(manifest, parent_aliases)
    chain.append(stage_alias)
    return "-".join(chain)


def _realign_stage_artifacts(
    manifest: MeetingManifest,
    stage_id: str,
    output_dir: Path,
    store: FileMeetingStore,
) -> None:
    if manifest.naming_mode != "branched":
        return
    alias_map: dict[str, str] = {}
    for alias, node in manifest.nodes.items():
        if node.stage_id != stage_id:
            continue
        stage_alias = alias.split("-")[-1]
        desired_alias = build_alias_with_branching(manifest, node.inputs.parent_nodes, stage_alias)
        if desired_alias != alias and desired_alias not in manifest.nodes:
            alias_map[alias] = desired_alias

    for alias, node in list(manifest.nodes.items()):
        if node.stage_id != stage_id:
            continue
        target_alias = alias_map.get(alias, alias)
        for artifact in node.artifacts:
            old_rel = artifact.path
            ext = Path(old_rel).suffix.lstrip(".")
            new_rel = store.resolve_artifact_path(
                manifest.base_name,
                target_alias,
                artifact.kind,
                ext,
            )
            if old_rel == new_rel:
                continue
            old_path = output_dir / old_rel
            new_path = output_dir / new_rel

            # If the new file already exists (e.g. from a previous copy fallback), just re-point metadata.
            if new_path.exists():
                artifact.path = new_rel
                if manifest.transcript_relpath == old_rel:
                    manifest.transcript_relpath = new_rel
                if manifest.segments_relpath == old_rel:
                    manifest.segments_relpath = new_rel
                if manifest.audio_relpath == old_rel:
                    manifest.audio_relpath = new_rel
                continue

            # Do not rewrite manifest to point at a non-existent relpath: it breaks UI previews ("Missing: ...").
            if not old_path.exists():
                continue

            moved = False
            try:
                os.replace(old_path, new_path)
                moved = True
            except PermissionError:
                # Windows: artifacts can be temporarily locked by UI preview (e.g. audio player).
                # Fall back to copy so the pipeline can proceed; the old file is left in place.
                try:
                    if new_path.exists():
                        os.unlink(new_path)
                except Exception:
                    pass
                try:
                    shutil.copy2(old_path, new_path)
                    moved = True
                except Exception:
                    moved = False

            if moved and new_path.exists():
                artifact.path = new_rel
                if manifest.transcript_relpath == old_rel:
                    manifest.transcript_relpath = new_rel
                if manifest.segments_relpath == old_rel:
                    manifest.segments_relpath = new_rel
                if manifest.audio_relpath == old_rel:
                    manifest.audio_relpath = new_rel

    if alias_map:
        for alias, node in list(manifest.nodes.items()):
            if alias in alias_map:
                new_alias = alias_map[alias]
                manifest.nodes[new_alias] = node
                del manifest.nodes[alias]
        for node in manifest.nodes.values():
            if node.inputs.parent_nodes:
                node.inputs.parent_nodes = [
                    alias_map.get(parent, parent) for parent in node.inputs.parent_nodes
                ]


def compute_node_fingerprint(
    stage_id: str,
    plugin_id: str,
    plugin_version: str,
    params: dict,
    parent_fps: Iterable[str],
    source_fps: Iterable[str],
) -> str:
    inputs: List[str] = list(parent_fps) + list(source_fps)
    return compute_fingerprint(stage_id, plugin_id, plugin_version, params, inputs)


def register_node(manifest: MeetingManifest, alias: str, node: LineageNode) -> None:
    manifest.nodes[alias] = node
