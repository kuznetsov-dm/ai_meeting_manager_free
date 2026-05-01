from __future__ import annotations

import html
import json
from pathlib import Path

from aimn.core.api import ManagementStore


class InspectionRenderController:
    def __init__(self, *, app_root: Path) -> None:
        self._app_root = Path(app_root)

    def render_inspection_html(self, meeting: object, *, stage_id: str, alias: str, kind: str) -> str:
        nodes = getattr(meeting, "nodes", {}) or {}
        node = nodes.get(alias) if isinstance(nodes, dict) else None

        pinned = getattr(meeting, "pinned_aliases", {}) or {}
        active = getattr(meeting, "active_aliases", {}) or {}
        pinned_alias = str(pinned.get(stage_id, "") or "").strip()
        active_alias = str(active.get(stage_id, "") or "").strip()

        def esc(value: object) -> str:
            return html.escape(str(value or ""))

        parts: list[str] = []
        parts.append(
            "<style>"
            ".ins-meta{color:#64748B;}"
            ".ins-warn{color:#B91C1C;font-weight:600;}"
            ".ins-pre{margin:0;padding:10px;border:1px solid #94A3B8;border-radius:10px;background:rgba(148,163,184,0.12);}"
            ".ins-ul{margin-top:0;}"
            "</style>"
        )
        parts.append(f"<h3 style=\"margin:0;\">{esc(kind)} — {esc(stage_id)}:{esc(alias)}</h3>")
        if pinned_alias:
            parts.append(f"<div><b>Pinned:</b> {esc(pinned_alias)}</div>")
        if active_alias:
            parts.append(f"<div><b>Active:</b> {esc(active_alias)}</div>")
        parts.append("<hr/>")

        if not node:
            parts.append("<div class=\"ins-warn\">Lineage node not found for this alias.</div>")
            return "\n".join(parts)

        tool = getattr(node, "tool", None)
        plugin_id = str(getattr(tool, "plugin_id", "") or "")
        version = str(getattr(tool, "version", "") or "")
        created_at = str(getattr(node, "created_at", "") or "")
        fingerprint = str(getattr(node, "fingerprint", "") or "")
        cacheable = getattr(node, "cacheable", None)
        inputs = getattr(node, "inputs", None)
        parent_nodes = getattr(inputs, "parent_nodes", []) if inputs else []
        source_ids = getattr(inputs, "source_ids", []) if inputs else []
        params = getattr(node, "params", {}) or {}
        raw_artifacts = getattr(node, "artifacts", []) or []
        hidden_kinds = {"actions", "decisions", "tasks", "projects"}
        artifacts = [art for art in raw_artifacts if str(getattr(art, "kind", "") or "") not in hidden_kinds]

        parts.append(f"<div><b>Tool:</b> {esc(plugin_id)} <span class=\"ins-meta\">{esc(version)}</span></div>")
        if created_at:
            parts.append(f"<div><b>Created:</b> {esc(created_at)}</div>")
        if fingerprint:
            parts.append(f"<div><b>Fingerprint:</b> <code>{esc(fingerprint)}</code></div>")
        if cacheable is not None:
            parts.append(f"<div><b>Cacheable:</b> {esc(cacheable)}</div>")
        if parent_nodes:
            joined = ", ".join([esc(x) for x in parent_nodes])
            parts.append(f"<div><b>Parents:</b> {joined}</div>")
        if source_ids:
            joined = ", ".join([esc(x) for x in source_ids])
            parts.append(f"<div><b>Sources:</b> {joined}</div>")

        try:
            params_pretty = json.dumps(params, ensure_ascii=False, indent=2)
        except Exception:
            params_pretty = str(params)
        parts.append("<h4 style=\"margin:14px 0 6px 0;\">Params</h4>")
        parts.append(
            "<pre class=\"ins-pre\">"
            f"{esc(params_pretty)}"
            "</pre>"
        )

        parts.append("<h4 style=\"margin:14px 0 6px 0;\">Artifacts</h4>")
        if not artifacts:
            parts.append("<div class=\"ins-meta\">No artifacts recorded.</div>")
        else:
            parts.append("<ul class=\"ins-ul\">")
            for art in artifacts:
                ak = esc(getattr(art, "kind", "") or "")
                ap = esc(getattr(art, "path", "") or "")
                parts.append(f"<li><b>{ak}</b> <span class=\"ins-meta\">{ap}</span></li>")
            parts.append("</ul>")

        meeting_id = str(getattr(meeting, "meeting_id", "") or "").strip()
        if meeting_id:
            try:
                store = ManagementStore(self._app_root)
                tasks = store.list_tasks_for_meeting(meeting_id)
                projects = store.list_projects_for_meeting(meeting_id)
                store.close()
            except Exception:
                tasks = []
                projects = []
            if tasks or projects:
                parts.append("<hr/>")
                if projects:
                    parts.append(f"<div><b>Projects:</b> {len(projects)}</div>")
                    for item in projects[:5]:
                        parts.append(f"<div>• {esc(item.get('name'))}</div>")
                if tasks:
                    parts.append(f"<div style=\"margin-top:6px;\"><b>Tasks:</b> {len(tasks)}</div>")
                    for item in tasks[:8]:
                        parts.append(f"<div>• {esc(item.get('title'))}</div>")

        return "\n".join(parts)
