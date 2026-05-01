from __future__ import annotations

from typing import Iterable, List

from aimn.core.lineage import alias_code_for_stage, allocate_stage_alias, build_alias_with_branching
from aimn.core.fingerprinting import compute_fingerprint
from aimn.domain.meeting import ArtifactRef, LineageNode, MeetingManifest, NodeInputs, NodeTool


def allocate_alias(
    manifest: MeetingManifest,
    stage_id: str,
    params: dict,
    parent_aliases: Iterable[str],
) -> str:
    code = alias_code_for_stage(stage_id, params)
    stage_alias = allocate_stage_alias(manifest, stage_id, code)
    return build_alias_with_branching(manifest, parent_aliases, stage_alias)


def register_lineage_node(
    manifest: MeetingManifest,
    alias: str,
    stage_id: str,
    plugin_id: str,
    plugin_version: str,
    params: dict,
    parent_aliases: Iterable[str],
    source_fps: Iterable[str],
    artifacts: List[ArtifactRef],
    created_at: str,
    *,
    cacheable: bool = True,
) -> str:
    parent_fps = [manifest.nodes[parent].fingerprint for parent in parent_aliases]
    fingerprint = compute_fingerprint(stage_id, plugin_id, plugin_version, params, parent_fps + list(source_fps))

    node = LineageNode(
        stage_id=stage_id,
        tool=NodeTool(plugin_id=plugin_id, version=plugin_version),
        params=params,
        inputs=NodeInputs(source_ids=list(source_fps), parent_nodes=list(parent_aliases)),
        fingerprint=fingerprint,
        cacheable=cacheable,
        artifacts=artifacts,
        created_at=created_at,
    )
    manifest.nodes[alias] = node
    return alias
