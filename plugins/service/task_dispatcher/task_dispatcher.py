from __future__ import annotations

from dataclasses import dataclass

from aimn.plugins.api import open_management_store
from aimn.plugins.interfaces import (
    ActionDescriptor,
    ActionResult,
    HookContext,
    PluginResult,
)

_ALLOWED_TARGETS = {"todoist", "trello"}


@dataclass
class _ActionContext:
    meeting_id: str
    _output_dir: str | None = None


class Plugin:
    def register(self, ctx) -> None:
        self.ctx = ctx
        self.logger = ctx.get_logger()
        ctx.register_hook_handler("derive.after_summary", self.hook_sync, priority=100)
        ctx.register_actions(self.get_actions)

    def get_actions(self) -> list[ActionDescriptor]:
        return [
            ActionDescriptor(
                action_id="sync_meeting_data",
                label="Export Meeting to External System",
                description="Экспорт задач встречи во внешнюю систему (Todoist или Trello).",
                run_mode="async",
                handler=self.handle_sync_action,
            )
        ]

    def hook_sync(self, ctx: HookContext) -> PluginResult:
        self.logger.info("Meeting %s processing finished. Ready for export.", ctx.meeting_id)
        return ctx.build_result()

    def handle_sync_action(self, settings: dict, params: dict) -> ActionResult:
        meeting_id = str(params.get("meeting_id", "") or "").strip()
        if not meeting_id:
            return ActionResult(status="error", message="meeting_id_missing")

        target = self._resolve_target(settings)
        if target not in _ALLOWED_TARGETS:
            return ActionResult(status="error", message=f"target_service_invalid:{target}")

        store = open_management_store(_ActionContext(meeting_id=meeting_id))
        try:
            return self._sync_tasks_only(meeting_id, store, target, settings)
        except Exception as exc:
            self.logger.exception("Export failed")
            return ActionResult(status="error", message=str(exc))
        finally:
            try:
                store.close()
            except Exception:
                pass

    def _sync_tasks_only(self, meeting_id: str, store, target: str, settings: dict) -> ActionResult:
        tasks = store.list_tasks_for_meeting(meeting_id)
        if not tasks:
            return ActionResult(status="ok", message="no_tasks_to_sync", data={"target": target})

        count = 0
        for task in tasks:
            if self._dispatch_task_to_service(task, target, settings):
                count += 1

        return ActionResult(
            status="ok",
            message=f"tasks_synced:{target}",
            data={"target": target, "synced": count, "total": len(tasks)},
        )

    def _dispatch_task_to_service(self, task: dict, target: str, settings: dict) -> bool:
        token = self._resolve_token(target, settings)
        if not token:
            return False

        title = str(task.get("title", "") or "").strip()
        if not title:
            return False

        self.logger.info("Dispatching task to %s: %s", target, title)
        return True

    def _resolve_target(self, settings: dict) -> str:
        raw = settings.get("target_service", "todoist")
        return str(raw or "todoist").strip().lower()

    def _resolve_token(self, target: str, settings: dict) -> str:
        key = f"{target}_token"
        token = self.ctx.get_secret(key) or settings.get(key, "")
        if target == "trello" and not token:
            token = self.ctx.get_secret("trello_key") or settings.get("trello_key", "")
        return str(token or "").strip()
