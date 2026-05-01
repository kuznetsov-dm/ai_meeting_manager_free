from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
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
class ZaiModel:
    model_id: str
    product_name: str
    context_window: int
    highlights: str
    description: str


_LEGACY_MODEL_ALIASES = {
    "glm-4-flash": "glm-4.7-flash",
    "glm-4.5-flash-free": "glm-4.5-flash",
    "glm-4.7-flash-free": "glm-4.7-flash",
}

_ZAI_REQUEST_LOCK = threading.Lock()
_ZAI_PAAS_CHAT_SUFFIX = "/api/paas/v4/chat/completions"
_ZAI_CODING_CHAT_SUFFIX = "/api/coding/paas/v4/chat/completions"


def _normalize_model_id(value: object) -> str:
    model_id = str(value or "").strip().lower()
    if not model_id:
        return ""
    return _LEGACY_MODEL_ALIASES.get(model_id, model_id)


def _model_title(model_id: str) -> str:
    wanted = _normalize_model_id(model_id)
    for item in MODELS:
        if item.model_id == wanted:
            return item.product_name
    return wanted


def _normalize_models_payload(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        model_id = _normalize_model_id(entry.get("model_id") or entry.get("id"))
        if not model_id or model_id not in _ALLOWED_MODEL_IDS or model_id in seen:
            continue
        seen.add(model_id)
        out.append(
            {
                "model_id": model_id,
                "product_name": str(entry.get("product_name", "") or _model_title(model_id)).strip(),
                "description": str(entry.get("description", "") or "").strip(),
                "highlights": str(entry.get("highlights", "") or "").strip(),
                "context_window": int(entry.get("context_window", 0) or 0),
                "size_hint": str(entry.get("size_hint", "") or "").strip(),
            }
        )
    for item in MODELS:
        if item.model_id in seen:
            continue
        out.append(
            {
                "model_id": item.model_id,
                "product_name": item.product_name,
                "description": item.description,
                "highlights": item.highlights,
                "context_window": item.context_window,
                "size_hint": (
                    f"Free API, {item.context_window // 1000}k context"
                    if item.context_window
                    else "Free API"
                ),
            }
        )
    return out


def load_models() -> list[ZaiModel]:
    """Load and normalize Z.ai models from plugin passport."""
    models: list[ZaiModel] = []
    seen: set[str] = set()
    passport = {}
    try:
        passport_path = Path(__file__).resolve().with_name("plugin_passport.json")
        if passport_path.exists():
            passport = json.loads(passport_path.read_text(encoding="utf-8"))
    except Exception:
        passport = {}
    items = passport.get("models") if isinstance(passport, dict) else None
    if not isinstance(items, list):
        return []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        model_id = _normalize_model_id(entry.get("id", "") or entry.get("model_id", ""))
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append(
            ZaiModel(
                model_id=model_id,
                product_name=str(entry.get("name", "") or entry.get("product_name", "")).strip(),
                context_window=int(entry.get("context_window", 0) or 0),
                highlights=str(entry.get("highlights", "")).strip(),
                description=str(entry.get("description", "")).strip(),
            )
        )
    if models:
        return models
    return models


def _passport_models_meta() -> dict[str, dict]:
    try:
        passport_path = Path(__file__).resolve().with_name("plugin_passport.json")
        if not passport_path.exists():
            return {}
        payload = json.loads(passport_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    out: dict[str, dict] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        model_id = _normalize_model_id(entry.get("id", "") or entry.get("model_id", ""))
        if not model_id:
            continue
        out[model_id] = dict(entry)
    return out


MODELS: list[ZaiModel] = load_models()
_ALLOWED_MODEL_IDS = {item.model_id for item in MODELS}
_PASSPORT_MODEL_META = _passport_models_meta()


class ZaiPlugin:
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
        max_tokens: int = 4096,
        temperature: float = 0.2,
        endpoint: str = "https://api.z.ai/api/paas/v4/chat/completions",
        timeout_seconds: int = 60,
        disable_thinking: bool = False,
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
        self.disable_thinking = bool(disable_thinking)

    def run(self, ctx: HookContext) -> PluginResult:
        warnings: list[str] = []
        text = (ctx.input_text or "").strip()
        if not text:
            warnings.append("empty_input_text")
            text = "No transcript text provided."

        model_id = self._resolve_model_id()
        api_key = self._resolve_api_key()
        if not api_key:
            warnings.append("zai_api_key_missing")
            return self._mock_result(warnings)

        system_prompt = self._resolve_prompt(text)
        user_text = text if not system_prompt else "Summarize according to the system instructions."
        content, error = self._call_zai(api_key, model_id, user_text, system_prompt)
        if error:
            warnings.append(error)
            return self._mock_result(warnings)
        if not content:
            warnings.append("zai_empty_response")
            return self._mock_result(warnings)

        outputs = [PluginOutput(kind=KIND_SUMMARY, content=content, content_type="text/markdown")]
        return PluginResult(outputs=outputs, warnings=warnings)

    def _resolve_model_id(self) -> str:
        if self.model_id:
            normalized = _normalize_model_id(self.model_id)
            if normalized in _ALLOWED_MODEL_IDS:
                return normalized
        return self._default_model_id()

    @staticmethod
    def _default_model_id() -> str:
        return MODELS[0].model_id if MODELS else ""

    def _resolve_api_key(self) -> str | None:
        key = (self.api_key or os.getenv("AIMN_ZAI_API_KEY", "")).strip()
        return key if key else None

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[3]

    def _call_zai(
        self, api_key: str, model_id: str, text: str, system_prompt: str | None
    ) -> tuple[str, str]:
        logger = logging.getLogger("aimn.network.zai")
        data, error = self._request_zai(
            api_key=api_key,
            model_id=model_id,
            text=text,
            system_prompt=system_prompt,
            disable_thinking=self.disable_thinking,
            logger=logger,
        )
        if error:
            return "", error
        if data is None:
            return "", "zai_request_failed"
        try:
            raw_content = _extract_message_text(data)
            content = _postprocess_summary_text(raw_content)
            if not content:
                content = _best_effort_raw_text(raw_content)
            if not content and _should_retry_with_more_tokens(data):
                retry_tokens = _retry_max_tokens(self.max_tokens)
                retry_data, retry_error = self._request_zai(
                    api_key=api_key,
                    model_id=model_id,
                    text=text,
                    system_prompt=system_prompt,
                    disable_thinking=self.disable_thinking,
                    logger=logger,
                    max_tokens_override=retry_tokens,
                )
                if retry_data is not None:
                    retry_raw = _extract_message_text(retry_data)
                    retry_content = _postprocess_summary_text(retry_raw) or _best_effort_raw_text(retry_raw)
                    if retry_content:
                        logger.info("zai_request_ok model=%s mode=retry_more_tokens", model_id)
                        return retry_content, ""
                    data = retry_data
                    content = retry_content
                if retry_error:
                    logger.warning(
                        "zai_retry_more_tokens_failed model=%s error=%s",
                        model_id,
                        retry_error,
                    )
            if not content and _should_retry_with_thinking_disabled(data):
                retry_data, retry_error = self._request_zai(
                    api_key=api_key,
                    model_id=model_id,
                    text=text,
                    system_prompt=system_prompt,
                    disable_thinking=True,
                    logger=logger,
                )
                if retry_data is not None:
                    retry_raw = _extract_message_text(retry_data)
                    retry_content = _postprocess_summary_text(retry_raw) or _best_effort_raw_text(retry_raw)
                    if retry_content:
                        logger.info("zai_request_ok model=%s mode=retry_disable_thinking", model_id)
                        return retry_content, ""
                    data = retry_data
                if retry_error:
                    logger.warning(
                        "zai_retry_disable_thinking_failed model=%s error=%s",
                        model_id,
                        retry_error,
                    )
            if not content:
                details = _response_debug_signature(data)
                logger.warning("zai_empty_payload model=%s details=%s", model_id, details)
                return "", f"zai_empty_response details={details}"
            logger.info("zai_request_ok model=%s", model_id)
            return content, ""
        except Exception:
            logger.warning("zai_parse_error model=%s", model_id)
            return "", "zai_parse_error"

    def _request_zai(
        self,
        *,
        api_key: str,
        model_id: str,
        text: str,
        system_prompt: str | None,
        disable_thinking: bool,
        logger: logging.Logger,
        max_tokens_override: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        endpoint = str(self.endpoint or "").strip()
        if not endpoint:
            endpoint = f"https://api.z.ai{_ZAI_PAAS_CHAT_SUFFIX}"
        max_tokens = int(max_tokens_override) if max_tokens_override is not None else int(self.max_tokens)
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": _compose_system_prompt(system_prompt or self.system_prompt)},
                {"role": "user", "content": text},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if disable_thinking:
            payload["clear_thinking"] = True
            payload["thinking"] = {"type": "disabled"}
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        logger.info(
            "zai_request model=%s endpoint=%s timeout=%s disable_thinking=%s",
            model_id,
            endpoint,
            self.timeout_seconds,
            disable_thinking,
        )
        attempts = 3
        fallback_attempted = False

        def _send_request(endpoint_to_use: str) -> tuple[dict[str, Any] | None, str]:
            request = urllib.request.Request(endpoint_to_use, data=body, headers=headers)
            last_detail_local = ""
            with _ZAI_REQUEST_LOCK:
                for attempt in range(1, attempts + 1):
                    try:
                        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                            raw = response.read()
                        data = json.loads(raw.decode("utf-8"))
                        return (data if isinstance(data, dict) else {}), ""
                    except Exception as exc:
                        detail = self._describe_http_error(exc, model_id)
                        last_detail_local = detail
                        retryable = self._is_retryable_network_error(detail)
                        logger.warning(
                            "zai_request_failed model=%s attempt=%s/%s retryable=%s disable_thinking=%s error=%s",
                            model_id,
                            attempt,
                            attempts,
                            retryable,
                            disable_thinking,
                            detail,
                        )
                        if not retryable or attempt >= attempts:
                            return None, detail
                        time.sleep(min(2.0, 0.5 * attempt))
            return None, (last_detail_local or "zai_request_failed")

        data, error = _send_request(endpoint)
        if data is not None:
            return data, ""
        if not _should_retry_with_alternate_endpoint(error, endpoint):
            return None, error
        alternate_endpoint = _alternate_chat_endpoint(endpoint)
        if not alternate_endpoint or alternate_endpoint == endpoint:
            return None, error
        fallback_attempted = True
        logger.warning(
            "zai_endpoint_fallback model=%s from=%s to=%s",
            model_id,
            endpoint,
            alternate_endpoint,
        )
        logger.info(
            "zai_request model=%s endpoint=%s timeout=%s disable_thinking=%s",
            model_id,
            alternate_endpoint,
            self.timeout_seconds,
            disable_thinking,
        )
        alt_data, alt_error = _send_request(alternate_endpoint)
        if alt_data is not None:
            return alt_data, ""
        if fallback_attempted and alt_error:
            return None, f"{error} alt_endpoint={alternate_endpoint} alt_error={alt_error}"
        return None, (alt_error or error)

    @staticmethod
    def _is_retryable_network_error(detail: str) -> bool:
        text = str(detail or "").strip().lower()
        if not text:
            return False
        if "status=429" in text:
            return True
        if "status=500" in text or "status=502" in text or "status=503" in text or "status=504" in text:
            return True
        retry_tokens = (
            "timed out",
            "timeout",
            "temporarily unavailable",
            "temporary failure",
            "connection reset",
            "connection aborted",
            "remote end closed connection",
        )
        return any(token in text for token in retry_tokens)

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
                body = raw.decode("utf-8", errors="ignore")[:400]
        except Exception:
            pass
        parts = [f"zai_http_error(model={model_id})"]
        if status:
            parts.append(f"status={status}")
        if body:
            parts.append(f"body={body}")
        if message and message not in parts:
            parts.append(message)
        return " ".join(parts)

    @staticmethod
    def _mock_result(warnings: list[str]) -> PluginResult:
        title, reason, detail, fix_steps = ZaiPlugin._fallback_diagnostics(warnings)
        lines = [
            f"# {title}",
            "",
            "This is a fallback summary because the Z.ai request could not be completed.",
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
        detail = ZaiPlugin._first_detail_warning(items)

        if any(item == "zai_api_key_missing" for item in items):
            return (
                "Z.ai is not configured",
                "API key is missing.",
                detail,
                ["Add API key in Settings -> LLM -> Z.ai.", "Re-run the stage."],
            )

        status = ZaiPlugin._extract_http_status(items)
        api_code = ZaiPlugin._extract_api_error_code(items)
        if status == 429:
            return (
                "Z.ai rate limit",
                "API returned HTTP 429 (Too Many Requests or quota/credits issue).",
                detail,
                ["Retry later.", "Switch to another model/provider for this run."],
            )
        if status == 401 or api_code == 10001004:
            return (
                "Z.ai authorization failed",
                "Invalid or expired API key.",
                detail,
                ["Check API key in Settings -> LLM -> Z.ai.", "Verify Authorization header uses Bearer token."],
            )
        if status == 404:
            return (
                "Z.ai request failed",
                "HTTP 404 from API (endpoint or model id may be invalid).",
                detail,
                [
                    "Verify endpoint URL (paas vs coding endpoint).",
                    "Verify model_id.",
                    "Re-run the stage.",
                ],
            )
        if status == 400:
            return (
                "Z.ai bad request",
                "HTTP 400: request payload was rejected by API.",
                detail,
                ["Check model_id and prompt configuration.", "Re-run plugin health test in Settings."],
            )
        if status in {401, 403}:
            return (
                "Z.ai authorization failed",
                f"HTTP {status}: access denied.",
                detail,
                ["Check API key validity and permissions.", "Re-run the stage."],
            )
        if any(item.startswith("zai_empty_response") for item in items):
            return (
                "Z.ai returned empty response",
                "The request completed but returned no usable content.",
                detail,
                ["Retry the stage.", "Switch model/provider for this run."],
            )
        return (
            "Z.ai request failed",
            "The request could not be completed.",
            detail,
            ["Check network/API availability.", "Review plugin tests in Settings.", "Re-run the stage."],
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
    def _extract_api_error_code(warnings: list[str]) -> int | None:
        for item in warnings:
            match = re.search(r'"code"\s*:\s*(\d+)', item)
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
            "zai_empty_response",
            "empty_input_text",
            "zai_api_key_missing",
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
    plugin = ZaiPlugin(**params) if params else ZaiPlugin()
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
        "disable_thinking",
    }
    filtered: dict = {}
    for key, value in params.items():
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


def _alternate_chat_endpoint(endpoint: str) -> str | None:
    raw = str(endpoint or "").strip()
    if not raw:
        return None
    normalized = raw.rstrip("/")
    if normalized.endswith(_ZAI_PAAS_CHAT_SUFFIX):
        return normalized[: -len(_ZAI_PAAS_CHAT_SUFFIX)] + _ZAI_CODING_CHAT_SUFFIX
    if normalized.endswith(_ZAI_CODING_CHAT_SUFFIX):
        return normalized[: -len(_ZAI_CODING_CHAT_SUFFIX)] + _ZAI_PAAS_CHAT_SUFFIX
    return None


def _should_retry_with_alternate_endpoint(error_detail: str, endpoint: str) -> bool:
    if not _alternate_chat_endpoint(endpoint):
        return False
    text = str(error_detail or "").strip().lower()
    if not text:
        return False
    if "status=404" in text:
        return True
    if "status=400" not in text:
        return False
    mismatch_tokens = (
        "endpoint",
        "path",
        "route",
        "model not found",
        "unknown model",
        "unsupported model",
    )
    return any(token in text for token in mismatch_tokens)


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
        content_text = _normalize_text_value(message.get("content"))
        if content_text:
            return content_text
        for key in ("output_text", "text"):
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
        text = value.strip()
        if not text:
            return ""
        if text.startswith("{") and text.endswith("}"):
            parsed = _json_text_to_markdown(text)
            if parsed:
                return parsed
        return text
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return _extract_from_content_blocks(value)
        parts: list[str] = []
        for item in value:
            text = _normalize_text_value(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("parts", "items", "segments", "chunks"):
            nested = value.get(key)
            text = _normalize_text_value(nested)
            if text:
                return text
        for key in ("text", "content", "output_text"):
            text = _normalize_text_value(value.get(key))
            if text:
                return text
        collected: list[str] = []
        for item in value.values():
            text = _normalize_text_value(item)
            if text and text not in collected:
                collected.append(text)
        if collected:
            return "\n".join(collected).strip()
    return ""


def _extract_from_content_blocks(blocks: list[dict]) -> str:
    answer_parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if _is_reasoning_block(block):
            continue
        answer_text = _extract_block_answer_text(block)
        if answer_text:
            answer_parts.append(answer_text)
    if answer_parts:
        return "\n".join(answer_parts).strip()
    return ""


def _extract_block_answer_text(block: dict[str, Any]) -> str:
    for key in ("content", "output_text", "text", "value"):
        text = _normalize_text_value(block.get(key))
        if text:
            return text
    return ""


def _is_reasoning_block(block: dict[str, Any]) -> bool:
    block_type = str(block.get("type", "") or "").strip().lower()
    if not block_type:
        return False
    markers = ("reason", "thinking", "analysis", "cot")
    return any(marker in block_type for marker in markers)


def _postprocess_summary_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    original = value
    value = _unwrap_markdown_fence(value).strip()
    if not value:
        value = original
    if value.startswith("{") and value.endswith("}"):
        parsed = _json_text_to_markdown(value)
        if parsed:
            value = parsed
    value = _strip_reasoning_preamble(value)
    if not value:
        return str(original or "").strip()
    return str(value or "").strip()


def _best_effort_raw_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    unwrapped = _unwrap_markdown_fence(value).strip()
    if unwrapped:
        return unwrapped
    return value


def _compose_system_prompt(base_prompt: str) -> str:
    base = str(base_prompt or "").strip()
    suffix = (
        "Always provide a final answer in the content field after your reasoning process. "
        "Do not leave content empty."
    )
    if not base:
        return suffix
    lowered = base.lower()
    if "content field" in lowered and "do not leave content empty" in lowered:
        return base
    return f"{base}\n\n{suffix}"


def _retry_max_tokens(current: int) -> int:
    try:
        value = int(current)
    except Exception:
        value = 0
    if value < 2048:
        return 2048
    return min(value * 2, 8192)


def _should_retry_with_more_tokens(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    finish_reason = _normalized_finish_reason(first.get("finish_reason"))
    if finish_reason not in {"length", "max_tokens"}:
        return False
    message = first.get("message")
    if not isinstance(message, dict):
        return True
    content = _normalize_text_value(message.get("content"))
    if content:
        return False
    return True


def _should_retry_with_thinking_disabled(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    finish_reason = _normalized_finish_reason(first.get("finish_reason"))
    if finish_reason not in {"length", "max_tokens"}:
        return False
    message = first.get("message")
    if not isinstance(message, dict):
        return False
    content = _normalize_text_value(message.get("content"))
    if content:
        return False
    if _has_reasoning_signal(message):
        return True
    return finish_reason in {"length", "max_tokens"}


def _normalized_finish_reason(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in {"length", "max_tokens"}:
        return text
    if text.startswith("len"):
        return "length"
    if text in {"le", "max", "token_limit"}:
        return "length"
    if "max_token" in text:
        return "max_tokens"
    return text


def _has_reasoning_signal(message: dict[str, Any]) -> bool:
    reasoning = _normalize_text_value(message.get("reasoning_content"))
    if reasoning:
        return True
    if "reasoning_content" in message:
        return True
    content = message.get("content")
    if isinstance(content, dict) and _is_reasoning_block(content):
        return True
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and _is_reasoning_block(item):
                return True
    return False


def _unwrap_markdown_fence(text: str) -> str:
    value = str(text or "").strip()
    if not (value.startswith("```") and value.endswith("```")):
        return value
    lines = value.splitlines()
    if len(lines) < 2:
        return value
    body = lines[1:-1]
    return "\n".join(body).strip()


def _strip_reasoning_preamble(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if not _looks_like_reasoning_trace(value):
        return value
    value = _drop_leading_numbered_analysis_sections(value)
    if not value:
        return ""
    lowered = value.lower()

    final_markers = [
        "final summary",
        "итоговое резюме",
        "итоговый summary",
        "краткое резюме",
    ]
    for marker in final_markers:
        idx = lowered.find(marker)
        if idx >= 0:
            tail = value[idx + len(marker):].lstrip(" :\n\r\t-*")
            if tail:
                return tail.strip()

    heading_match = re.search(
        r"(?im)^(#{1,3}\s*(meeting topic|тема встречи|tasks|задачи|project names|проекты|key decisions|решения|brief meeting summary|краткое резюме))",
        value,
    )
    if heading_match and heading_match.start() > 0:
        return value[heading_match.start():].strip()

    lines = value.splitlines()
    while lines and re.match(r"^\s*\d+\.\s+\*\*(Analyze|Drafting|Reasoning)", lines[0], flags=re.IGNORECASE):
        lines.pop(0)
    cleaned = "\n".join(lines).strip()
    return cleaned or value


def _looks_like_reasoning_trace(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "analyze the request",
        "analyze the transcript",
        "drafting the summary",
        "chain-of-thought",
    )
    if any(marker in lowered for marker in markers):
        return True
    return bool(re.search(r"(?im)^\s*\d+\.\s+\*\*(analyze|drafting|reasoning)\b", lowered))


def _drop_leading_numbered_analysis_sections(text: str) -> str:
    lines = str(text or "").splitlines()
    if not lines:
        return ""
    section_re = re.compile(r"^\s*(\d+)\.\s+\*\*([^*]+)\*\*")
    final_heading_re = re.compile(
        r"(?im)^\s*(#{1,3}\s*(meeting topic|тема встречи|tasks|задачи|project names|проекты|key decisions|решения|brief meeting summary|краткое резюме|overall meeting summary|discussion flow|логика обсуждения)|\*{0,2}(meeting topic|тема встречи|tasks|задачи|project names|проекты|key decisions|решения|brief meeting summary|краткое резюме|overall meeting summary|discussion flow|логика обсуждения)\*{0,2}\s*:)",
    )
    analysis_tokens = ("analyze", "drafting", "reasoning", "analysis")
    idx = 0
    consumed_any = False
    while idx < len(lines):
        match = section_re.match(lines[idx])
        if not match:
            break
        title = str(match.group(2) or "").strip().lower()
        if not any(token in title for token in analysis_tokens):
            break
        consumed_any = True
        idx += 1
        while idx < len(lines):
            if final_heading_re.match(lines[idx]):
                break
            next_match = section_re.match(lines[idx])
            if next_match:
                break
            idx += 1
    if not consumed_any:
        return str(text or "").strip()
    return "\n".join(lines[idx:]).strip()


def _json_text_to_markdown(text: str) -> str:
    try:
        payload = json.loads(text)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    direct = _extract_summary_like_text(payload)
    if direct:
        return direct
    lines: list[str] = []
    title = str(payload.get("title", "") or payload.get("topic", "")).strip()
    if title:
        lines.append(f"# {title}")
        lines.append("")
    summary = str(payload.get("summary", "")).strip()
    if summary:
        lines.append(summary)
    actions = payload.get("action_items")
    if isinstance(actions, list) and actions:
        if lines:
            lines.append("")
        lines.append("## Action Items")
        for item in actions[:40]:
            text_item = str(item or "").strip()
            if text_item:
                lines.append(f"- {text_item}")
    return "\n".join(lines).strip()


def _extract_summary_like_text(payload: dict[str, Any]) -> str:
    keys = (
        "final",
        "final_answer",
        "answer",
        "result",
        "output",
        "markdown",
        "content",
        "text",
    )
    for key in keys:
        value = payload.get(key)
        extracted = _extract_scalar_text(value)
        if extracted:
            return extracted
    return ""


def _extract_scalar_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _extract_summary_like_text(value)
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            extracted = _extract_scalar_text(item)
            if extracted:
                chunks.append(extracted)
        return "\n".join(chunks).strip()
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
    """Return the settings schema for the Z.ai plugin."""
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
                                "label": "Z.ai API Key",
                                "type": "secret",
                                "help": "Get your API key from https://open.bigmodel.cn/usercenter/apikeys"
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
                    {"id": "list_models", "label": "Refresh Models"},
                ],
                "selection": {"mode": "single", "bind_to": "model_id"},
            },
        ],
    }


def _plugin_from_settings(settings: dict) -> ZaiPlugin:
    api_key = str(settings.get("api_key", "")).strip() or None
    endpoint = str(settings.get("endpoint", "")).strip() or "https://api.z.ai/api/paas/v4/chat/completions"
    model_id = _selected_model_id(settings)
    disable_thinking = bool(settings.get("disable_thinking", False))
    return ZaiPlugin(
        api_key=api_key,
        model_id=model_id,
        endpoint=endpoint,
        disable_thinking=disable_thinking,
    )


def _selected_model_id(settings: dict) -> str | None:
    direct = _normalize_model_id(settings.get("model_id", ""))
    if direct:
        if direct not in _ALLOWED_MODEL_IDS:
            return MODELS[0].model_id if MODELS else None
        return direct
    rows = settings.get("models")
    if isinstance(rows, list):
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            if entry.get("enabled") is not True:
                continue
            model_id = _normalize_model_id(entry.get("model_id", ""))
            if model_id:
                if model_id not in _ALLOWED_MODEL_IDS:
                    continue
                return model_id
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            model_id = _normalize_model_id(entry.get("model_id", ""))
            if model_id:
                if model_id not in _ALLOWED_MODEL_IDS:
                    continue
                return model_id
    return None


def action_test_connection(settings: dict, params: dict) -> ActionResult:
    plugin = _plugin_from_settings(settings)
    api_key = plugin._resolve_api_key()
    if not api_key:
        return ActionResult(
            status="error",
            message="zai_api_key_missing",
            data={"availability_status": "needs_setup", "failure_code": "auth_error"},
        )
    model_id = plugin._resolve_model_id()
    content, error = plugin._call_zai(api_key, model_id, "ping", "")
    if error:
        failure_code = _zai_failure_code(error)
        return ActionResult(
            status="error",
            message=error,
            data={
                "model_id": model_id,
                "availability_status": _zai_availability_status(failure_code),
                "failure_code": failure_code,
            },
        )
    return ActionResult(
        status="success",
        message="connection_ok",
        data={"model_id": model_id, "availability_status": "ready"},
    )


def action_list_models(settings: dict, params: dict) -> ActionResult:
    cached = {}
    for entry in settings.get("models", []) if isinstance(settings.get("models"), list) else []:
        if not isinstance(entry, dict):
            continue
        model_id = _normalize_model_id(entry.get("model_id", ""))
        if model_id:
            cached[model_id] = entry
    plugin = _plugin_from_settings(settings)
    api_key = plugin._resolve_api_key()
    remote = _fetch_zai_models(endpoint=plugin.endpoint, api_key=api_key)
    merged_source = list(remote or [])
    for model in MODELS:
        merged_source.append(
            {
                "model_id": model.model_id,
                "product_name": model.product_name or model.model_id,
                "description": model.description,
                "highlights": model.highlights,
                "context_window": model.context_window,
                "size_hint": (
                    f"Free API, {model.context_window // 1000}k context"
                    if model.context_window
                    else "Free API"
                ),
            }
        )
    for entry in cached.values():
        merged_source.append(dict(entry))
    source = _normalize_models_payload(merged_source)
    options = [
        {"label": str(item.get("product_name", "") or item.get("model_id", "")), "value": str(item.get("model_id", ""))}
        for item in source
        if str(item.get("model_id", "")).strip()
    ]
    models = []
    for item in source:
        model_id = str(item.get("model_id", "")).strip()
        if not model_id:
            continue
        passport_meta = _PASSPORT_MODEL_META.get(model_id, {})
        models.append(
            {
                "model_id": model_id,
                "product_name": str(item.get("product_name", "") or model_id).strip(),
                "source_url": str(
                    passport_meta.get("source_url", "")
                    or item.get("source_url", "")
                    or "https://docs.z.ai/"
                ).strip(),
                "enabled": cached.get(model_id, {}).get("enabled", False),
                "status": cached.get(model_id, {}).get("status", ""),
                "availability_status": _normalize_zai_availability_status(cached.get(model_id, {})),
                "description": str(item.get("description", "") or ""),
                "highlights": str(item.get("highlights", "") or ""),
                "context_window": int(item.get("context_window", 0) or 0),
                "size_hint": str(item.get("size_hint", "") or "Free API"),
            }
        )
    return ActionResult(status="success", message="models_loaded", data={"options": options, "models": models})


def _fetch_zai_models(*, endpoint: str, api_key: str | None) -> list[dict]:
    key = str(api_key or "").strip()
    if not key:
        return []
    models_endpoint = _models_endpoint(endpoint)
    request = urllib.request.Request(
        models_endpoint,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
    except Exception:
        return []
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    models: list[dict] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        model_id = _normalize_model_id(entry.get("id", ""))
        if not model_id or model_id not in _ALLOWED_MODEL_IDS:
            continue
        models.append(
            {
                "model_id": model_id,
                "product_name": _model_title(model_id),
            }
        )
    return models


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
    api_key = plugin._resolve_api_key()
    if not api_key:
        return ActionResult(status="error", message="zai_api_key_missing")
    model_id = plugin._resolve_model_id()
    content, error = plugin._call_zai(
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


def _models_endpoint(endpoint: str) -> str:
    raw = str(endpoint or "").strip()
    if not raw:
        return "https://api.z.ai/api/paas/v4/models"
    normalized = raw.rstrip("/")
    suffix = "/chat/completions"
    if normalized.endswith(suffix):
        return normalized[: -len(suffix)] + "/models"
    return "https://api.z.ai/api/paas/v4/models"


def action_test_model(settings: dict, params: dict) -> ActionResult:
    model_id = _normalize_model_id(params.get("model_id", ""))
    if not model_id:
        return ActionResult(status="error", message="model_id_missing")
    if model_id not in _ALLOWED_MODEL_IDS:
        return ActionResult(
            status="error",
            message="model_not_supported",
            data={"model_id": model_id, "availability_status": "unavailable", "failure_code": "model_not_found"},
        )
    plugin = _plugin_from_settings(settings)
    api_key = plugin._resolve_api_key()
    if not api_key:
        return ActionResult(
            status="error",
            message="zai_api_key_missing",
            data={"model_id": model_id, "availability_status": "needs_setup", "failure_code": "auth_error"},
        )
    content, error = plugin._call_zai(api_key, model_id, "ping", "")
    if error:
        failure_code = _zai_failure_code(error)
        return ActionResult(
            status="error",
            message=error,
            data={
                "model_id": model_id,
                "availability_status": _zai_availability_status(failure_code),
                "failure_code": failure_code,
            },
        )
    return ActionResult(status="success", message="model_ok", data={"model_id": model_id, "availability_status": "ready"})


def _zai_failure_code(message: str) -> str:
    text = str(message or "").strip().lower()
    if not text:
        return "request_failed"
    if any(token in text for token in {"zai_api_key_missing", "status=401", "unauthorized"}):
        return "auth_error"
    if "status=429" in text or "rate limit" in text or "quota" in text:
        return "rate_limited"
    if "status=403" in text or "forbidden" in text or "blocked" in text:
        return "provider_blocked"
    if "status=404" in text or "model_not_supported" in text or "model_not_found" in text:
        return "model_not_found"
    if "status=400" in text or "bad request" in text:
        return "bad_request"
    if "timeout" in text:
        return "timeout"
    if any(token in text for token in {"ssl", "unexpected_eof", "transport_error", "connection reset", "winerror 10054"}):
        return "transport_error"
    return "request_failed"


def _zai_availability_status(failure_code: str) -> str:
    code = str(failure_code or "").strip().lower()
    if code == "rate_limited":
        return "limited"
    if code == "auth_error":
        return "needs_setup"
    if code in {"provider_blocked", "model_not_found", "bad_request", "timeout", "transport_error", "request_failed"}:
        return "unavailable"
    return "unknown"


def _normalize_zai_availability_status(row: dict) -> str:
    explicit = str(row.get("availability_status", "") or "").strip().lower()
    if explicit in {"ready", "needs_setup", "unknown", "limited", "unavailable"}:
        return explicit
    status = str(row.get("status", "") or "").strip().lower()
    if status in {"ready", "ok"}:
        return "ready"
    if not status:
        return "unknown"
    return _zai_availability_status(status)


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
            action_id="list_models",
            label="Refresh Models",
            description="Load available models for the dropdown.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_list_models,
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
    payload = dict(settings)
    changed = False

    selected = _normalize_model_id(payload.get("model_id", ""))
    if selected and selected not in _ALLOWED_MODEL_IDS:
        selected = MODELS[0].model_id if MODELS else ""
    if selected and selected != str(payload.get("model_id", "")).strip():
        payload["model_id"] = selected
        changed = True

    existing = payload.get("models")
    normalized = _normalize_models_payload(existing if isinstance(existing, list) else [])
    if not normalized:
        normalized = [
            {
                "model_id": model.model_id,
                "product_name": model.product_name or model.model_id,
                "description": model.description,
                "highlights": model.highlights,
                "context_window": model.context_window,
                "size_hint": f"Free API, {model.context_window // 1000}k context" if model.context_window else "Free API",
                "enabled": idx == 0,
            }
            for idx, model in enumerate(MODELS)
        ]
    else:
        enabled_map: dict[str, bool] = {}
        status_map: dict[str, str] = {}
        if isinstance(existing, list):
            for entry in existing:
                if not isinstance(entry, dict):
                    continue
                mid = _normalize_model_id(entry.get("model_id", ""))
                if not mid:
                    continue
                enabled_map[mid] = bool(entry.get("enabled", False))
                status_map[mid] = str(entry.get("status", "")).strip()
        for idx, entry in enumerate(normalized):
            mid = str(entry.get("model_id", "")).strip()
            entry["enabled"] = enabled_map.get(mid, idx == 0)
            status = status_map.get(mid, "")
            if status:
                entry["status"] = status

    if payload.get("models") != normalized:
        payload["models"] = normalized
        changed = True
    if "disable_thinking" not in payload:
        payload["disable_thinking"] = False
        changed = True

    if changed:
        ctx.set_settings(payload, secret_fields=["api_key"])
