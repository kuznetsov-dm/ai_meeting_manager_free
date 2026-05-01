from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

from aimn.plugins.api import ArtifactSchema, HookContext, emit_result
from aimn.plugins.interfaces import KIND_SUMMARY, PluginOutput, PluginResult


def _api_key(value: Optional[str]) -> str:
    key = (value or os.getenv("AIMN_OPENAI_API_KEY", "")).strip()
    if not key:
        raise ValueError("openai_api_key_missing")
    return key


class OpenAISummaryPlugin:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        system_prompt: str = "Summarize the meeting clearly and concisely.",
        temperature: float = 0.2,
        max_tokens: int = 900,
        endpoint: str = "https://api.openai.com/v1/chat/completions",
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def run(self, ctx: HookContext) -> PluginResult:
        text = (ctx.input_text or "").strip()
        if not text:
            raise ValueError("empty_input_text")
        key = _api_key(self.api_key)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(self.endpoint, data=body, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
        data = json.loads(raw.decode("utf-8"))
        content = str(data["choices"][0]["message"]["content"]).strip()
        if not content:
            raise ValueError("openai_summary_empty")
        outputs = [PluginOutput(kind=KIND_SUMMARY, content=content, content_type="text/markdown")]
        return PluginResult(outputs=outputs, warnings=[])


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "OpenAI Summary (Reference)",
        "description": "Reference summarization plugin using OpenAI Chat Completions.",
        "views": [
            {
                "id": "main",
                "type": "form",
                "sections": [
                    {
                        "id": "auth",
                        "title": "Auth",
                        "fields": [
                            {"id": "api_key", "label": "API Key", "type": "secret"},
                        ],
                    },
                    {
                        "id": "model",
                        "title": "Model",
                        "fields": [
                            {"id": "model", "label": "Model", "type": "string", "default": "gpt-4o-mini"},
                            {
                                "id": "system_prompt",
                                "label": "System Prompt",
                                "type": "multiline",
                                "default": "Summarize the meeting clearly and concisely.",
                            },
                            {"id": "temperature", "label": "Temperature", "type": "string", "default": "0.2"},
                            {"id": "max_tokens", "label": "Max Tokens", "type": "string", "default": "900"},
                            {
                                "id": "endpoint",
                                "label": "Endpoint",
                                "type": "string",
                                "default": "https://api.openai.com/v1/chat/completions",
                            },
                            {"id": "timeout_seconds", "label": "Timeout Seconds", "type": "string", "default": "60"},
                        ],
                    },
                ],
            }
        ],
    }


def hook_derive_summary(ctx: HookContext) -> PluginResult:
    params = ctx.plugin_config or {}
    plugin = OpenAISummaryPlugin(
        api_key=str(params.get("api_key", "")).strip() or None,
        model=str(params.get("model", "")).strip() or "gpt-4o-mini",
        system_prompt=str(params.get("system_prompt", "")).strip()
        or "Summarize the meeting clearly and concisely.",
        temperature=float(params.get("temperature", 0.2) or 0.2),
        max_tokens=int(params.get("max_tokens", 900) or 900),
        endpoint=str(params.get("endpoint", "")).strip()
        or "https://api.openai.com/v1/chat/completions",
        timeout_seconds=int(params.get("timeout_seconds", 60) or 60),
    )
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_SUMMARY, ArtifactSchema(content_type="text/markdown", user_visible=True))
        ctx.register_hook_handler(
            "derive.after_postprocess", hook_derive_summary, mode="optional", priority=100
        )
        ctx.register_settings_schema(settings_schema)
