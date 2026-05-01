"""Ollama LLM integration plugin for AI Meeting Manager.

This plugin provides local LLM processing using Ollama server with:
- Server management (check, install, start, stop)
- Model management (list, download, remove, select)
- Summary generation from meeting transcripts
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aimn.plugins.api import (
    ArtifactSchema,
    HookContext,
    build_prompt,
    emit_result,
    get_content,
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

logger = logging.getLogger("aimn.plugins.llm.ollama")


# ============================================================================
# Constants
# ============================================================================

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_API_URL = f"{DEFAULT_OLLAMA_BASE_URL}/api"
DEFAULT_TIMEOUT = 45
DEFAULT_HEALTH_START_TIMEOUT = 12
DEFAULT_PULL_TIMEOUT = 600  # 10 minutes
DEFAULT_CHAT_TIMEOUT = 90

@dataclass(frozen=True)
class OllamaCatalogModel:
    model_id: str
    product_name: str = ""
    context_window: int = 0
    highlights: str = ""
    description: str = ""
    source_url: str = ""
    size_hint: str = ""


def _coerce_catalog_int(value: object) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _ollama_highlights_from_entry(entry: dict[str, Any]) -> str:
    highlights = str(entry.get("highlights", "") or "").strip()
    if highlights:
        return highlights
    suitability = entry.get("suitability")
    if isinstance(suitability, list):
        items = [str(item).strip() for item in suitability if str(item).strip()]
        return ", ".join(items)
    return ""


def _load_passport_models() -> list[dict[str, Any]]:
    try:
        passport_path = Path(__file__).resolve().with_name("plugin_passport.json")
        if not passport_path.exists():
            return []
        payload = json.loads(passport_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _ollama_model_page(model_id: str) -> str:
    mid = str(model_id or "").strip()
    if not mid:
        return ""
    base = mid.split(":", 1)[0].strip() or mid
    return f"https://ollama.com/library/{base}"


def load_models() -> list[OllamaCatalogModel]:
    """Load Ollama catalog models from plugin passport."""
    models: list[OllamaCatalogModel] = []
    source = _load_passport_models()
    for entry in source:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if not model_id:
            continue
        source_url = str(entry.get("source_url", "") or "").strip() or _ollama_model_page(model_id)
        size_hint = str(entry.get("size_hint", "") or entry.get("size", "") or "").strip()
        models.append(
            OllamaCatalogModel(
                model_id=model_id,
                product_name=str(entry.get("product_name", "") or entry.get("name", "") or model_id).strip(),
                context_window=_coerce_catalog_int(entry.get("context_window", 0)),
                highlights=_ollama_highlights_from_entry(entry),
                description=str(entry.get("description", "") or "").strip(),
                source_url=source_url,
                size_hint=size_hint,
            )
        )
    return models


MODELS: list[OllamaCatalogModel] = load_models()

# Windows installation paths
OLLAMA_INSTALLER_URL = "https://ollama.com/download/install.ps1"
OLLAMA_BINARY_NAME = "ollama.exe" if sys.platform == "win32" else "ollama"


def _normalize_model_name(value: str) -> str:
    text = str(value or "").strip().lower()
    if text.endswith(":latest"):
        return text[: -len(":latest")]
    return text


def _ollama_match_keys(value: str) -> set[str]:
    text = str(value or "").strip().lower()
    if not text:
        return set()
    keys = {text}
    normalized = _normalize_model_name(text)
    if normalized:
        keys.add(normalized)
    return {item for item in keys if item}

# ============================================================================
# Server Management
# ============================================================================


@dataclass
class OllamaServerStatus:
    """Status of Ollama server."""

    running: bool
    url: str
    version: str | None = None
    error: str | None = None


class OllamaServerManager:
    """Manages Ollama server lifecycle."""

    def __init__(self, base_url: str = DEFAULT_OLLAMA_BASE_URL):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"

    def check_server(self) -> OllamaServerStatus:
        """Check if Ollama server is running."""
        try:
            response = self._http_request("GET", "/tags", timeout=5)
            if response:
                data = self._read_json_response(response)
                version = data.get("models", [{}])[0].get("details", {}).get("version") if data.get("models") else None
                return OllamaServerStatus(running=True, url=self.base_url, version=version)
        except Exception as exc:
            logger.debug("ollama_server_not_running: %s", exc)
            return OllamaServerStatus(running=False, url=self.base_url, error=str(exc))
        return OllamaServerStatus(running=False, url=self.base_url, error="server_not_running")

    def start_server(self, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
        """Start Ollama server.

        Returns:
            Tuple of (success, message)
        """
        try:
            timeout = int(timeout)
        except Exception:
            timeout = DEFAULT_TIMEOUT
        timeout = max(2, min(timeout, 300))

        # Check if already running
        status = self.check_server()
        if status.running:
            return True, "Ollama server is already running"

        # Try to start via subprocess
        try:
            # On Windows, use the installed binary
            if sys.platform == "win32":
                ollama_path = shutil.which("ollama")
                if ollama_path:
                    # Start server in background
                    process = subprocess.Popen(
                        [ollama_path, "serve"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                    )
                else:
                    return False, "Ollama binary not found in PATH"
            else:
                # On Unix, use the installed binary
                ollama_path = shutil.which("ollama")
                if ollama_path:
                    process = subprocess.Popen(
                        [ollama_path, "serve"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                else:
                    return False, "Ollama binary not found in PATH"

            # Wait for server to start
            logger.info("Starting Ollama server...")
            for _ in range(timeout):
                time.sleep(1)
                poll = process.poll()
                if poll is not None:
                    stdout, stderr = process.communicate()
                    err = (stderr or b"").decode("utf-8", errors="ignore").strip()
                    out = (stdout or b"").decode("utf-8", errors="ignore").strip()
                    detail = err or out or f"exit_code={poll}"
                    return False, f"Ollama server process exited early: {detail[:240]}"
                status = self.check_server()
                if status.running:
                    logger.info("Ollama server started successfully")
                    return True, f"Ollama server started at {self.base_url}"
            return False, f"Ollama server did not start within {timeout} seconds"

        except Exception as exc:
            return False, f"Failed to start Ollama server: {exc}"

    def stop_server(self) -> tuple[bool, str]:
        """Stop Ollama server.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Send shutdown request to API
            response = self._http_request("POST", "/shutdown", timeout=5)
            if response is not None:
                logger.info("Ollama server shutdown request sent")
                return True, "Ollama server shutdown request sent"
            return False, "Server shutdown request failed (server may already be stopped)"
        except Exception as exc:
            logger.warning("Ollama server stop failed: %s", exc)
            return False, f"Failed to stop server: {exc}"

    def _http_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        timeout: int = 10,
    ) -> Any | None:
        """Make HTTP request to Ollama API."""
        import urllib.error
        import urllib.request

        url = f"{self.api_url}{endpoint}"
        body = json.dumps(data).encode("utf-8") if data else None
        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            # Some endpoints return 404 or 200 with empty body
            if e.code in (404, 200):
                return e
            raise
        except Exception as exc:
            logger.debug("ollama_http_request_failed: %s", exc)
            return None

    @staticmethod
    def _read_json_response(response: Any) -> dict:
        if response is None:
            return {}
        raw = b""
        try:
            if isinstance(response, (bytes, bytearray)):
                raw = bytes(response)
            elif hasattr(response, "read"):
                raw = response.read()
            if not raw:
                return {}
            text = raw.decode("utf-8", errors="ignore")
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        finally:
            if hasattr(response, "close"):
                try:
                    response.close()
                except Exception:
                    pass


