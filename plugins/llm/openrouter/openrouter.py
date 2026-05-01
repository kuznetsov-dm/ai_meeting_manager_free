from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aimn.plugins.api import (
    ArtifactSchema,
    HookContext,
    build_prompt,
    default_summary_system_prompt,
    emit_result,
    load_prompt_presets,
    normalize_presets,
    resolve_prompt,
)
from aimn.plugins.interfaces import (
    KIND_SUMMARY,
    ActionDescriptor,
    ActionResult,
    PluginOutput,
    PluginResult,
)


@dataclass(frozen=True)
class OpenRouterModel:
    model_id: str
    product_name: str
    context_window: int
    highlights: str
    description: str
    source_url: str = ""
    size_hint: str = ""


def load_free_models() -> list[OpenRouterModel]:
    models: list[OpenRouterModel] = []
    source: list[dict] = []
    try:
        passport_path = Path(__file__).resolve().with_name("plugin_passport.json")
        if passport_path.exists():
            payload = json.loads(passport_path.read_text(encoding="utf-8"))
            candidate = payload.get("models") if isinstance(payload, dict) else None
            if isinstance(candidate, list):
                source = [entry for entry in candidate if isinstance(entry, dict)]
    except Exception:
        source = []
    for entry in source:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if not model_id:
            continue
        models.append(
            OpenRouterModel(
                model_id=model_id,
                product_name=str(entry.get("product_name", "") or entry.get("name", "")).strip(),
                context_window=int(entry.get("context_window", 0) or 0),
                highlights=str(entry.get("highlights", "")).strip(),
                description=str(entry.get("description", "")).strip(),
                source_url=str(entry.get("source_url", "")).strip(),
                size_hint=str(entry.get("size_hint", "")).strip(),
            )
        )
    return models


FREE_MODELS: list[OpenRouterModel] = load_free_models()
_FREE_MODELS_BY_ID = {item.model_id: item for item in FREE_MODELS}
OPENROUTER_RATE_LIMIT_COOLDOWN_SECONDS = 60 * 30
OPENROUTER_TRANSIENT_COOLDOWN_SECONDS = 60 * 10


