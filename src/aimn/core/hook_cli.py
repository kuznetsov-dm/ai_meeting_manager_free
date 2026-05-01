from __future__ import annotations

import json
import sys
from pathlib import Path

from aimn.core.contracts import Artifact, ArtifactMeta, HookContext, PluginResult
from aimn.core.plugin_manager import PluginManager
from aimn.core.plugins_config import PluginsConfig
from aimn.core.plugins_registry import load_registry_payload


def main() -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw or "{}")
    repo_root = Path(payload.get("repo_root", "")).resolve()
    if not repo_root.exists():
        print(json.dumps({"status": "error", "message": "repo_root_missing"}, ensure_ascii=True))
        return 1
    registry_payload, _source, _path = load_registry_payload(repo_root)
    config = PluginsConfig(registry_payload)
    manager = PluginManager(repo_root, config)
    manager.load()

    plugin_id = str(payload.get("plugin_id", "")).strip()
    hook_name = str(payload.get("hook_name", "")).strip()
    if not plugin_id or not hook_name:
        print(json.dumps({"status": "error", "message": "hook_payload_missing"}, ensure_ascii=True))
        return 1

    output_dir = str(payload.get("output_dir", "") or "").strip()
    storage_dir = str(payload.get("storage_dir", "") or "").strip()
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
    latest = payload.get("latest_artifacts") if isinstance(payload.get("latest_artifacts"), dict) else {}

    def _list_artifacts() -> list[ArtifactMeta]:
        metas: list[ArtifactMeta] = []
        for entry in artifacts:
            if not isinstance(entry, dict):
                continue
            metas.append(
                ArtifactMeta(
                    kind=str(entry.get("kind", "")),
                    path=str(entry.get("path", "")),
                    content_type=str(entry.get("content_type", "")) or None,
                    user_visible=bool(entry.get("user_visible", True)),
                )
            )
        return metas

    def _get_artifact(kind: str) -> Artifact | None:
        entry = latest.get(kind) if isinstance(latest, dict) else None
        if not isinstance(entry, dict):
            for candidate in reversed(artifacts):
                if isinstance(candidate, dict) and candidate.get("kind") == kind:
                    entry = candidate
                    break
        if not isinstance(entry, dict):
            return None
        relpath = str(entry.get("path", "")).strip()
        if not relpath or not output_dir:
            return None
        path = Path(output_dir) / relpath
        if not path.exists():
            return None
        content_type = str(entry.get("content_type", "")).strip()
        content = ""
        if content_type.startswith("text") or content_type.endswith("json"):
            content = path.read_text(encoding="utf-8", errors="ignore")
        meta = ArtifactMeta(
            kind=str(entry.get("kind", "")),
            path=relpath,
            content_type=content_type or None,
            user_visible=bool(entry.get("user_visible", True)),
        )
        return Artifact(meta=meta, content=content)

    ctx = HookContext(
        plugin_id=plugin_id,
        meeting_id=str(payload.get("meeting_id", "")),
        alias=payload.get("alias"),
        input_text=payload.get("input_text"),
        input_media_path=payload.get("input_media_path"),
        force_run=bool(payload.get("force_run", False)),
        progress_callback=None,
        plugin_config=payload.get("plugin_config") or {},
        _output_dir=output_dir or None,
        _storage_dir=storage_dir or str(manager.get_storage_path(plugin_id)),
        _get_artifact=_get_artifact,
        _list_artifacts=_list_artifacts,
        _get_secret=lambda key: manager.get_secret(plugin_id, key),
        _resolve_service=manager.get_service,
        _schema_resolver=manager.artifact_schema,
    )

    try:
        executions = manager.execute_connector(hook_name, ctx, allowed_plugin_ids=[plugin_id])
        if not executions:
            print(json.dumps({"status": "ok", "execution": None}, ensure_ascii=True))
            return 0
        execution = executions[0]
        payload = {
            "plugin_id": execution.plugin_id,
            "handler_id": execution.handler_id,
            "mode": execution.mode,
            "error": execution.error,
            "result": _serialize_result(execution.result),
        }
        print(json.dumps({"status": "ok", "execution": payload}, ensure_ascii=True))
        return 0
    finally:
        manager.shutdown()


def _serialize_result(result: PluginResult | None) -> dict | None:
    if result is None:
        return None
    outputs = [
        {
            "kind": output.kind,
            "content": output.content,
            "content_type": output.content_type,
            "user_visible": output.user_visible,
        }
        for output in result.outputs
    ]
    return {"outputs": outputs, "warnings": list(result.warnings)}


if __name__ == "__main__":
    raise SystemExit(main())
