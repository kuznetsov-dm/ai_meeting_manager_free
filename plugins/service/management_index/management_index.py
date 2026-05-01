from __future__ import annotations

import json

from aimn.plugins.api import ArtifactSchema, HookContext, open_management_store
from aimn.plugins.interfaces import KIND_INDEX


class Plugin:
    def register(self, ctx) -> None:
        # Keep schema compatible with other service/index plugins (text payload).
        ctx.register_artifact_kind(KIND_INDEX, ArtifactSchema(content_type="text", user_visible=False))
        ctx.register_hook_handler("derive.after_summary", hook_build_index, mode="optional", priority=100)


def hook_build_index(ctx: HookContext):
    store = open_management_store(ctx)
    try:
        tasks = store.list_tasks_for_meeting(ctx.meeting_id)
        projects = store.list_projects_for_meeting(ctx.meeting_id)
    finally:
        store.close()

    payload = {
        "meeting_id": str(ctx.meeting_id or ""),
        "tasks": tasks,
        "projects": projects,
    }
    ctx.write_artifact(KIND_INDEX, json.dumps(payload, ensure_ascii=True, indent=2), content_type="text")
    return None