class OpenRouterPlugin:
    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
        system_prompt: str | None = None,
        prompt_profile: str | None = None,
        prompt_custom: str | None = None,
        prompt_language: str | None = None,
        prompt_presets: list[dict] | None = None,
        prompt_max_words: int = 600,
        max_tokens: int = 900,
        temperature: float = 0.2,
        endpoint: str = "https://openrouter.ai/api/v1/chat/completions",
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = api_key
        self.model_id = model_id
        if system_prompt is None:
            system_prompt = default_summary_system_prompt()
        self.system_prompt = system_prompt
        self.prompt_profile = (prompt_profile or "").strip()
        self.prompt_custom = prompt_custom or ""
        self.prompt_language = (prompt_language or "").strip()
        self.prompt_presets = prompt_presets or []
        self.prompt_max_words = int(prompt_max_words) if isinstance(prompt_max_words, str) else prompt_max_words
        self.max_tokens = int(max_tokens) if isinstance(max_tokens, str) else max_tokens
        self.temperature = float(temperature) if isinstance(temperature, str) else temperature
        self.endpoint = endpoint
        self.timeout_seconds = _coerce_timeout_seconds(timeout_seconds, default=60)

    def run(self, ctx: HookContext) -> PluginResult:
        warnings: list[str] = []
        text = (ctx.input_text or "").strip()
        if not text:
            warnings.append("empty_input_text")
            text = "No transcript text provided."

        model_id = self._resolve_model_id()
        api_key, key_status = self._resolve_api_key()
        if key_status != "ok":
            warnings.append(key_status)
        if not api_key:
            return self._mock_result(warnings + ["openrouter_key_missing"])

        system_prompt = self._resolve_prompt(text)
        user_text = text if not system_prompt else "Summarize according to the system instructions."
        content, error = self._call_openrouter(api_key, model_id, user_text, system_prompt)
        if error:
            warnings.append(error)
            return self._mock_result(warnings + ["openrouter_request_failed"])
        if not content:
            warnings.append("openrouter_empty_response")
            return self._mock_result(warnings)

        outputs = [PluginOutput(kind=KIND_SUMMARY, content=content, content_type="text/markdown")]
        return PluginResult(outputs=outputs, warnings=warnings)

    def _resolve_model_id(self) -> str:
        if self.model_id:
            return self.model_id.strip()
        return self._default_free_model_id()

    @staticmethod
    def _default_free_model_id() -> str:
        return FREE_MODELS[0].model_id if FREE_MODELS else "openrouter/auto"

    @staticmethod
    def _is_free_model(model_id: str) -> bool:
        return any(model.model_id == model_id for model in FREE_MODELS)

    def _resolve_api_key(self) -> tuple[str | None, str]:
        key = (
            self.api_key
            or os.getenv("AIMN_OPENROUTER_API_KEY", "")
            or os.getenv("AIMN_OPENROUTER_USER_KEY", "")
            or os.getenv("AIMN_OPENROUTER_FREE_KEY", "")
        ).strip()
        return (key if key else None, "ok" if key else "api_key_missing")

    def _call_openrouter(
        self,
        api_key: str,
        model_id: str,
        text: str,
        system_prompt: str | None,
        *,
        quiet: bool = False,
    ) -> tuple[str, str]:
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt or self.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ai-meetingnotes.local",
            "X-Title": "AIMeetingNotes",
        }
        logger = logging.getLogger("aimn.network.openrouter")
        log = logger.debug if quiet else logger.info
        log("openrouter_request model=%s endpoint=%s timeout=%s", model_id, self.endpoint, self.timeout_seconds)
        request = urllib.request.Request(self.endpoint, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            detail = self._describe_http_error(exc, model_id)
            if quiet:
                logger.info("openrouter_probe_failed model=%s error=%s", model_id, detail)
            else:
                logger.warning("openrouter_request_failed model=%s error=%s", model_id, detail)
            return "", detail
        try:
            content = _extract_message_text(data)
            if not content:
                details = _response_debug_signature(data)
                if quiet:
                    logger.info("openrouter_probe_empty_payload model=%s details=%s", model_id, details)
                else:
                    logger.warning("openrouter_empty_payload model=%s details=%s", model_id, details)
                return "", f"openrouter_empty_response details={details}"
            log("openrouter_request_ok model=%s", model_id)
            return content, ""
        except Exception:
            if quiet:
                logger.info("openrouter_probe_parse_error model=%s", model_id)
            else:
                logger.warning("openrouter_parse_error model=%s", model_id)
            return "", "openrouter_parse_error"

    @staticmethod
    def _describe_http_error(exc: Exception, model_id: str) -> str:
        message = str(exc)
        status = None
        body = ""
        try:
            from urllib.error import HTTPError

            if isinstance(exc, HTTPError):
                status = exc.code
                raw = exc.read()
                body = raw.decode("utf-8", errors="ignore")[:200]
        except Exception:
            pass
        parts = [f"openrouter_http_error(model={model_id})"]
        if status:
            parts.append(f"status={status}")
        if body:
            parts.append(f"body={body}")
        if message and message not in parts:
            parts.append(message)
        return " ".join(parts)

    @staticmethod
    def _mock_result(warnings: list[str]) -> PluginResult:
        title, reason, detail, fix_steps = OpenRouterPlugin._fallback_diagnostics(warnings)
        lines = [
            f"# {title}",
            "",
            "This is a fallback summary because the OpenRouter request could not be completed.",
            "",
            f"Reason: {reason}",
        ]
        if detail:
            lines.extend(["", f"Detail: `{detail}`"])
        if fix_steps:
            lines.extend(["", "To fix:"])
            lines.extend([f"- {step}" for step in fix_steps])
        text = "\n".join(lines)
        outputs = [PluginOutput(kind=KIND_SUMMARY, content=text, content_type="text/markdown")]
        if "mock_fallback" not in warnings:
            warnings = list(warnings) + ["mock_fallback"]
        return PluginResult(outputs=outputs, warnings=warnings)

    @staticmethod
    def _fallback_diagnostics(warnings: list[str]) -> tuple[str, str, str, list[str]]:
        items = [str(item).strip() for item in (warnings or []) if str(item).strip()]
        detail = OpenRouterPlugin._first_detail_warning(items)

        if any(item in {"api_key_missing", "openrouter_key_missing"} for item in items):
            return (
                "OpenRouter is not configured",
                "API key is missing.",
                detail,
                ["Add API key in Settings -> LLM -> OpenRouter.", "Re-run the stage."],
            )

        status = OpenRouterPlugin._extract_http_status(items)
        if status == 429:
            return (
                "OpenRouter rate limit",
                "Upstream provider returned HTTP 429 (Too Many Requests).",
                detail,
                [
                    "Retry later.",
                    "Use another enabled model/provider in this run.",
                    "Use your own key/credits to avoid shared free-tier limits.",
                ],
            )
        if status == 404:
            return (
                "OpenRouter request failed",
                "HTTP 404 from API (endpoint or model id is invalid).",
                detail,
                ["Verify endpoint URL.", "Verify model_id in plugin settings.", "Re-run the stage."],
            )
        if status == 400:
            return (
                "OpenRouter bad request",
                "HTTP 400: request payload was rejected by API.",
                detail,
                ["Check model_id and prompt configuration.", "Re-run plugin health test in Settings."],
            )
        if status in {401, 403}:
            return (
                "OpenRouter authorization failed",
                f"HTTP {status}: access denied.",
                detail,
                ["Check API key validity and permissions.", "Re-run the stage."],
            )
        if any(item.startswith("openrouter_empty_response") for item in items):
            return (
                "OpenRouter returned empty response",
                "The API request completed but returned no usable content.",
                detail,
                ["Retry the stage.", "Switch to another model for this run."],
            )
        return (
            "OpenRouter request failed",
            "The request could not be completed.",
            detail,
            ["Check network/API availability.", "Review plugin test results in Settings.", "Re-run the stage."],
        )

    @staticmethod
    def _extract_http_status(warnings: list[str]) -> int | None:
        for item in warnings:
            match = re.search(r"status=(\d{3})", item)
            if not match:
                continue
            try:
                return int(match.group(1))
            except Exception:
                return None
        return None

    @staticmethod
    def _first_detail_warning(warnings: list[str]) -> str:
        skip = {
            "mock_fallback",
            "openrouter_request_failed",
            "openrouter_empty_response",
            "empty_input_text",
            "api_key_missing",
            "openrouter_key_missing",
        }
        for item in warnings:
            if item in skip:
                continue
            return item[:220]
        return ""

    def _resolve_prompt(self, transcript: str) -> str:
        presets = normalize_presets(self.prompt_presets) or load_prompt_presets()
        main_prompt = resolve_prompt(self.prompt_profile, presets, self.prompt_custom)
        if not main_prompt:
            return ""
        return build_prompt(
            transcript=transcript,
            main_prompt=main_prompt,
            language_override=self.prompt_language,
            max_words=self.prompt_max_words,
        )


def _openrouter_request_headers(api_key: str = "") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ai-meetingnotes.local",
        "X-Title": "AIMeetingNotes",
    }
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _probe_openrouter_api_key(plugin: OpenRouterPlugin, api_key: str) -> tuple[bool, str, dict[str, Any]]:
    request = urllib.request.Request(
        _models_endpoint(plugin.endpoint),
        headers=_openrouter_request_headers(api_key),
    )
    timeout_seconds = min(max(int(plugin.timeout_seconds or 0), 5), 20)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return False, plugin._describe_http_error(exc, "openrouter/models"), {}
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        return False, "openrouter_models_parse_error", {}
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return False, "openrouter_models_invalid_payload", {}
    return True, "", {"models_count": len(items)}

    @staticmethod
    def _mock_result(warnings: list[str]) -> PluginResult:
        title, reason, detail, fix_steps = OpenRouterPlugin._fallback_diagnostics(warnings)
        lines = [
            f"# {title}",
            "",
            "This is a fallback summary because the OpenRouter request could not be completed.",
            "",
            f"Reason: {reason}",
        ]
        if detail:
            lines.extend(["", f"Detail: `{detail}`"])
        if fix_steps:
            lines.extend(["", "To fix:"])
            lines.extend([f"- {step}" for step in fix_steps])
        text = "\n".join(lines)
        outputs = [PluginOutput(kind=KIND_SUMMARY, content=text, content_type="text/markdown")]
        if "mock_fallback" not in warnings:
            warnings = list(warnings) + ["mock_fallback"]
        return PluginResult(outputs=outputs, warnings=warnings)

    @staticmethod
    def _fallback_diagnostics(warnings: list[str]) -> tuple[str, str, str, list[str]]:
        items = [str(item).strip() for item in (warnings or []) if str(item).strip()]
        detail = OpenRouterPlugin._first_detail_warning(items)

        if any(item in {"api_key_missing", "openrouter_key_missing"} for item in items):
            return (
                "OpenRouter is not configured",
                "API key is missing.",
                detail,
                ["Add API key in Settings -> LLM -> OpenRouter.", "Re-run the stage."],
            )

        status = OpenRouterPlugin._extract_http_status(items)
        if status == 429:
            return (
                "OpenRouter rate limit",
                "Upstream provider returned HTTP 429 (Too Many Requests).",
                detail,
                [
                    "Retry later.",
                    "Use another enabled model/provider in this run.",
                    "Use your own key/credits to avoid shared free-tier limits.",
                ],
            )
        if status == 404:
            return (
                "OpenRouter request failed",
                "HTTP 404 from API (endpoint or model id is invalid).",
                detail,
                ["Verify endpoint URL.", "Verify model_id in plugin settings.", "Re-run the stage."],
            )
        if status == 400:
            return (
                "OpenRouter bad request",
                "HTTP 400: request payload was rejected by API.",
                detail,
                ["Check model_id and prompt configuration.", "Re-run plugin health test in Settings."],
            )
        if status in {401, 403}:
            return (
                "OpenRouter authorization failed",
                f"HTTP {status}: access denied.",
                detail,
                ["Check API key validity and permissions.", "Re-run the stage."],
            )
        if any(item.startswith("openrouter_empty_response") for item in items):
            return (
                "OpenRouter returned empty response",
                "The API request completed but returned no usable content.",
                detail,
                ["Retry the stage.", "Switch to another model for this run."],
            )
        return (
            "OpenRouter request failed",
            "The request could not be completed.",
            detail,
            ["Check network/API availability.", "Review plugin test results in Settings.", "Re-run the stage."],
        )

    @staticmethod
    def _extract_http_status(warnings: list[str]) -> int | None:
        for item in warnings:
            match = re.search(r"status=(\d{3})", item)
            if not match:
                continue
            try:
                return int(match.group(1))
            except Exception:
                return None
        return None

    @staticmethod
    def _first_detail_warning(warnings: list[str]) -> str:
        skip = {
            "mock_fallback",
            "openrouter_request_failed",
            "openrouter_empty_response",
            "empty_input_text",
            "api_key_missing",
            "openrouter_key_missing",
        }
        for item in warnings:
            if item in skip:
                continue
            return item[:220]
        return ""

    def _resolve_prompt(self, transcript: str) -> str:
        presets = normalize_presets(self.prompt_presets) or load_prompt_presets()
        main_prompt = resolve_prompt(self.prompt_profile, presets, self.prompt_custom)
        if not main_prompt:
            return ""
        return build_prompt(
            transcript=transcript,
            main_prompt=main_prompt,
            language_override=self.prompt_language,
            max_words=self.prompt_max_words,
        )


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_SUMMARY, ArtifactSchema(content_type="text/markdown", user_visible=True))
        ctx.register_hook_handler("derive.after_postprocess", hook_derive_summary, mode="optional", priority=100)
        ctx.register_settings_schema(settings_schema)
        ctx.register_actions(action_descriptors)
        _ensure_default_settings(ctx)


