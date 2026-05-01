from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

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
class DeepSeekModel:
    model_id: str
    product_name: str
    context_window: int
    highlights: str
    description: str


def load_models() -> list[DeepSeekModel]:
    models: list[DeepSeekModel] = []
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
            DeepSeekModel(
                model_id=model_id,
                product_name=str(entry.get("product_name", "") or entry.get("name", "")).strip(),
                context_window=int(entry.get("context_window", 0) or 0),
                highlights=str(entry.get("highlights", "")).strip(),
                description=str(entry.get("description", "")).strip(),
            )
        )
    return models


MODELS: list[DeepSeekModel] = load_models()


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
        model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if not model_id:
            continue
        out[model_id] = dict(entry)
    return out


_PASSPORT_MODEL_META = _passport_models_meta()


class DeepSeekPlugin:
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
        endpoint: str = "https://api.deepseek.com/v1/chat/completions",
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = api_key
        if system_prompt is None:
            system_prompt = default_summary_system_prompt()
        self.system_prompt = system_prompt
        self.model_id = model_id
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
            return self._mock_result(warnings + ["deepseek_key_missing"])

        system_prompt = self._resolve_prompt(text)
        user_text = text if not system_prompt else "Summarize according to the system instructions."
        content, error = self._call_deepseek(api_key, model_id, user_text, system_prompt)
        if error:
            warnings.append(error)
            return self._mock_result(warnings + ["deepseek_request_failed"])
        if not content:
            warnings.append("deepseek_empty_response")
            return self._mock_result(warnings)

        outputs = [PluginOutput(kind=KIND_SUMMARY, content=content, content_type="text/markdown")]
        return PluginResult(outputs=outputs, warnings=warnings)

    def _resolve_model_id(self) -> str:
        if self.model_id:
            return self.model_id.strip()
        return self._default_model_id()

    @staticmethod
    def _default_model_id() -> str:
        return MODELS[0].model_id if MODELS else "deepseek-chat"

    def _resolve_api_key(self) -> tuple[str | None, str]:
        key = (
            self.api_key
            or os.getenv("AIMN_DEEPSEEK_API_KEY", "")
            or os.getenv("AIMN_DEEPSEEK_USER_KEY", "")
            or os.getenv("AIMN_DEEPSEEK_PAID_KEY", "")
        ).strip()
        return (key if key else None, "ok" if key else "api_key_missing")

    def _call_deepseek(
        self, api_key: str, model_id: str, text: str, system_prompt: str | None
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
        }
        logger = logging.getLogger("aimn.network.deepseek")
        logger.info("deepseek_request model=%s endpoint=%s timeout=%s", model_id, self.endpoint, self.timeout_seconds)
        request = urllib.request.Request(self.endpoint, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            detail = self._describe_http_error(exc, model_id)
            logger.warning("deepseek_request_failed model=%s error=%s", model_id, detail)
            return "", detail
        try:
            content = data["choices"][0]["message"]["content"]
            logger.info("deepseek_request_ok model=%s", model_id)
            return content, ""
        except Exception:
            logger.warning("deepseek_parse_error model=%s", model_id)
            return "", "deepseek_parse_error"

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
        parts = [f"deepseek_http_error(model={model_id})"]
        if status:
            parts.append(f"status={status}")
        if body:
            parts.append(f"body={body}")
        if message and message not in parts:
            parts.append(message)
        return " ".join(parts)

    @staticmethod
    def _mock_result(warnings: list[str]) -> PluginResult:
        title, reason, detail, fix_steps = DeepSeekPlugin._fallback_diagnostics(warnings)
        lines = [
            f"# {title}",
            "",
            "This is a fallback summary because the DeepSeek request could not be completed.",
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
        detail = DeepSeekPlugin._first_detail_warning(items)

        if any(item in {"api_key_missing", "deepseek_key_missing"} for item in items):
            return (
                "DeepSeek is not configured",
                "API key is missing.",
                detail,
                ["Add API key in Settings -> LLM -> DeepSeek.", "Re-run the stage."],
            )

        status = DeepSeekPlugin._extract_http_status(items)
        if status == 429:
            return (
                "DeepSeek rate limit",
                "API returned HTTP 429 (Too Many Requests).",
                detail,
                ["Retry later.", "Switch to another provider/model for this run."],
            )
        if status == 404:
            return (
                "DeepSeek request failed",
                "HTTP 404 from API (endpoint or model id is invalid).",
                detail,
                ["Verify endpoint URL.", "Verify model_id.", "Re-run the stage."],
            )
        if status == 400:
            return (
                "DeepSeek bad request",
                "HTTP 400: request payload was rejected by API.",
                detail,
                ["Check model_id and prompt configuration.", "Re-run plugin health test in Settings."],
            )
        if status in {401, 403}:
            return (
                "DeepSeek authorization failed",
                f"HTTP {status}: access denied.",
                detail,
                ["Check API key validity and permissions.", "Re-run the stage."],
            )
        if any(item == "deepseek_empty_response" for item in items):
            return (
                "DeepSeek returned empty response",
                "The request completed but no usable content was returned.",
                detail,
                ["Retry the stage.", "Switch model/provider for this run."],
            )
        return (
            "DeepSeek request failed",
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
    def _first_detail_warning(warnings: list[str]) -> str:
        skip = {
            "mock_fallback",
            "deepseek_request_failed",
            "deepseek_empty_response",
            "empty_input_text",
            "api_key_missing",
            "deepseek_key_missing",
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
    plugin = DeepSeekPlugin(**params) if params else DeepSeekPlugin()
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


def _plugin_from_settings(settings: dict) -> DeepSeekPlugin:
    api_key = str(
        settings.get("api_key", "")
        or settings.get("user_api_key", "")
        or settings.get("paid_api_key", "")
    ).strip() or None
    endpoint = str(settings.get("endpoint", "")).strip() or "https://api.deepseek.com/v1/chat/completions"
    model_id = str(settings.get("model_id", "")).strip() or None
    return DeepSeekPlugin(
        api_key=api_key,
        model_id=model_id,
        endpoint=endpoint,
    )


def action_test_connection(settings: dict, params: dict) -> ActionResult:
    plugin = _plugin_from_settings(settings)
    api_key, status = plugin._resolve_api_key()
    if status != "ok":
        return ActionResult(
            status="error",
            message=status,
            data={"availability_status": "needs_setup", "failure_code": "auth_error"},
        )
    model_id = plugin._resolve_model_id()
    content, error = plugin._call_deepseek(api_key, model_id, "ping", "")
    if error:
        failure_code = _deepseek_failure_code(error)
        return ActionResult(
            status="error",
            message=error,
            data={
                "model_id": model_id,
                "availability_status": _deepseek_availability_status(failure_code),
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
        model_id = str(entry.get("model_id", "")).strip()
        if model_id:
            cached[model_id] = dict(entry)
    options = [
        {"label": model.product_name or model.model_id, "value": model.model_id}
        for model in MODELS
    ]
    models = []
    for model in MODELS:
        row = cached.get(model.model_id, {})
        passport_meta = _PASSPORT_MODEL_META.get(model.model_id, {})
        context_window = int(model.context_window or 0)
        size_hint = "Cloud API"
        if context_window > 0:
            size_hint = f"Cloud API, {context_window // 1000}k context"
        models.append(
            {
                "model_id": model.model_id,
                "product_name": model.product_name or model.model_id,
                "source_url": str(
                    passport_meta.get("source_url", "")
                    or "https://api.deepseek.com"
                ).strip(),
                "enabled": row.get("enabled", False),
                "status": str(row.get("status", "") or ""),
                "availability_status": _normalize_deepseek_availability_status(row),
                "description": model.description,
                "highlights": model.highlights,
                "context_window": context_window,
                "size_hint": size_hint,
            }
        )
    return ActionResult(status="success", message="models_loaded", data={"options": options, "models": models})


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
    content, error = plugin._call_deepseek(
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
            data={"model_id": model_id, "availability_status": "needs_setup", "failure_code": "auth_error"},
        )
    content, error = plugin._call_deepseek(api_key, model_id, "ping", "")
    if error:
        failure_code = _deepseek_failure_code(error)
        return ActionResult(
            status="error",
            message=error,
            data={
                "model_id": model_id,
                "availability_status": _deepseek_availability_status(failure_code),
                "failure_code": failure_code,
            },
        )
    return ActionResult(status="success", message="model_ok", data={"model_id": model_id, "availability_status": "ready"})


def _deepseek_failure_code(message: str) -> str:
    text = str(message or "").strip().lower()
    if not text:
        return "request_failed"
    if any(token in text for token in {"api_key_missing", "auth_error", "status=401", "status=402", "unauthorized"}):
        return "auth_error"
    if "status=429" in text or "rate limit" in text:
        return "rate_limited"
    if "status=403" in text or "forbidden" in text or "blocked" in text:
        return "provider_blocked"
    if "status=404" in text or "model_not_found" in text:
        return "model_not_found"
    if "status=400" in text or "bad_request" in text:
        return "bad_request"
    if "timeout" in text:
        return "timeout"
    if any(token in text for token in {"ssl", "unexpected_eof", "transport_error", "connection reset", "winerror 10054"}):
        return "transport_error"
    return "request_failed"


def _deepseek_availability_status(failure_code: str) -> str:
    code = str(failure_code or "").strip().lower()
    if code == "rate_limited":
        return "limited"
    if code == "auth_error":
        return "needs_setup"
    if code in {"provider_blocked", "model_not_found", "bad_request", "timeout", "transport_error", "request_failed"}:
        return "unavailable"
    return "unknown"


def _normalize_deepseek_availability_status(row: dict) -> str:
    explicit = str(row.get("availability_status", "") or "").strip().lower()
    if explicit in {"ready", "needs_setup", "unknown", "limited", "unavailable"}:
        return explicit
    status = str(row.get("status", "") or "").strip().lower()
    if status in {"ready", "ok"}:
        return "ready"
    if not status:
        return "unknown"
    return _deepseek_availability_status(status)


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
    if settings.get("models"):
        return
    defaults = [
        {
            "model_id": model.model_id,
            "product_name": model.product_name or model.model_id,
            "description": model.description,
            "highlights": model.highlights,
            "context_window": model.context_window,
            "size_hint": f"Cloud API, {model.context_window // 1000}k context" if model.context_window else "Cloud API",
            "enabled": idx == 0,
        }
        for idx, model in enumerate(MODELS)
    ]
    if defaults:
        payload = dict(settings)
        payload["models"] = defaults
        ctx.set_settings(payload, secret_fields=["api_key"])
