from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ExportDialogMessage:
    level: str
    title: str
    message: str


class MeetingExportController:
    def __init__(
        self,
        *,
        action_service,
        meeting_service,
        plugin_display_name: Callable[[str], str],
        plugin_capabilities: Callable[[str], dict],
        tr: Callable[[str, str], str],
        fmt: Callable[[str, str], str],
    ) -> None:
        self._action_service = action_service
        self._meeting_service = meeting_service
        self._plugin_display_name = plugin_display_name
        self._plugin_capabilities = plugin_capabilities
        self._tr = tr
        self._fmt = fmt

    def manual_export_text_limit(self, plugin_id: str) -> int:
        pid = str(plugin_id or "").strip()
        if not pid:
            return 0
        caps = self._plugin_capabilities(pid)
        export_caps = caps.get("artifact_export") if isinstance(caps, dict) else None
        limit = export_caps.get("manual_text_max_chars", 0) if isinstance(export_caps, dict) else 0
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    @staticmethod
    def export_error_text(message: str) -> str:
        return str(message or "").strip()

    def resolve_export_identifiers(self, *, base: str, meeting_key: str) -> tuple[str, str]:
        resolved_base = str(base or "").strip()
        meeting_id = ""
        if resolved_base:
            try:
                meeting = self._meeting_service.load_by_base_name(resolved_base)
                meeting_id = str(getattr(meeting, "meeting_id", "") or "").strip()
                candidate_base = str(getattr(meeting, "base_name", "") or "").strip()
                if candidate_base:
                    resolved_base = candidate_base
            except Exception:
                meeting_id = ""
        if not meeting_id:
            meeting_id = str(meeting_key or "").strip()
        return resolved_base, meeting_id

    def run_manual_artifact_export(
        self,
        *,
        plugin_id: str,
        action_id: str,
        stage_id: str,
        alias: str,
        artifact_kind: str,
        text: str,
        active_meeting_base_name: str,
        active_meeting_id: str,
    ) -> ExportDialogMessage | None:
        pid = str(plugin_id or "").strip()
        aid = str(action_id or "").strip()
        sid = str(stage_id or "").strip()
        al = str(alias or "").strip()
        kind = str(artifact_kind or "").strip()
        body = str(text or "")
        if not pid or not aid or not sid or not al or not kind or not body.strip():
            return None
        if not str(active_meeting_base_name or "").strip():
            return ExportDialogMessage(
                level="warning",
                title=self._tr("export.manual.no_meeting.title", "Export failed"),
                message=self._tr("export.manual.no_meeting.message", "Open a meeting before exporting artifacts."),
            )
        was_trimmed = False
        trimmed_limit = self.manual_export_text_limit(pid)
        if trimmed_limit > 0 and len(body) > trimmed_limit:
            body = f"{body[:trimmed_limit].rstrip()}\n\n... [truncated by UI]"
            was_trimmed = True
        meeting_id = str(active_meeting_id or "").strip()
        title = f"{meeting_id or active_meeting_base_name} [{kind}]"
        payload = {
            "meeting_id": meeting_id,
            "base_name": str(active_meeting_base_name or "").strip(),
            "stage_id": sid,
            "alias": al,
            "artifact_kind": kind,
            "title": title,
            "text": body,
        }
        try:
            result = self._action_service.invoke_action(pid, aid, payload)
        except Exception as exc:
            return ExportDialogMessage(
                level="warning",
                title=self._tr("export.manual.failed.title", "Export failed"),
                message=self._fmt(
                    "export.manual.failed.message",
                    "{plugin}: {error}",
                    plugin=self._plugin_display_name(pid),
                    error=self.export_error_text(str(exc or "")),
                ),
            )
        status = str(getattr(result, "status", "") or "").strip().lower()
        message = str(getattr(result, "message", "") or "").strip() or (
            "ok" if status in {"ok", "success"} else "error"
        )
        if status in {"ok", "success", "accepted"}:
            ok_key = "export.manual.ok.message_trimmed" if was_trimmed else "export.manual.ok.message"
            ok_default = (
                "{plugin}: {message} (sent truncated text, {chars} chars)"
                if was_trimmed
                else "{plugin}: {message}"
            )
            return ExportDialogMessage(
                level="info",
                title=self._tr("export.manual.ok.title", "Export completed"),
                message=self._fmt(
                    ok_key,
                    ok_default,
                    plugin=self._plugin_display_name(pid),
                    message=self.export_error_text(message),
                    chars=trimmed_limit,
                ),
            )
        return ExportDialogMessage(
            level="warning",
            title=self._tr("export.manual.failed.title", "Export failed"),
            message=self._fmt(
                "export.manual.failed.message",
                "{plugin}: {error}",
                plugin=self._plugin_display_name(pid),
                error=self.export_error_text(message),
            ),
        )

    def run_meeting_export(
        self,
        *,
        plugin_id: str,
        action_id: str,
        base_name: str,
        meeting_key: str,
        mode: str,
    ) -> ExportDialogMessage | None:
        pid = str(plugin_id or "").strip()
        aid = str(action_id or "").strip()
        base, meeting_id = self.resolve_export_identifiers(base=base_name, meeting_key=meeting_key)
        if not pid or not aid:
            return None
        payload = {
            "meeting_id": meeting_id,
            "base_name": base,
            "mode": str(mode or "").strip() or "full",
        }
        try:
            result = self._action_service.invoke_action(pid, aid, payload)
        except Exception as exc:
            return ExportDialogMessage(
                level="warning",
                title=self._tr("export.meeting.failed.title", "Export failed"),
                message=self._fmt(
                    "export.meeting.failed.message",
                    "{plugin}: {error}",
                    plugin=self._plugin_display_name(pid),
                    error=self.export_error_text(str(exc or "")),
                ),
            )
        status = str(getattr(result, "status", "") or "").strip().lower()
        message = str(getattr(result, "message", "") or "").strip() or (
            "ok" if status in {"ok", "success"} else "error"
        )
        if status in {"ok", "success", "accepted"}:
            return ExportDialogMessage(
                level="info",
                title=self._tr("export.meeting.ok.title", "Export completed"),
                message=self._fmt(
                    "export.meeting.ok.message",
                    "{plugin}: {message}",
                    plugin=self._plugin_display_name(pid),
                    message=self.export_error_text(message),
                ),
            )
        return ExportDialogMessage(
            level="warning",
            title=self._tr("export.meeting.failed.title", "Export failed"),
            message=self._fmt(
                "export.meeting.failed.message",
                "{plugin}: {error}",
                plugin=self._plugin_display_name(pid),
                error=self.export_error_text(message),
            ),
        )