def hook_derive_summary(ctx: HookContext) -> PluginResult:
    params = _filtered_params(ctx.plugin_config or {})
    plugin = OpenRouterPlugin(**params) if params else OpenRouterPlugin()
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


def _filtered_params(params: dict) -> dict:
    allowed = {
        "api_key",
        "model_id",
        "system_prompt",
        "prompt_profile",
        "prompt_custom",
        "prompt_language",
        "prompt_presets",
        "prompt_max_words",
        "max_tokens",
        "temperature",
        "endpoint",
        "timeout_seconds",
    }
    mapped = {
        "user_api_key": "api_key",
        "paid_api_key": "api_key",
    }
    filtered: dict = {}
    for key, value in params.items():
        if key in mapped:
            filtered[mapped[key]] = value
            continue
        if key in allowed:
            filtered[key] = value
    return filtered


def _coerce_timeout_seconds(value: object, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _extract_message_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            text = _extract_choice_text(choice)
            if text:
                return text
    return _normalize_text_value(payload.get("output_text"))


def _extract_choice_text(choice: object) -> str:
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if isinstance(message, dict):
        for key in ("content", "text", "output_text"):
            text = _normalize_text_value(message.get(key))
            if text:
                return text
    for key in ("text", "content"):
        text = _normalize_text_value(choice.get(key))
        if text:
            return text
    return ""


def _normalize_text_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _normalize_text_value(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "output_text"):
            text = _normalize_text_value(value.get(key))
            if text:
                return text
    return ""


def _response_debug_signature(payload: object) -> str:
    if not isinstance(payload, dict):
        return f"type={type(payload).__name__}"
    summary: dict[str, Any] = {
        "keys": sorted(str(key) for key in payload.keys())[:12],
    }
    choices = payload.get("choices")
    if isinstance(choices, list):
        summary["choices_count"] = len(choices)
        if choices:
            first = choices[0]
            summary["first_choice_type"] = type(first).__name__
            if isinstance(first, dict):
                summary["first_choice_keys"] = sorted(str(key) for key in first.keys())[:12]
                finish_reason = first.get("finish_reason")
                if isinstance(finish_reason, str) and finish_reason:
                    summary["finish_reason"] = finish_reason
                message = first.get("message")
                summary["message_type"] = type(message).__name__
                if isinstance(message, dict):
                    summary["message_keys"] = sorted(str(key) for key in message.keys())[:12]
                    content = message.get("content")
                    summary["message_content_type"] = type(content).__name__
                    if isinstance(content, list):
                        summary["message_content_items"] = len(content)
    usage = payload.get("usage")
    if isinstance(usage, dict):
        usage_summary = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
            if key in usage:
                usage_summary[key] = usage.get(key)
        if usage_summary:
            summary["usage"] = usage_summary
    serialized = json.dumps(summary, ensure_ascii=True, separators=(",", ":"))
    return serialized[:320]


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "Provider Settings",
        "description": "Configure API key and models.",
        "layout": {
            "type": "tabs",
            "tabs": [
                {"id": "auth", "title": "Auth"},
                {"id": "models", "title": "Models"},
            ],
        },
        "views": [
            {
                "id": "auth",
                "type": "form",
                "sections": [
                    {
                        "id": "credentials",
                        "title": "Credentials",
                        "fields": [
                            {
                                "id": "api_key",
                                "label": "API Key",
                                "type": "secret",
                                "required": False,
                            },
                        ],
                    },
                ],
            },
            {
                "id": "models",
                "type": "table",
                "binding": "models",
                "title": "Models",
                "description": "Enable models and test connectivity.",
                "columns": [
                    {"id": "model_id", "label": "Model ID", "type": "string"},
                    {"id": "product_name", "label": "Name", "type": "string"},
                    {"id": "enabled", "label": "Enabled", "type": "bool"},
                    {"id": "status", "label": "Status", "type": "status", "readonly": True},
                ],
                "row_id": "model_id",
                "row_actions": [
                    {
                        "id": "test_model",
                        "label": "Test",
                        "params": [{"id": "model_id", "source": "row.model_id"}],
                    }
                ],
                "toolbar_actions": [
                    {"id": "test_connection", "label": "Test Connection"},
                    {"id": "test_models", "label": "Test Enabled Models"},
                    {"id": "retest_failed_models", "label": "Retest Failed Models"},
                    {"id": "list_models", "label": "Refresh Models"},
                ],
                "selection": {"mode": "single"},
            },
        ],
    }


