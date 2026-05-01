from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

from aimn.plugins.api import ArtifactSchema, HookContext, emit_result
from aimn.plugins.interfaces import KIND_INDEX, PluginOutput, PluginResult


def _webhook_url(value: Optional[str]) -> str:
    url = (value or os.getenv("AIMN_WEBHOOK_URL", "")).strip()
    if not url:
        raise ValueError("webhook_url_missing")
    return url


class WebhookIngestPlugin:
    def __init__(
        self,
        webhook_url: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds

    def run(self, ctx: HookContext) -> PluginResult:
        if not ctx.input_text:
            raise ValueError("missing_summary_text")
        url = _webhook_url(self.webhook_url)
        payload = {
            "meeting_id": ctx.meeting_id,
            "alias": ctx.alias,
            "summary": ctx.input_text,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        request = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            response.read()
        outputs = [
            PluginOutput(
                kind=KIND_INDEX,
                content=f"webhook_sent:{url}",
                content_type="text",
                user_visible=False,
            )
        ]
        return PluginResult(outputs=outputs, warnings=[])


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "Webhook Ingest (Reference)",
        "description": "Reference service plugin posting summaries to a webhook.",
        "views": [
            {
                "id": "main",
                "type": "form",
                "sections": [
                    {
                        "id": "connection",
                        "title": "Connection",
                        "fields": [
                            {"id": "webhook_url", "label": "Webhook URL", "type": "string"},
                            {"id": "timeout_seconds", "label": "Timeout Seconds", "type": "string", "default": "30"},
                        ],
                    },
                ],
            }
        ],
    }


def hook_service(ctx: HookContext) -> PluginResult:
    params = ctx.plugin_config or {}
    plugin = WebhookIngestPlugin(
        webhook_url=str(params.get("webhook_url", "")).strip() or None,
        timeout_seconds=int(params.get("timeout_seconds", 30) or 30),
    )
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_INDEX, ArtifactSchema(content_type="text", user_visible=False))
        ctx.register_hook_handler("derive.after_summary", hook_service, mode="optional", priority=100)
        ctx.register_settings_schema(settings_schema)