# ============================================================================
# Model Management
# ============================================================================


@dataclass
class OllamaInstalledModel:
    """Ollama model information."""

    name: str
    size: int | None = None
    digest: str | None = None
    modified_at: str | None = None


class OllamaModelManager:
    """Manages Ollama models."""

    def __init__(self, server_manager: OllamaServerManager):
        self.server_manager = server_manager

    def list_models(self) -> list[OllamaInstalledModel]:
        """List all installed Ollama models."""
        models: list[OllamaInstalledModel] = []
        status = self.server_manager.check_server()

        if not status.running:
            logger.warning("Ollama server is not running, cannot list models")
            return models

        try:
            response = self.server_manager._http_request("GET", "/tags", timeout=10)
            if response:
                data = self.server_manager._read_json_response(response)
                for model_data in data.get("models", []):
                    models.append(
                        OllamaInstalledModel(
                            name=model_data.get("name", ""),
                            size=model_data.get("size"),
                            digest=model_data.get("digest"),
                            modified_at=model_data.get("modified_at"),
                        )
                    )
        except Exception as exc:
            logger.error("Failed to list Ollama models: %s", exc)

        return models

    def pull_model(self, model_name: str, timeout: int = DEFAULT_PULL_TIMEOUT) -> tuple[bool, str]:
        """Pull/download a model from Ollama registry.

        Args:
            model_name: Name of the model to pull (e.g., "llama3.2:8b")
            timeout: Maximum time to wait for pull to complete

        Returns:
            Tuple of (success, message)
        """
        status = self.server_manager.check_server()
        if not status.running:
            return False, "Ollama server is not running"

        try:
            # Start pull process
            if sys.platform == "win32":
                ollama_path = shutil.which("ollama")
                if not ollama_path:
                    return False, "Ollama binary not found in PATH"
                process = subprocess.Popen(
                    [ollama_path, "pull", model_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            else:
                ollama_path = shutil.which("ollama")
                if not ollama_path:
                    return False, "Ollama binary not found in PATH"
                process = subprocess.Popen(
                    [ollama_path, "pull", model_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            # Wait for pull to complete
            logger.info("Pulling Ollama model: %s", model_name)
            for _ in range(timeout):
                time.sleep(1)
                poll_result = process.poll()
                if poll_result is not None:
                    # Process has finished
                    if poll_result == 0:
                        stdout, stderr = process.communicate()
                        if stderr:
                            logger.debug("Pull output: %s", stderr.decode("utf-8", errors="ignore"))
                        return True, f"Model {model_name} pulled successfully"
                    else:
                        stdout, stderr = process.communicate()
                        error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Unknown error"
                        return False, f"Failed to pull {model_name}: {error_msg}"

            # Timeout
            process.kill()
            return False, f"Pull timed out after {timeout} seconds"

        except Exception as exc:
            return False, f"Failed to pull model {model_name}: {exc}"

    def remove_model(self, model_name: str) -> tuple[bool, str]:
        """Remove an installed Ollama model.

        Args:
            model_name: Name of the model to remove

        Returns:
            Tuple of (success, message)
        """
        status = self.server_manager.check_server()
        if not status.running:
            return False, "Ollama server is not running"

        try:
            if sys.platform == "win32":
                ollama_path = shutil.which("ollama")
                if not ollama_path:
                    return False, "Ollama binary not found in PATH"
                process = subprocess.Popen(
                    [ollama_path, "rm", "-f", model_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
            else:
                ollama_path = shutil.which("ollama")
                if not ollama_path:
                    return False, "Ollama binary not found in PATH"
                process = subprocess.Popen(
                    [ollama_path, "rm", "-f", model_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            stdout, stderr = process.communicate(timeout=30)
            if process.returncode == 0:
                return True, f"Model {model_name} removed successfully"
            else:
                error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Unknown error"
                return False, f"Failed to remove {model_name}: {error_msg}"

        except subprocess.TimeoutExpired:
            process.kill()
            return False, f"Remove operation timed out for {model_name}"
        except Exception as exc:
            return False, f"Failed to remove model {model_name}: {exc}"

    def get_model_info(self, model_name: str) -> OllamaInstalledModel | None:
        """Get information about a specific model."""
        target = _normalize_model_name(model_name)
        models = self.list_models()
        for model in models:
            current = _normalize_model_name(model.name)
            if current == target:
                return model
        return None

    def generate(
        self,
        model_name: str,
        prompt: str,
        *,
        max_tokens: int = 50,
        timeout: int = 30,
    ) -> str:
        """Generate a small response to validate model availability."""
        status = self.server_manager.check_server()
        if not status.running:
            return ""
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": int(max_tokens)},
        }
        response = self.server_manager._http_request("POST", "/generate", data=payload, timeout=timeout)
        if not response:
            return ""
        data = self.server_manager._read_json_response(response)
        return str(data.get("response", "")).strip()


# ============================================================================
# Summary Generation
# ============================================================================


class OllamaSummaryGenerator:
    """Generates meeting summaries using Ollama."""

    def __init__(
        self,
        server_manager: OllamaServerManager,
        model_manager: OllamaModelManager,
        model_id: str = "llama3.2",
        system_prompt: str | None = None,
        prompt_profile: str | None = None,
        prompt_custom: str | None = None,
        prompt_language: str | None = None,
        prompt_presets: list[dict] | None = None,
        prompt_max_words: int = 600,
        temperature: float = 0.2,
        max_tokens: int = 900,
        auto_pull_model: bool = False,
        pull_timeout_seconds: int = 120,
        request_timeout_seconds: int = DEFAULT_CHAT_TIMEOUT,
    ):
        self.server_manager = server_manager
        self.model_manager = model_manager
        self.model_id = model_id
        self.system_prompt = system_prompt or self._get_default_system_prompt()
        self.prompt_profile = str(prompt_profile or "").strip()
        self.prompt_custom = str(prompt_custom or "")
        self.prompt_language = str(prompt_language or "").strip()
        self.prompt_presets = prompt_presets or []
        self.prompt_max_words = int(prompt_max_words) if isinstance(prompt_max_words, str) else prompt_max_words
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.auto_pull_model = bool(auto_pull_model)
        try:
            parsed_pull_timeout = int(pull_timeout_seconds)
        except Exception:
            parsed_pull_timeout = 120
        try:
            parsed_request_timeout = int(request_timeout_seconds)
        except Exception:
            parsed_request_timeout = DEFAULT_CHAT_TIMEOUT
        self.pull_timeout_seconds = max(10, min(parsed_pull_timeout, 1800))
        self.request_timeout_seconds = max(10, min(parsed_request_timeout, 600))

    def _get_default_system_prompt(self) -> str:
        """Get default system prompt for meeting summaries."""
        return """You are a helpful AI assistant that creates concise meeting summaries.

Analyze the meeting transcript and create a structured summary with:
1. Key topics discussed
2. Action items and decisions made
3. Important points and takeaways

Format the response in markdown."""

    def generate_summary(self, transcript: str, ctx: HookContext) -> tuple[str, list[str]]:
        """Generate a summary from meeting transcript.

        Args:
            transcript: The meeting transcript text
            ctx: HookContext for progress reporting

        Returns:
            Tuple of (summary_text, warnings)
        """
        warnings: list[str] = []
        system_prompt = self._resolve_prompt(transcript)
        user_text = transcript if not system_prompt else "Summarize according to the system instructions."

        # Check server status
        status = self.server_manager.check_server()
        if not status.running:
            # Try to start server
            success, message = self.server_manager.start_server()
            if not success:
                warnings.append(f"Ollama server not running: {message}")
                return "# Summary\n\n(Ollama server not available)", warnings

        # Some Ollama servers can proxy cloud/server-side models that are not
        # listed in /tags. For pipeline/UI consistency we only run models that
        # are actually visible in the local Ollama catalog on this host.
        model_info = self.model_manager.get_model_info(self.model_id)
        if not model_info:
            if self.auto_pull_model:
                # Optional auto-pull is disabled by default to avoid long pipeline stalls.
                logger.info("Model %s not found, attempting to pull", self.model_id)
                success, message = self.model_manager.pull_model(
                    self.model_id,
                    timeout=self.pull_timeout_seconds,
                )
                if not success:
                    warnings.append(f"Model {self.model_id} not available: {message}")
                    return f"# Summary\n\n(Model {self.model_id} not available)", warnings
            else:
                warnings.append(f"Model {self.model_id} is not listed in Ollama tags.")
                return f"# Summary\n\n(Model {self.model_id} not available)", warnings

        # Generate summary using Ollama API
        try:
            payload = {
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": system_prompt or self.system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            }

            import urllib.error
            import urllib.request

            url = f"{self.server_manager.api_url}/chat"
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}

            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=self.request_timeout_seconds) as response:
                data = response.read().decode("utf-8")
                response_data = json.loads(data)

                message = response_data.get("message")
                if isinstance(message, dict):
                    content = str(message.get("content", "")).strip()
                    if content:
                        logger.info("Ollama summary generated successfully")
                        return content, warnings
                content = str(response_data.get("response", "")).strip()
                if content:
                    logger.info("Ollama summary generated successfully")
                    return content, warnings

                warnings.append("Ollama returned unexpected response format")
                return "# Summary\n\n(Ollama response format error)", warnings

        except urllib.error.HTTPError as e:
            error_msg = e.read().decode("utf-8", errors="ignore") if e.fp else "Unknown error"
            lowered = error_msg.lower()
            if e.code in {400, 404} and ("model" in lowered or "not found" in lowered or "unknown" in lowered):
                warnings.append(f"Model {self.model_id} not available in Ollama: {error_msg}")
                logger.error("Ollama model not available: %s", error_msg)
                return f"# Summary\n\n(Model {self.model_id} not available)", warnings
            warnings.append(f"Ollama API error: {error_msg}")
            logger.error("Ollama API error: %s", error_msg)
            return "# Summary\n\n(Ollama API error)", warnings
        except Exception as exc:
            warnings.append(f"Failed to generate summary: {exc}")
            logger.error("Failed to generate summary: %s", exc)
            return "# Summary\n\n(Ollama error)", warnings

    def _resolve_prompt(self, transcript: str) -> str:
        presets = normalize_presets(self.prompt_presets) if self.prompt_presets else load_prompt_presets()
        main_prompt = resolve_prompt(self.prompt_profile, presets, self.prompt_custom).strip()
        if not main_prompt:
            main_prompt = str(self.system_prompt or "").strip()
        if not main_prompt:
            return ""
        return build_prompt(
            transcript=transcript,
            main_prompt=main_prompt,
            language_override=self.prompt_language,
            max_words=self.prompt_max_words,
        )


# ============================================================================
# Plugin Classes
# ============================================================================


class OllamaPlugin:
    """Main plugin class for Ollama integration."""

    def __init__(
        self,
        # Server settings
        ollama_url: str = DEFAULT_OLLAMA_BASE_URL,
        auto_start_server: bool = True,
        auto_stop_server: bool = False,
        # Model settings
        model_id: str = "llama3.2",
        # Generation settings
        system_prompt: str | None = None,
        prompt_profile: str | None = None,
        prompt_custom: str | None = None,
        prompt_language: str | None = None,
        prompt_presets: list[dict] | None = None,
        prompt_max_words: int = 600,
        temperature: float = 0.2,
        max_tokens: int = 900,
        auto_pull_model: bool = False,
        pull_timeout_seconds: int = 120,
        request_timeout_seconds: int = DEFAULT_CHAT_TIMEOUT,
    ):
        self.server_manager = OllamaServerManager(base_url=ollama_url)
        self.model_manager = OllamaModelManager(self.server_manager)
        self.generator = OllamaSummaryGenerator(
            self.server_manager,
            self.model_manager,
            model_id=model_id,
            system_prompt=system_prompt,
            prompt_profile=prompt_profile,
            prompt_custom=prompt_custom,
            prompt_language=prompt_language,
            prompt_presets=prompt_presets,
            prompt_max_words=prompt_max_words,
            temperature=temperature,
            max_tokens=max_tokens,
            auto_pull_model=auto_pull_model,
            pull_timeout_seconds=pull_timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )
        self.auto_start_server = auto_start_server
        self.auto_stop_server = auto_stop_server

    def run(self, ctx: HookContext) -> PluginResult:
        """Execute the plugin to generate a summary."""
        warnings: list[str] = []

        # Auto-start server if configured
        if self.auto_start_server:
            status = self.server_manager.check_server()
            if not status.running:
                logger.info("Auto-starting Ollama server")
                success, message = self.server_manager.start_server()
                if not success:
                    warnings.append(f"Failed to start Ollama server: {message}")
                    return self._create_error_result(warnings)

        # Get transcript text
        transcript = (ctx.input_text or "").strip()
        if not transcript:
            warnings.append("No transcript text provided")
            return self._create_error_result(warnings)

        # Generate summary
        summary, gen_warnings = self.generator.generate_summary(transcript, ctx)
        warnings.extend(gen_warnings)

        # Auto-stop server if configured
        if self.auto_stop_server:
            self.server_manager.stop_server()

        outputs = [
            PluginOutput(kind=KIND_SUMMARY, content=summary, content_type="text/markdown")
        ]

        return PluginResult(outputs=outputs, warnings=warnings)

    def _create_error_result(self, warnings: list[str]) -> PluginResult:
        """Create an error result."""
        return PluginResult(
            outputs=[PluginOutput(kind=KIND_SUMMARY, content="# Summary\n\n(Error occurred)", content_type="text/markdown")],
            warnings=warnings,
        )


# ============================================================================
# Plugin Registration
# ============================================================================


class Plugin:
    """Plugin registration class."""

    def register(self, ctx) -> None:
        """Register plugin hooks and schemas."""
        ctx.register_artifact_kind(KIND_SUMMARY, ArtifactSchema(content_type="text/markdown", user_visible=True))
        ctx.register_hook_handler("derive.after_postprocess", hook_generate_summary, mode="optional", priority=100)
        ctx.register_settings_schema(settings_schema)
        ctx.register_actions(action_descriptors)
        _ensure_default_settings(ctx)


def hook_generate_summary(ctx: HookContext) -> PluginResult:
    """Hook handler for summary generation."""
    params = _filtered_params(ctx.plugin_config or {})
    plugin = OllamaPlugin(**params) if params else OllamaPlugin()
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


def _filtered_params(params: dict) -> dict:
    """Filter and map plugin parameters."""
    allowed = {
        # Server settings
        "ollama_url",
        "auto_start_server",
        "auto_stop_server",
        # Model settings
        "model_id",
        # Generation settings
        "system_prompt",
        "prompt_profile",
        "prompt_custom",
        "prompt_language",
        "prompt_presets",
        "prompt_max_words",
        "temperature",
        "max_tokens",
        "auto_pull_model",
        "pull_timeout_seconds",
        "request_timeout_seconds",
    }
    filtered: dict = {}
    for key, value in params.items():
        if key in allowed:
            filtered[key] = value
    return filtered


# ============================================================================
# Settings Schema
# ============================================================================


def settings_schema() -> dict:
    """Return the plugin settings schema."""
    return {
        "schema_version": 2,
        "title": "Ollama LLM Integration",
        "description": "Manage Ollama models.",
        "layout": {
            "type": "tabs",
            "tabs": [
                {"id": "models", "title": "Models"},
            ],
        },
        "views": [
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


def _get_default_system_prompt() -> str:
    """Get default system prompt."""
    return """You are a helpful AI assistant that creates concise meeting summaries.

Analyze the meeting transcript and create a structured summary with:
1. Key topics discussed
2. Action items and decisions made
3. Important points and takeaways

Format the response in markdown."""


# ============================================================================
# Actions
# ============================================================================


def action_descriptors() -> list[ActionDescriptor]:
    """Return available plugin actions."""
    return [
        ActionDescriptor(
            action_id="check_server",
            label="Check Server",
            description="Check whether the Ollama server is running.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_check_server,
        ),
        ActionDescriptor(
            action_id="start_server",
            label="Start Server",
            description="Start the Ollama server (if not running).",
            params_schema={"fields": [{"id": "timeout_seconds", "type": "int", "required": False}]},
            dangerous=False,
            handler=action_start_server,
        ),
        ActionDescriptor(
            action_id="stop_server",
            label="Stop Server",
            description="Stop the Ollama server.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_stop_server,
        ),
        ActionDescriptor(
            action_id="test_connection",
            label="Test Connection",
            description="Verify the Ollama endpoint is reachable.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_test_connection,
        ),
        ActionDescriptor(
            action_id="list_models",
            label="Refresh Models",
            description="Load installed Ollama models.",
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
        ActionDescriptor(
            action_id="refine_prompt",
            label="Refine Prompt",
            description="Refine a user prompt with the current LLM model.",
            params_schema={
                "fields": [
                    {"id": "prompt_text", "type": "string", "required": True},
                    {"id": "objective", "type": "string", "required": False},
                    {"id": "model_id", "type": "string", "required": False},
                ]
            },
            dangerous=False,
            handler=action_refine_prompt,
        ),
        ActionDescriptor(
            action_id="pull_model",
            label="Pull Model",
            description="Download an Ollama model.",
            params_schema={"fields": [{"id": "model_id", "type": "string", "required": True}]},
            dangerous=False,
            handler=action_pull_model,
        ),
        ActionDescriptor(
            action_id="remove_model",
            label="Remove Model",
            description="Remove an installed Ollama model.",
            params_schema={"fields": [{"id": "model_id", "type": "string", "required": True}]},
            dangerous=True,
            handler=action_remove_model,
        ),
    ]


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


def _to_int(value: object, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return max(min_value, min(parsed, max_value))


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


def _build_model_rows(installed_models: list[OllamaInstalledModel]) -> list[dict]:
    rows: list[dict] = []
    catalog_by_key: dict[str, OllamaCatalogModel] = {}
    for model in MODELS:
        model_id = str(getattr(model, "model_id", "") or "").strip()
        if not model_id:
            continue
        for key in _ollama_match_keys(model_id):
            catalog_by_key.setdefault(key, model)
    for model in installed_models or []:
        model_id = str(getattr(model, "name", "") or "").strip()
        if not model_id:
            continue
        catalog_meta = None
        for key in _ollama_match_keys(model_id):
            catalog_meta = catalog_by_key.get(key)
            if catalog_meta is not None:
                break
        rows.append(
            {
                "model_id": model_id,
                "product_name": str(getattr(catalog_meta, "product_name", "") or model_id),
                "enabled": False,
                "installed": True,
                "status": "installed",
                "availability_status": "ready",
                "description": str(getattr(catalog_meta, "description", "") or "").strip(),
                "source_url": str(getattr(catalog_meta, "source_url", "") or _ollama_model_page(model_id)).strip(),
                "highlights": str(getattr(catalog_meta, "highlights", "") or "").strip(),
                "context_window": int(getattr(catalog_meta, "context_window", 0) or 0),
                "size_hint": str(getattr(catalog_meta, "size_hint", "") or "").strip(),
                "installed_model_id": model_id,
            }
        )
    return rows


def _ensure_server_running(
    server_manager: OllamaServerManager,
    *,
    auto_start: bool,
    timeout_seconds: int,
) -> tuple[bool, OllamaServerStatus | None, str]:
    status = server_manager.check_server()
    if status and bool(getattr(status, "running", False)):
        return True, status, ""
    if not auto_start:
        err = str(getattr(status, "error", "") or "server_not_running")
        return False, status, err
    ok, message = server_manager.start_server(timeout=timeout_seconds)
    status = server_manager.check_server()
    if ok and status and bool(getattr(status, "running", False)):
        return True, status, message
    err = str(getattr(status, "error", "") or message or "server_not_running")
    return False, status, err


def action_test_connection(settings: dict, params: dict) -> ActionResult:
    """Test Ollama server connection."""
    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    timeout = _to_int(params.get("timeout_seconds", DEFAULT_HEALTH_START_TIMEOUT), default=12, min_value=2, max_value=120)
    auto_start = _to_bool(settings.get("auto_start_server"), default=True)
    running, status, error = _ensure_server_running(
        server_manager,
        auto_start=auto_start,
        timeout_seconds=timeout,
    )

    if running:
        return ActionResult(
            status="success",
            message="connection_ok",
            data={
                "url": ollama_url,
                "version": str(getattr(status, "version", "") or ""),
                "auto_start": auto_start,
            },
        )
    return ActionResult(
        status="error",
        message="connection_failed",
        data={"url": ollama_url, "error": error or "server_not_running", "auto_start": auto_start},
    )


def action_check_server(settings: dict, params: dict) -> ActionResult:
    """Check if Ollama server is running."""
    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    status = server_manager.check_server()

    if status and status.running:
        return ActionResult(
            status="success",
            message="server_running",
            data={"url": ollama_url, "version": status.version or ""},
        )
    return ActionResult(
        status="error",
        message="server_not_running",
        data={"url": ollama_url, "error": status.error or ""},
    )


def action_start_server(settings: dict, params: dict) -> ActionResult:
    """Start the Ollama server."""
    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    raw_timeout = params.get("timeout_seconds", DEFAULT_HEALTH_START_TIMEOUT)
    try:
        timeout = int(raw_timeout)
    except Exception:
        timeout = DEFAULT_HEALTH_START_TIMEOUT
    timeout = max(2, min(timeout, 120))
    server_manager = OllamaServerManager(base_url=ollama_url)
    success, message = server_manager.start_server(timeout=timeout)
    return ActionResult(
        status="success" if success else "error",
        message=message,
        data={"timeout_seconds": timeout},
    )


def action_stop_server(settings: dict, params: dict) -> ActionResult:
    """Stop the Ollama server."""
    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    success, message = server_manager.stop_server()

    return ActionResult(status="success" if success else "error", message=message)


def action_list_models(settings: dict, params: dict) -> ActionResult:
    """List catalog models and mark installed ones."""
    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    model_manager = OllamaModelManager(server_manager)
    ollama_installed = bool(shutil.which("ollama"))
    timeout = _to_int(params.get("timeout_seconds", DEFAULT_HEALTH_START_TIMEOUT), default=12, min_value=2, max_value=120)
    auto_start = _to_bool(settings.get("auto_start_server"), default=True)
    running, status, error = _ensure_server_running(
        server_manager,
        auto_start=auto_start,
        timeout_seconds=timeout,
    )

    installed_models: list[OllamaInstalledModel] = []
    if running:
        try:
            installed_models = model_manager.list_models()
        except Exception as exc:
            error = str(exc)
            running = False

    model_list = _build_model_rows(installed_models)
    previous_rows = settings.get("models") if isinstance(settings.get("models"), list) else []
    previous_by_key: dict[str, dict] = {}
    for entry in previous_rows:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id", "") or "").strip()
        if not model_id:
            continue
        for key in _ollama_match_keys(model_id):
            previous_by_key.setdefault(key, entry)
    for row in model_list:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("model_id", "") or "").strip()
        previous = None
        for key in _ollama_match_keys(model_id):
            previous = previous_by_key.get(key)
            if previous is not None:
                break
        if previous is None:
            continue
        enabled = previous.get("enabled")
        if isinstance(enabled, bool):
            row["enabled"] = enabled
    payload = {
        "url": ollama_url,
        "ollama_installed": ollama_installed,
        "server_running": bool(running),
        "error": error if not running else "",
        "options": [{"label": m["product_name"], "value": m["model_id"]} for m in model_list],
        "models": model_list,
        "total": len(model_list),
    }
    if status:
        payload["version"] = str(getattr(status, "version", "") or "")
    if not running:
        return ActionResult(status="error", message="server_not_running", data=payload)
    return ActionResult(
        status="success",
        message="models_loaded",
        data=payload,
    )


def action_test_model(settings: dict, params: dict) -> ActionResult:
    """Test a single Ollama model."""
    model_id = str(params.get("model_id", "")).strip()
    if not model_id:
        return ActionResult(status="error", message="model_id_missing")

    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    model_manager = OllamaModelManager(server_manager)
    timeout = _to_int(params.get("timeout_seconds", DEFAULT_HEALTH_START_TIMEOUT), default=12, min_value=2, max_value=120)
    auto_start = _to_bool(settings.get("auto_start_server"), default=True)

    running, _status, error = _ensure_server_running(
        server_manager,
        auto_start=auto_start,
        timeout_seconds=timeout,
    )
    if not running:
        return ActionResult(status="error", message=error or "server_not_running", data={"model_id": model_id})

    try:
        # Try to generate a simple response
        test_prompt = "Say 'OK' in 5 words."
        result = model_manager.generate(
            model_name=model_id,
            prompt=test_prompt,
            max_tokens=50,
        )

        if result:
            return ActionResult(status="success", message="model_ok", data={"model_id": model_id})
        return ActionResult(
            status="success",
            message="model_available_no_output",
            data={"model_id": model_id},
            warnings=["model_response_empty"],
        )
    except Exception as exc:
        return ActionResult(status="error", message=str(exc), data={"model_id": model_id})


def action_refine_prompt(settings: dict, params: dict) -> ActionResult:
    prompt_text = str(params.get("prompt_text", "")).strip()
    if not prompt_text:
        return ActionResult(status="error", message="prompt_text_missing")
    objective = str(params.get("objective", "")).strip()
    model_id = str(params.get("model_id", settings.get("model_id", "llama3.2"))).strip() or "llama3.2"

    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    model_manager = OllamaModelManager(server_manager)
    timeout = _to_int(
        params.get("timeout_seconds", DEFAULT_HEALTH_START_TIMEOUT),
        default=12,
        min_value=2,
        max_value=120,
    )
    auto_start = _to_bool(settings.get("auto_start_server"), default=True)

    running, _status, error = _ensure_server_running(
        server_manager,
        auto_start=auto_start,
        timeout_seconds=timeout,
    )
    if not running:
        return ActionResult(status="error", message=error or "server_not_running", data={"model_id": model_id})

    try:
        models = model_manager.list_models()
        if not any(m.name == model_id for m in models):
            return ActionResult(status="error", message="model_not_found", data={"model_id": model_id})

        max_tokens = _to_int(settings.get("max_tokens", 900), default=900, min_value=16, max_value=4096)
        request_text = (
            f"{_prompt_refiner_system_prompt()}\n\n"
            f"{_prompt_refiner_user_text(prompt_text, objective)}"
        )
        content = model_manager.generate(
            model_name=model_id,
            prompt=request_text,
            max_tokens=max_tokens,
        )
        refined = _sanitize_refined_prompt(content)
        if not refined:
            return ActionResult(status="error", message="refined_prompt_empty", data={"model_id": model_id})
        return ActionResult(
            status="success",
            message="prompt_refined",
            data={"prompt": refined, "model_id": model_id},
        )
    except Exception as exc:
        return ActionResult(status="error", message=str(exc), data={"model_id": model_id})


def action_pull_model(settings: dict, params: dict) -> ActionResult:
    """Download an Ollama model."""
    model_id = str(params.get("model_id", "")).strip()
    if not model_id:
        return ActionResult(status="error", message="model_id_missing")

    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    model_manager = OllamaModelManager(server_manager)
    timeout = _to_int(params.get("timeout_seconds", DEFAULT_HEALTH_START_TIMEOUT), default=12, min_value=2, max_value=120)
    auto_start = _to_bool(settings.get("auto_start_server"), default=True)
    running, _status, error = _ensure_server_running(
        server_manager,
        auto_start=auto_start,
        timeout_seconds=timeout,
    )
    if not running:
        return ActionResult(status="error", message=error or "server_not_running", data={"model_id": model_id})

    success, message = model_manager.pull_model(model_id)

    if success:
        return ActionResult(status="success", message="model_pulled", data={"model_id": model_id})
    return ActionResult(status="error", message=message, data={"model_id": model_id})


def action_remove_model(settings: dict, params: dict) -> ActionResult:
    """Remove an installed Ollama model."""
    model_id = str(params.get("model_id", "")).strip()
    if not model_id:
        return ActionResult(status="error", message="model_id_missing")

    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    server_manager = OllamaServerManager(base_url=ollama_url)
    model_manager = OllamaModelManager(server_manager)
    timeout = _to_int(params.get("timeout_seconds", DEFAULT_HEALTH_START_TIMEOUT), default=12, min_value=2, max_value=120)
    auto_start = _to_bool(settings.get("auto_start_server"), default=True)
    running, _status, error = _ensure_server_running(
        server_manager,
        auto_start=auto_start,
        timeout_seconds=timeout,
    )
    if not running:
        return ActionResult(status="error", message=error or "server_not_running", data={"model_id": model_id})

    success, message = model_manager.remove_model(model_id)

    if success:
        return ActionResult(status="success", message="model_removed", data={"model_id": model_id})
    return ActionResult(status="error", message=message, data={"model_id": model_id})


def action_generate_summary(settings: dict, params: dict) -> dict:
    """Generate a meeting summary using Ollama."""
    ollama_url = str(settings.get("ollama_url", DEFAULT_OLLAMA_BASE_URL))
    model_id = str(settings.get("model_id", MODELS[0].model_id if MODELS else "llama3.2"))

    # Get transcript from context
    # Note: This action is designed to be called from the UI, so it needs access to the current meeting's transcript
    # For now, we'll return a placeholder response
    return {
        "status": "info",
        "message": "Summary generation requires a meeting transcript. Use the plugin hook instead.",
        "data": {
            "model_id": model_id,
            "ollama_url": ollama_url,
        },
    }


# ============================================================================
# Default Settings
# ============================================================================


def _ensure_default_settings(ctx) -> None:
    """Ensure default plugin settings are present."""
    settings = ctx.get_settings()

    # Check if we need to set defaults
    if settings.get("ollama_url") and settings.get("models"):
        return

    defaults = {
        "ollama_url": DEFAULT_OLLAMA_BASE_URL,
        "auto_start_server": True,
        "auto_stop_server": False,
        "model_id": MODELS[0].model_id if MODELS else "llama3.2",
        "temperature": 0.2,
        "max_tokens": 900,
        "auto_pull_model": False,
        "pull_timeout_seconds": 120,
        "request_timeout_seconds": DEFAULT_CHAT_TIMEOUT,
        "system_prompt": _get_default_system_prompt(),
    }

    # Initialize models catalog if not present.
    if not settings.get("models"):
        defaults["models"] = [
            {
                "model_id": model.model_id,
                "product_name": model.product_name or model.model_id,
                # Default to disabled so Meetings drawer (installed-only) doesn't show catalog items as "installed".
                "enabled": False,
            }
            for model in MODELS
        ]

    payload = dict(settings)
    payload.update(defaults)
    ctx.set_settings(payload, secret_fields=[])