def _plugin_from_settings(settings: dict) -> OpenRouterPlugin:
    api_key = str(
        settings.get("api_key", "")
        or settings.get("user_api_key", "")
        or settings.get("paid_api_key", "")
    ).strip() or None
    endpoint = str(settings.get("endpoint", "")).strip() or "https://openrouter.ai/api/v1/chat/completions"
    model_id = _selected_model_id(settings)
    return OpenRouterPlugin(
        api_key=api_key,
        model_id=model_id,
        endpoint=endpoint,
    )


def _selected_model_id(settings: dict) -> str | None:
    direct = str(settings.get("model_id", "")).strip()
    if direct:
        return direct
    rows = settings.get("models")
    if isinstance(rows, list):
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            if entry.get("enabled") is not True:
                continue
            model_id = str(entry.get("model_id", "")).strip()
            if model_id:
                return model_id
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model_id", "")).strip()
            if model_id:
                return model_id
    return None


def action_test_connection(settings: dict, params: dict) -> ActionResult:
    plugin = _plugin_from_settings(settings)
    api_key, status = plugin._resolve_api_key()
    if status != "ok":
        return ActionResult(
            status="error",
            message=status,
            data={"status": "error", "availability_status": "needs_setup", "failure_code": "auth_error"},
        )
    ok, error, data = _probe_openrouter_api_key(plugin, api_key)
    if not ok:
        failure_code, _selectable, _cooldown = _classify_openrouter_error(error)
        return ActionResult(
            status="error",
            message=error,
            data={
                "status": "error",
                "availability_status": _availability_status_from_openrouter_failure(failure_code),
                "failure_code": failure_code,
            },
        )
    return ActionResult(
        status="success",
        message="connection_ok",
        data={"status": "ok", "availability_status": "ready", **data},
    )


