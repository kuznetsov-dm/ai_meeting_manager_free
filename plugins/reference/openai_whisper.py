from __future__ import annotations

import json
import mimetypes
import os
import uuid
import urllib.request
from pathlib import Path
from typing import Optional

from aimn.plugins.api import ArtifactSchema, HookContext, emit_result
from aimn.plugins.interfaces import KIND_TRANSCRIPT, PluginOutput, PluginResult


def _api_key(value: Optional[str]) -> str:
    key = (value or os.getenv("AIMN_OPENAI_API_KEY", "")).strip()
    if not key:
        raise ValueError("openai_api_key_missing")
    return key


def _multipart_body(fields: dict, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----aimn-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    filename = file_path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8")
    )
    parts.append(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


class OpenAIWhisperPlugin:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "whisper-1",
        language: str | None = None,
        prompt: str | None = None,
        endpoint: str = "https://api.openai.com/v1/audio/transcriptions",
        timeout_seconds: int = 120,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.language = language or ""
        self.prompt = prompt or ""
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def run(self, ctx: HookContext) -> PluginResult:
        if not ctx.input_media_path:
            raise ValueError("input_media_path is required")
        key = _api_key(self.api_key)
        file_path = Path(ctx.input_media_path)
        fields = {"model": self.model}
        if self.language:
            fields["language"] = self.language
        if self.prompt:
            fields["prompt"] = self.prompt
        body, boundary = _multipart_body(fields, file_path)
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        request = urllib.request.Request(self.endpoint, data=body, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
        data = json.loads(raw.decode("utf-8"))
        transcript = str(data.get("text", "")).strip()
        if not transcript:
            raise ValueError("openai_transcription_empty")
        outputs = [PluginOutput(kind=KIND_TRANSCRIPT, content=transcript, content_type="text")]
        return PluginResult(outputs=outputs, warnings=[])


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "OpenAI Whisper (Reference)",
        "description": "Reference transcription plugin using OpenAI Whisper API.",
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
                            {"id": "model", "label": "Model", "type": "string", "default": "whisper-1"},
                            {"id": "language", "label": "Language", "type": "string"},
                            {"id": "prompt", "label": "Prompt", "type": "multiline"},
                            {
                                "id": "endpoint",
                                "label": "Endpoint",
                                "type": "string",
                                "default": "https://api.openai.com/v1/audio/transcriptions",
                            },
                            {"id": "timeout_seconds", "label": "Timeout Seconds", "type": "string", "default": "120"},
                        ],
                    },
                ],
            }
        ],
    }


def hook_transcribe(ctx: HookContext) -> PluginResult:
    params = ctx.plugin_config or {}
    plugin = OpenAIWhisperPlugin(
        api_key=str(params.get("api_key", "")).strip() or None,
        model=str(params.get("model", "")).strip() or "whisper-1",
        language=str(params.get("language", "")).strip() or None,
        prompt=str(params.get("prompt", "")).strip() or None,
        endpoint=str(params.get("endpoint", "")).strip()
        or "https://api.openai.com/v1/audio/transcriptions",
        timeout_seconds=int(params.get("timeout_seconds", 120) or 120),
    )
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_TRANSCRIPT, ArtifactSchema(content_type="text", user_visible=True))
        ctx.register_hook_handler("transcribe.run", hook_transcribe, mode="optional", priority=100)
        ctx.register_settings_schema(settings_schema)