def action_list_models(settings: dict, params: dict) -> ActionResult:
    cached = {}
    user_added_rows: list[dict[str, Any]] = []
    for entry in settings.get("models", []) if isinstance(settings.get("models"), list) else []:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id", "")).strip()
        if model_id:
            cached[model_id] = entry
            if bool(entry.get("user_added", False)):
                user_added_rows.append(dict(entry))
    plugin = _plugin_from_settings(settings)
    api_key, _status = plugin._resolve_api_key()
    now_ts = int(time.time())
    key_probe_ok = False
    key_probe_payload: dict[str, Any] = {}
    if api_key:
        key_probe_ok, _key_probe_error, key_probe_payload = _probe_openrouter_api_key(plugin, api_key)
    user_added_ids = {
        str(entry.get("model_id", "")).strip()
        for entry in user_added_rows
        if str(entry.get("model_id", "")).strip()
    }
    remote = _fetch_openrouter_models(
        endpoint=plugin.endpoint,
        api_key=api_key,
        enabled_or_selected=user_added_ids,
    )
    source = list(remote) if remote else [
        {
            "model_id": model.model_id,
            "product_name": model.product_name or model.model_id,
            "description": model.description,
            "highlights": model.highlights,
            "context_window": model.context_window,
            "size_hint": model.size_hint,
            "source_url": model.source_url,
        }
        for model in FREE_MODELS
    ]
    source_ids = {
        str(item.get("model_id", "")).strip()
        for item in source
        if isinstance(item, dict) and str(item.get("model_id", "")).strip()
    }
    for entry in user_added_rows:
        model_id = str(entry.get("model_id", "")).strip()
        if not model_id or model_id in source_ids:
            continue
        source.append(dict(entry))
        source_ids.add(model_id)
    auto_disable = _to_bool(settings.get("auto_disable_on_fail"), default=False)
    models: list[dict[str, Any]] = []
    for item in source:
        model_id = str(item.get("model_id", "")).strip()
        if not model_id:
            continue
        previous = cached.get(model_id, {})
        curated = _FREE_MODELS_BY_ID.get(model_id)
        row = {
            "model_id": model_id,
            "product_name": str(item.get("product_name", "") or model_id).strip(),
            "source_url": str(
                item.get("source_url", "")
                or getattr(curated, "source_url", "")
                or _openrouter_model_page(model_id)
            ).strip(),
            "enabled": bool(previous.get("enabled", False)),
            "status": str(previous.get("status", "") or "").strip(),
            "availability_status": str(previous.get("availability_status", "") or "").strip(),
            "description": str(
                item.get("description", "")
                or getattr(curated, "description", "")
            ).strip(),
            "highlights": str(
                item.get("highlights", "")
                or getattr(curated, "highlights", "")
            ).strip(),
            "context_window": int(
                item.get("context_window", 0)
                or getattr(curated, "context_window", 0)
                or 0
            ),
            "size_hint": str(
                item.get("size_hint", "")
                or getattr(curated, "size_hint", "")
                or "Cloud API"
            ).strip(),
            "selectable": bool(previous.get("selectable", False)),
            "failure_code": str(previous.get("failure_code", "") or "").strip(),
            "cooldown_until": int(previous.get("cooldown_until", 0) or 0),
            "last_checked_at": int(previous.get("last_checked_at", 0) or 0),
            "last_ok_at": int(previous.get("last_ok_at", 0) or 0),
        }
        row = _apply_cached_openrouter_policy(row, now_ts=now_ts)
        if api_key and model_id in user_added_ids:
            row = _probe_openrouter_row(plugin, row, now_ts=now_ts, auto_disable=auto_disable)
        elif (
            key_probe_ok
            and not str(row.get("failure_code", "") or "").strip()
            and int(row.get("cooldown_until", 0) or 0) <= now_ts
        ):
            row["selectable"] = True
            if not str(row.get("status", "") or "").strip():
                row["status"] = "ready"
            if int(row.get("last_ok_at", 0) or 0) <= 0:
                row["last_ok_at"] = now_ts
        row["availability_status"] = _normalize_openrouter_availability_status(row)
        models.append(row)
    options = [
        {"label": str(item.get("product_name", "") or item.get("model_id", "")), "value": str(item.get("model_id", ""))}
        for item in models
        if str(item.get("model_id", "")).strip() and item.get("selectable") is True
    ]
    return ActionResult(
        status="success",
        message="models_loaded",
        data={"options": options, "models": models, "key_probe_ok": key_probe_ok, **key_probe_payload},
    )


def _openrouter_model_page(model_id: str) -> str:
    mid = str(model_id or "").strip()
    if not mid:
        return ""
    # OpenRouter uses stable per-model pages under /models.
    return f"https://openrouter.ai/models/{mid}"


def _fetch_openrouter_models(
    *,
    endpoint: str,
    api_key: str | None,
    enabled_or_selected: set[str],
) -> list[dict]:
    import urllib.error

    models_endpoint = _models_endpoint(endpoint)
    headers = {"Content-Type": "application/json"}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(models_endpoint, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
    except Exception:
        return []
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    selected = {str(mid or "").strip() for mid in enabled_or_selected if str(mid or "").strip()}
    models: list[dict] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id", "")).strip()
        if not model_id:
            continue
        name = str(entry.get("name", "") or "").strip()
        haystack = f"{model_id} {name}".lower()
        include = model_id in selected or (model_id.endswith(":free") and "qwen" in haystack)
        if not include:
            continue
        models.append(
            {
                "model_id": model_id,
                "product_name": name or model_id,
                "description": str(entry.get("description", "") or "").strip(),
                "context_window": int(entry.get("context_length", 0) or entry.get("context_window", 0) or 0),
                "source_url": _openrouter_model_page(model_id),
                "size_hint": "Cloud API",
            }
        )
        if len(models) >= 250:
            break
    return models


def _models_endpoint(endpoint: str) -> str:
    raw = str(endpoint or "").strip()
    if not raw:
        return "https://openrouter.ai/api/v1/models"
    normalized = raw.rstrip("/")
    suffix = "/chat/completions"
    if normalized.endswith(suffix):
        return normalized[: -len(suffix)] + "/models"
    return "https://openrouter.ai/api/v1/models"


def _safe_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return -1.0


def _to_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _apply_cached_openrouter_policy(row: dict[str, Any], *, now_ts: int) -> dict[str, Any]:
    updated = dict(row)
    cooldown_until = int(updated.get("cooldown_until", 0) or 0)
    if cooldown_until > now_ts:
        updated["selectable"] = False
        if not str(updated.get("status", "") or "").strip():
            updated["status"] = "rate_limited"
        return updated
    if cooldown_until:
        updated["cooldown_until"] = 0
    failure_code = str(updated.get("failure_code", "") or "").strip().lower()
    status = str(updated.get("status", "") or "").strip().lower()
    if failure_code in {"provider_blocked", "model_not_found", "not_available"}:
        updated["selectable"] = False
    elif failure_code in {"rate_limited", "request_failed", "empty_response"} or status == "rate_limited":
        updated["selectable"] = True
    elif status in {"ok", "ready"} and int(updated.get("last_ok_at", 0) or 0) > 0:
        updated["selectable"] = True
    return updated


def _availability_status_from_openrouter_failure(failure_code: str) -> str:
    code = str(failure_code or "").strip().lower()
    if code == "rate_limited":
        return "limited"
    if code in {
        "provider_blocked",
        "model_not_found",
        "not_available",
        "auth_error",
        "bad_request",
        "empty_response",
        "request_failed",
    }:
        return "unavailable"
    return "unknown"


def _normalize_openrouter_availability_status(row: dict[str, Any]) -> str:
    now_ts = int(time.time())
    cooldown_until = int(row.get("cooldown_until", 0) or 0)
    status = str(row.get("status", "") or "").strip().lower()
    failure_code = str(row.get("failure_code", "") or "").strip().lower()
    explicit = str(row.get("availability_status", "") or "").strip().lower()
    stale_transient_failure = cooldown_until <= now_ts and failure_code in {
        "rate_limited",
        "request_failed",
        "empty_response",
    }
    stale_rate_limit_status = cooldown_until <= now_ts and status == "rate_limited"
    if explicit in {"ready", "needs_setup", "unknown", "limited", "unavailable"}:
        if explicit == "limited" and (stale_transient_failure or stale_rate_limit_status):
            return "unknown"
        return explicit
    selectable = row.get("selectable")
    if cooldown_until > now_ts or failure_code == "rate_limited" or status == "rate_limited":
        return "limited"
    if stale_transient_failure:
        return "unknown"
    if failure_code:
        return _availability_status_from_openrouter_failure(failure_code)
    if status in {"ok", "ready"} or selectable is True:
        return "ready"
    return "unknown"


def _classify_openrouter_error(error: str) -> tuple[str, bool, int]:
    text = str(error or "").strip()
    lowered = text.lower()
    status = OpenRouterPlugin._extract_http_status([text])
    if status == 429:
        return "rate_limited", False, OPENROUTER_RATE_LIMIT_COOLDOWN_SECONDS
    if "at capacity" in lowered or "temporarily overloaded" in lowered or "retry shortly" in lowered:
        return "rate_limited", False, OPENROUTER_RATE_LIMIT_COOLDOWN_SECONDS
    if status == 404 or "model_not_found" in lowered:
        return "model_not_found", False, 0
    if status == 403 and ("blocked" in lowered or "provider returned error" in lowered or "google ai studio" in lowered):
        return "provider_blocked", False, 0
    if status == 400:
        return "bad_request", False, OPENROUTER_TRANSIENT_COOLDOWN_SECONDS
    if text.startswith("openrouter_empty_response"):
        return "empty_response", False, OPENROUTER_TRANSIENT_COOLDOWN_SECONDS
    if status in {401, 402}:
        return "auth_error", False, 0
    return "request_failed", False, OPENROUTER_TRANSIENT_COOLDOWN_SECONDS


def _probe_openrouter_row(
    plugin: OpenRouterPlugin,
    row: dict[str, Any],
    *,
    now_ts: int,
    auto_disable: bool,
) -> dict[str, Any]:
    updated = dict(row)
    api_key, status = plugin._resolve_api_key()
    if status != "ok" or not api_key:
        return updated
    model_id = str(updated.get("model_id", "") or "").strip()
    if not model_id:
        return updated
    _content, error = plugin._call_openrouter(api_key, model_id, "ping", "", quiet=True)
    updated["last_checked_at"] = now_ts
    if error:
        failure_code, selectable, cooldown_seconds = _classify_openrouter_error(error)
        updated["status"] = failure_code
        updated["availability_status"] = _availability_status_from_openrouter_failure(failure_code)
        updated["failure_code"] = failure_code
        updated["selectable"] = selectable
        updated["cooldown_until"] = now_ts + cooldown_seconds if cooldown_seconds > 0 else 0
        if auto_disable and failure_code not in {"auth_error"}:
            updated["enabled"] = False
        return updated
    updated["status"] = "ok"
    updated["availability_status"] = "ready"
    updated["failure_code"] = ""
    updated["selectable"] = True
    updated["cooldown_until"] = 0
    updated["last_ok_at"] = now_ts
    return updated


def _prompt_refiner_system_prompt() -> str:
    return (
        "You are an expert prompt engineer for meeting AI workflows. "
        "Refine the user's prompt while preserving original intent. "
        "Make it clear, concise, executable, and safe. "
        "Do not invent unavailable data sources. "
        "Return only the final refined prompt text without markdown fences or explanations."
    )


def _prompt_refiner_user_text(prompt_text: str, objective: str) -> str:
    objective_text = str(objective or "").strip() or (
        "Improve clarity, structure, and instruction quality without changing core intent."
    )
    return (
        "Refine this user prompt for a meeting-summary assistant.\n\n"
        f"Original prompt:\n{str(prompt_text or '').strip()}\n\n"
        f"Refinement objective:\n{objective_text}\n\n"
        "Output requirements:\n"
        "- return a single prompt text\n"
        "- no markdown code fences\n"
        "- keep language and intent of the original prompt"
    )


def _sanitize_refined_prompt(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            value = "\n".join(lines[1:-1]).strip()
    return value.strip()


def action_refine_prompt(settings: dict, params: dict) -> ActionResult:
    prompt_text = str(params.get("prompt_text", "")).strip()
    if not prompt_text:
        return ActionResult(status="error", message="prompt_text_missing")
    objective = str(params.get("objective", "")).strip()
    plugin = _plugin_from_settings(settings)
    api_key, status = plugin._resolve_api_key()
    if status != "ok":
        return ActionResult(status="error", message=status)
    model_id = plugin._resolve_model_id()
    content, error = plugin._call_openrouter(
        api_key,
        model_id,
        _prompt_refiner_user_text(prompt_text, objective),
        _prompt_refiner_system_prompt(),
    )
    if error:
        return ActionResult(status="error", message=error, data={"model_id": model_id})
    refined = _sanitize_refined_prompt(content)
    if not refined:
        return ActionResult(status="error", message="refined_prompt_empty", data={"model_id": model_id})
    return ActionResult(
        status="success",
        message="prompt_refined",
        data={"prompt": refined, "model_id": model_id},
    )


def action_test_model(settings: dict, params: dict) -> ActionResult:
    model_id = str(params.get("model_id", "")).strip()
    if not model_id:
        return ActionResult(status="error", message="model_id_missing")
    plugin = _plugin_from_settings(settings)
    api_key, status = plugin._resolve_api_key()
    if status != "ok":
        return ActionResult(
            status="error",
            message=status,
            data={
                "model_id": model_id,
                "status": "error",
                "availability_status": "needs_setup",
                "failure_code": "auth_error",
            },
        )
    content, error = plugin._call_openrouter(api_key, model_id, "ping", "", quiet=True)
    if error:
        failure_code, _selectable, _cooldown = _classify_openrouter_error(error)
        return ActionResult(
            status="error",
            message=error,
            data={
                "model_id": model_id,
                "status": "error",
                "availability_status": _availability_status_from_openrouter_failure(failure_code),
                "failure_code": failure_code,
            },
        )
    return ActionResult(
        status="success",
        message="model_ok",
        data={"model_id": model_id, "status": "ok", "availability_status": "ready"},
    )


def action_test_models(settings: dict, params: dict) -> ActionResult:
    plugin = _plugin_from_settings(settings)
    api_key, status = plugin._resolve_api_key()
    if status != "ok":
        return ActionResult(status="error", message=status, data={"status": "error"})
    models = []
    ok_count = 0
    error_count = 0
    source = settings.get("models", []) if isinstance(settings.get("models"), list) else []
    for entry in source:
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled", True):
            continue
        model_id = str(entry.get("model_id", "")).strip()
        if not model_id:
            continue
        _, error = plugin._call_openrouter(api_key, model_id, "ping", "", quiet=True)
        status_value = "error" if error else "ok"
        if error:
            error_count += 1
        else:
            ok_count += 1
        models.append(
            {
                "model_id": model_id,
                "status": status_value,
            }
        )
    summary = {"total": ok_count + error_count, "ok": ok_count, "error": error_count}
    return ActionResult(status="success", message="model_checks_complete", data={"models": models, "summary": summary})


def action_retest_failed_models(settings: dict, params: dict) -> ActionResult:
    plugin = _plugin_from_settings(settings)
    api_key, status = plugin._resolve_api_key()
    if status != "ok" or not api_key:
        return ActionResult(status="error", message=status or "api_key_missing", data={"status": "error"})

    now_ts = int(time.time())
    rows = settings.get("models", []) if isinstance(settings.get("models"), list) else []
    cached: dict[str, dict[str, Any]] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id", "") or "").strip()
        if model_id:
            cached[model_id] = dict(entry)

    auto_disable = _to_bool(settings.get("auto_disable_on_fail"), default=False)
    models: list[dict[str, Any]] = []
    retested = 0
    selectable_count = 0
    for model in FREE_MODELS:
        model_id = str(model.model_id or "").strip()
        if not model_id:
            continue
        previous = cached.get(model_id, {})
        row = {
            "model_id": model_id,
            "product_name": model.product_name or model_id,
            "source_url": model.source_url or _openrouter_model_page(model_id),
            "enabled": bool(previous.get("enabled", False)),
            "status": str(previous.get("status", "") or "").strip(),
            "description": model.description,
            "highlights": model.highlights,
            "context_window": int(model.context_window or 0),
            "size_hint": model.size_hint or "Cloud API",
            "selectable": bool(previous.get("selectable", False)),
            "failure_code": str(previous.get("failure_code", "") or "").strip(),
            "cooldown_until": int(previous.get("cooldown_until", 0) or 0),
            "last_checked_at": int(previous.get("last_checked_at", 0) or 0),
            "last_ok_at": int(previous.get("last_ok_at", 0) or 0),
        }
        row = _apply_cached_openrouter_policy(row, now_ts=now_ts)
        if _openrouter_row_needs_retest(row, now_ts=now_ts):
            row = _probe_openrouter_row(plugin, row, now_ts=now_ts, auto_disable=auto_disable)
            retested += 1
        if row.get("selectable") is True:
            selectable_count += 1
        models.append(row)

    return ActionResult(
        status="success",
        message="retest_failed_models_complete",
        data={
            "models": models,
            "summary": {"retested": retested, "selectable": selectable_count, "total": len(models)},
        },
    )


def action_descriptors() -> list[ActionDescriptor]:
    return [
        ActionDescriptor(
            action_id="test_connection",
            label="Test Connection",
            description="Verify credentials and endpoint.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_test_connection,
        ),
        ActionDescriptor(
            action_id="test_models",
            label="Test Enabled Models",
            description="Check all enabled models.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_test_models,
        ),
        ActionDescriptor(
            action_id="retest_failed_models",
            label="Retest Failed Models",
            description="Retest blocked, cooling-down, and unverified models.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_retest_failed_models,
        ),
        ActionDescriptor(
            action_id="refine_prompt",
            label="Refine Prompt",
            description="Refine a user prompt with the current LLM model.",
            params_schema={
                "fields": [
                    {"id": "prompt_text", "type": "string", "required": True},
                    {"id": "objective", "type": "string", "required": False},
                ]
            },
            dangerous=False,
            handler=action_refine_prompt,
        ),
        ActionDescriptor(
            action_id="list_models",
            label="Refresh Models",
            description="Load available models for the dropdown.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_list_models,
        ),
        ActionDescriptor(
            action_id="test_model",
            label="Test Model",
            description="Check a single model availability.",
            params_schema={"fields": [{"id": "model_id", "type": "string", "required": True}]},
            dangerous=False,
            handler=action_test_model,
        ),
    ]


def _ensure_default_settings(ctx) -> None:
    settings = ctx.get_settings()
    if settings.get("models"):
        return
    # Default: keep the catalog, but don't auto-enable everything.
    defaults = []
    for idx, model in enumerate(FREE_MODELS):
        defaults.append(
            {
                "model_id": model.model_id,
                "product_name": model.product_name or model.model_id,
                "enabled": idx == 0,
            }
        )
    if defaults:
        payload = dict(settings)
        payload["models"] = defaults
        ctx.set_settings(payload, secret_fields=["api_key"])


def _openrouter_row_needs_retest(row: dict[str, Any], *, now_ts: int) -> bool:
    selectable = row.get("selectable")
    status = str(row.get("status", "") or "").strip().lower()
    failure_code = str(row.get("failure_code", "") or "").strip().lower()
    cooldown_until = int(row.get("cooldown_until", 0) or 0)
    if selectable is True and status in {"ok", "ready"}:
        return False
    if cooldown_until > now_ts:
        return False
    return failure_code != "auth_error"
