from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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

_BROKEN_BINARIES_LOCK = threading.Lock()
_BROKEN_BINARIES: dict[str, str] = {}

_BROKEN_BINARIES_CACHE_VERSION = 1
_RUNTIME_CONTEXT_START = "[APPROVED_CONTEXT_START]"
_RUNTIME_CONTEXT_END = "[APPROVED_CONTEXT_END]"
_RUNTIME_TRANSCRIPT_START = "[MEETING_TRANSCRIPT_START]"
_RUNTIME_TRANSCRIPT_END = "[MEETING_TRANSCRIPT_END]"
_HF_TOKEN_ENV_KEYS = ("AIMN_HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HF_TOKEN")
_DEFAULT_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class _CommandRunResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False


def _subprocess_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _windows_returncode_hex(code: int | None) -> str:
    if code is None:
        return ""
    try:
        value = int(code)
    except Exception:
        return ""
    if value < 0:
        value = (value + (1 << 32)) & 0xFFFFFFFF
    return f"0x{value:08X}"


def _windows_dll_diagnostics() -> dict[str, object]:
    if os.name != "nt":
        return {"platform": "non_windows"}
    try:
        import ctypes
    except Exception:
        return {"platform": "windows", "error": "ctypes_unavailable"}

    missing: list[str] = []
    # Common MSVC + Vulkan loader deps for ggml-based binaries on Windows.
    candidates = [
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "concrt140.dll",
        "vulkan-1.dll",
    ]
    for dll in candidates:
        try:
            ctypes.WinDLL(dll)
        except OSError:
            missing.append(dll)
        except Exception:
            missing.append(dll)
    return {"platform": "windows", "missing": missing}


def _broken_binaries_cache_ttl_seconds() -> int:
    raw = os.getenv("AIMN_LLAMA_CLI_BROKEN_CACHE_TTL_SECONDS", "").strip()
    if not raw:
        return 10 * 60
    try:
        value = int(raw)
    except Exception:
        return 10 * 60
    return max(0, value)


def _ignore_broken_binaries_cache() -> bool:
    return os.getenv("AIMN_LLAMA_CLI_IGNORE_BROKEN_CACHE", "").strip().lower() in {"1", "true", "yes", "on"}


def _broken_cache_file(cache_dir: str) -> Path:
    base = Path(cache_dir) if cache_dir else _resolve_repo_root() / "models" / "llama"
    return base / ".aimn_llama_cli_broken_binaries.json"


def _forget_broken_binary(binary_path: str, cache_dir: str) -> None:
    if not binary_path:
        return
    with _BROKEN_BINARIES_LOCK:
        _BROKEN_BINARIES.pop(binary_path, None)
    if _ignore_broken_binaries_cache():
        return
    path = _broken_cache_file(cache_dir)
    existing = _load_broken_binaries_from_disk(cache_dir)
    if binary_path not in existing:
        return
    existing.pop(binary_path, None)
    if not existing:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            return
        return
    payload = {
        "version": _BROKEN_BINARIES_CACHE_VERSION,
        "binaries": dict(existing),
    }
    try:
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=True))
    except Exception:
        return


def _load_broken_binaries_from_disk(cache_dir: str) -> dict[str, dict]:
    if _ignore_broken_binaries_cache():
        return {}
    path = _broken_cache_file(cache_dir)
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    if not isinstance(data, dict) or int(data.get("version", 0) or 0) != _BROKEN_BINARIES_CACHE_VERSION:
        return {}
    binaries = data.get("binaries")
    return binaries if isinstance(binaries, dict) else {}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _remember_broken_binary_on_disk(binary_path: str, reason: str, cache_dir: str) -> None:
    if _ignore_broken_binaries_cache():
        return
    if not binary_path or not reason:
        return
    path = _broken_cache_file(cache_dir)
    existing = _load_broken_binaries_from_disk(cache_dir)
    try:
        mtime = int(Path(binary_path).stat().st_mtime)
    except Exception:
        mtime = 0
    payload = {
        "version": _BROKEN_BINARIES_CACHE_VERSION,
        "binaries": dict(existing),
    }
    payload["binaries"][binary_path] = {
        "reason": str(reason),
        "ts": int(time.time()),
        "mtime": mtime,
    }
    try:
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=True))
    except Exception:
        return


def _broken_binary_reason(binary_path: str, cache_dir: str) -> str:
    if not binary_path:
        return ""
    with _BROKEN_BINARIES_LOCK:
        cached = str(_BROKEN_BINARIES.get(binary_path, "") or "")
    if cached:
        return cached
    if _ignore_broken_binaries_cache():
        return ""
    ttl = _broken_binaries_cache_ttl_seconds()
    if ttl <= 0:
        return ""
    binaries = _load_broken_binaries_from_disk(cache_dir)
    entry = binaries.get(binary_path) if isinstance(binaries, dict) else None
    if not isinstance(entry, dict):
        return ""
    reason = str(entry.get("reason", "") or "")
    if not reason:
        return ""
    if reason.startswith("llama_cli_missing_dll_dependencies"):
        diag = _windows_dll_diagnostics()
        missing = diag.get("missing") if isinstance(diag, dict) else None
        if not isinstance(missing, list) or not missing:
            _forget_broken_binary(binary_path, cache_dir)
            return ""
    try:
        ts = int(entry.get("ts", 0) or 0)
    except Exception:
        ts = 0
    if not ts or (int(time.time()) - ts) > ttl:
        return ""
    try:
        cached_mtime = int(entry.get("mtime", 0) or 0)
    except Exception:
        cached_mtime = 0
    if cached_mtime:
        try:
            current_mtime = int(Path(binary_path).stat().st_mtime)
        except Exception:
            current_mtime = 0
        if current_mtime and current_mtime != cached_mtime:
            return ""
    with _BROKEN_BINARIES_LOCK:
        _BROKEN_BINARIES[binary_path] = reason
    return reason


def _remember_broken_binary(binary_path: str, reason: str, cache_dir: str) -> None:
    if not binary_path or not reason:
        return
    with _BROKEN_BINARIES_LOCK:
        _BROKEN_BINARIES[binary_path] = str(reason)
    _remember_broken_binary_on_disk(binary_path, reason, cache_dir)


def _terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=1)
        return
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=1)
    except Exception:
        pass


def _run_command_with_cancel(
    cmd: list[str],
    *,
    timeout_seconds: int,
    env: dict[str, str],
    cancel_requested=None,
) -> _CommandRunResult:
    if not callable(cancel_requested):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_seconds,
            env=env,
            creationflags=_subprocess_creationflags(),
        )
        return _CommandRunResult(
            returncode=getattr(result, "returncode", None),
            stdout=str(getattr(result, "stdout", "") or ""),
            stderr=str(getattr(result, "stderr", "") or ""),
        )
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        env=env,
        creationflags=_subprocess_creationflags(),
    )
    try:
        timeout_value = float(timeout_seconds)
    except Exception:
        timeout_value = 0.0
    deadline = time.monotonic() + max(1.0, timeout_value)

    while True:
        if callable(cancel_requested) and cancel_requested():
            _terminate_process(process)
            try:
                stdout, stderr = process.communicate(timeout=1)
            except Exception:
                stdout, stderr = "", ""
            return _CommandRunResult(
                returncode=process.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                cancelled=True,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process(process)
            try:
                stdout, stderr = process.communicate(timeout=1)
            except Exception:
                stdout, stderr = "", ""
            return _CommandRunResult(
                returncode=process.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                timed_out=True,
            )
        try:
            stdout, stderr = process.communicate(timeout=min(0.2, remaining))
            return _CommandRunResult(
                returncode=process.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
            )
        except subprocess.TimeoutExpired:
            continue


def _maybe_pick_local_gguf_from_cache(cache_dir: str, model_id: str, model_quant: str) -> str:
    if not cache_dir:
        return ""
    root = Path(cache_dir)
    if not root.exists():
        return ""
    files = [p for p in root.glob("*.gguf") if p.is_file()]
    if not files:
        return ""

    model_tail = (model_id or "").strip().split("/")[-1]
    query = _normalize_model_match_key(model_tail)
    tokens = _model_match_tokens(model_tail)
    candidates: list[tuple[int, Path]] = []
    for candidate in files:
        candidate_key = _normalize_model_match_key(candidate.stem)
        if not candidate_key:
            continue
        score = 0
        if query and candidate_key == query:
            score += 1000
        elif query and query in candidate_key:
            score += len(query) * 10
        score += sum(len(token) for token in tokens if token in candidate_key)
        if score > 0:
            candidates.append((score, candidate))

    if candidates:
        best_score = max(score for score, _candidate in candidates)
        best_candidates = [candidate for score, candidate in candidates if score == best_score]
        if len(best_candidates) == 1:
            return str(best_candidates[0])
        files = best_candidates
    elif len(files) == 1:
        return str(files[0])

    # Only use quant as a tie-breaker after narrowing candidates by model identity.
    quant_token = (model_quant or "").strip().lower().replace("-", "_")
    if quant_token:
        quant_files = [p for p in files if quant_token in p.name.lower().replace("-", "_")]
        if len(quant_files) == 1:
            return str(quant_files[0])
        if quant_files:
            files = quant_files

    if len(files) == 1:
        return str(files[0])
    return ""


def _normalize_model_match_key(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    normalized = re.sub(r"(?<=\d)\.(?=\d)", "_", raw)
    normalized = re.sub(r"(?i)\bgguf\b", "", normalized)
    normalized = normalized.replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _model_match_tokens(value: str) -> list[str]:
    normalized = _normalize_model_match_key(value)
    if not normalized:
        return []
    seen: set[str] = set()
    tokens: list[str] = []
    parts = [part for part in normalized.split("_") if part]
    for part in parts:
        if len(part) >= 3 or any(ch.isdigit() for ch in part):
            if part not in seen:
                seen.add(part)
                tokens.append(part)
    if len(parts) >= 2:
        joined = "_".join(parts)
        if joined and joined not in seen:
            seen.add(joined)
            tokens.append(joined)
        collapsed = "".join(parts)
        if collapsed and collapsed not in seen and any(ch.isdigit() for ch in collapsed):
            seen.add(collapsed)
            tokens.append(collapsed)
    return tokens


def _resolve_repo_root() -> Path:
    raw = str(os.environ.get("AIMN_HOME", "") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[3]

def _resolve_path(path_value: str, env_key: str | None = None) -> str:
    env_value = os.getenv(env_key or "", "").strip() if env_key else ""
    raw = env_value or path_value
    if not raw:
        return ""
    path = Path(raw)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(_resolve_repo_root() / path)
        candidates.append(path)
    if path.suffix == ".exe":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(""))
    if path.suffix == "" and os.name == "nt":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(".exe"))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    system = shutil.which(str(raw))
    if system:
        return system
    return ""


def _resolve_dir(path_value: str, env_key: str | None = None) -> str:
    env_value = os.getenv(env_key or "", "").strip() if env_key else ""
    raw = env_value or path_value
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute():
        path = _resolve_repo_root() / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _resolved_cache_root(cache_dir: str) -> Path:
    root = Path(_resolve_dir(cache_dir, "AIMN_LLAMA_CACHE_DIR"))
    try:
        return root.resolve()
    except Exception:
        return root


def _model_id_looks_like_local_path(model_id: str) -> bool:
    raw = str(model_id or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if lowered.endswith(".gguf"):
        return True
    return any(token in raw for token in ("\\", "/", ":"))


def _resolve_local_model_candidate_from_model_id(cache_dir: str, model_id: str) -> str:
    raw = str(model_id or "").strip()
    if not raw or not _model_id_looks_like_local_path(raw):
        return ""
    resolved = _resolve_path(raw)
    if resolved:
        return resolved
    cache_root = _resolved_cache_root(cache_dir)
    candidate = cache_root / Path(raw).name
    if candidate.exists() and candidate.is_file():
        return str(candidate)
    return ""


def _validate_local_gguf_file(path_value: str) -> list[str]:
    path = Path(str(path_value or "").strip())
    if not path:
        return ["llama_cli_model_missing"]
    if not path.exists() or not path.is_file():
        return ["llama_cli_model_missing"]
    try:
        size = int(path.stat().st_size)
    except Exception:
        size = 0
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except Exception as exc:
        return [f"llama_cli_model_file_unreadable({exc})"]
    if size <= 0:
        return ["llama_cli_model_file_empty"]
    if head.startswith(b"GGUF"):
        return []
    lowered = head.lower()
    if lowered.startswith((b"<!do", b"<html", b"<?xm")):
        return [f"llama_cli_model_file_invalid_magic_html({path.name})"]
    if size < 1024:
        return [f"llama_cli_model_file_too_small(bytes={size})"]
    return [f"llama_cli_model_file_invalid_magic({head[:4].hex()})"]


def _is_valid_hf_repo_id(model_id: str) -> bool:
    raw = str(model_id or "").strip()
    if not raw:
        return False
    if _model_id_looks_like_local_path(raw):
        return False
    head = raw.split(":", 1)[0].strip()
    if head.count("/") != 1:
        return False
    owner, name = [item.strip() for item in head.split("/", 1)]
    return bool(owner and name)


def _resolve_model_execution_spec(
    *,
    model_path: str,
    model_id: str,
    model_quant: str,
    cache_dir: str,
    allow_download: bool,
) -> tuple[str, bool, list[str]]:
    warnings: list[str] = []
    resolved_model_path = _resolve_path(model_path)
    if resolved_model_path:
        return resolved_model_path, False, warnings
    wanted_model_id = str(model_id or "").strip()
    wanted_quant = str(model_quant or "").strip()
    if not wanted_model_id:
        return "", False, ["llama_cli_model_missing"]
    local_candidate = _resolve_local_model_candidate_from_model_id(cache_dir, wanted_model_id)
    if local_candidate:
        return local_candidate, False, warnings
    local = _maybe_pick_local_gguf_from_cache(cache_dir, wanted_model_id, wanted_quant)
    if local:
        return local, False, warnings
    if not allow_download:
        return "", False, ["llama_cli_download_disabled"]
    if not _is_valid_hf_repo_id(wanted_model_id):
        return "", False, ["llama_cli_invalid_hf_repo_format"]
    model_spec = wanted_model_id
    if wanted_quant:
        model_spec = f"{model_spec}:{wanted_quant}"
    warnings.append("llama_cli_download_attempted")
    return model_spec, True, warnings


def _builtin_model_rows() -> list[dict]:
    try:
        passport_path = Path(__file__).resolve().with_name("plugin_passport.json")
        if passport_path.exists():
            payload = json.loads(passport_path.read_text(encoding="utf-8"))
            models = payload.get("models") if isinstance(payload, dict) else None
            if isinstance(models, list):
                return [dict(entry) for entry in models if isinstance(entry, dict)]
    except Exception:
        pass
    return []


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class LlamaCliPlugin:
    def __init__(
        self,
        binary_path: str = "bin/llama/llama-cli",
        model_path: str = "",
        model_id: str = "",
        model_quant: str = "Q4_K_M",
        allow_download: bool = False,
        cache_dir: str = "models/llama",
        hf_token: str = "",
        system_prompt: str | None = None,
        prompt_profile: str | None = None,
        prompt_custom: str | None = None,
        prompt_language: str | None = None,
        prompt_presets: list[dict] | None = None,
        prompt_max_words: int = 600,
        max_tokens: int = 900,
        temperature: float = 0.2,
        ctx_size: int = 32768,
        gpu_layers: int = -1,
        vulkan_visible_devices: str = "",
        use_chunking: bool = False,
        disable_thinking: bool = False,
        extra_args: str = "",
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.binary_path = binary_path
        self.model_path = model_path
        self.model_id = model_id
        self.model_quant = model_quant
        self.allow_download = _coerce_bool(allow_download)
        self.cache_dir = cache_dir
        self.hf_token = str(hf_token or "").strip()
        if system_prompt is None:
            system_prompt = default_summary_system_prompt()
        self.system_prompt = system_prompt
        self.prompt_profile = (prompt_profile or "").strip()
        self.prompt_custom = prompt_custom or ""
        self.prompt_language = (prompt_language or "").strip()
        self.prompt_presets = prompt_presets or []
        self.prompt_max_words = int(prompt_max_words) if isinstance(prompt_max_words, str) else prompt_max_words
        # Legacy fields are accepted for backward compatibility but no longer limit generation or trigger chunking.
        self.max_tokens = -1
        self.temperature = float(temperature) if isinstance(temperature, str) else temperature
        self.ctx_size = int(ctx_size) if isinstance(ctx_size, str) else ctx_size
        self.gpu_layers = int(gpu_layers) if isinstance(gpu_layers, str) else gpu_layers
        self.vulkan_visible_devices = str(vulkan_visible_devices or "").strip()
        self.use_chunking = False
        self.disable_thinking = _coerce_bool(disable_thinking)
        self.extra_args = extra_args
        self.timeout_seconds = int(timeout_seconds) if isinstance(timeout_seconds, str) else timeout_seconds

    def run(self, ctx: HookContext) -> PluginResult:
        warnings: list[str] = []
        text = (ctx.input_text or "").strip()
        if not text:
            warnings.append("empty_input_text")
            text = "No transcript text provided."
        cancel_requested = getattr(ctx, "cancel_requested", None)
        if callable(cancel_requested) and cancel_requested():
            raise RuntimeError("cancelled_by_user")

        binary_path = _resolve_path(self.binary_path, "AIMN_LLAMA_CLI_PATH")
        if not binary_path:
            warnings.append("llama_cli_missing")
            return self._mock_result(warnings)

        cache_dir = _resolve_dir(self.cache_dir, "AIMN_LLAMA_CACHE_DIR")
        cached_reason = _broken_binary_reason(binary_path, cache_dir)
        if cached_reason:
            warnings.append(cached_reason)
            return self._mock_result(warnings)

        model_spec, use_hf_repo, resolve_warnings = _resolve_model_execution_spec(
            model_path=self.model_path,
            model_id=self.model_id,
            model_quant=self.model_quant,
            cache_dir=cache_dir,
            allow_download=self.allow_download,
        )
        warnings.extend(resolve_warnings)
        if not model_spec:
            return self._mock_result(warnings)
        if not use_hf_repo:
            model_file_warnings = _validate_local_gguf_file(model_spec)
            if model_file_warnings:
                warnings.extend(model_file_warnings)
                return self._mock_result(warnings)

        prompt_text = self._resolve_prompt(text)
        if prompt_text:
            system_prompt = prompt_text
            user_text = self._prepare_user_prompt(
                "Summarize according to the system instructions.",
                model_spec=model_spec,
            )
        else:
            system_prompt = self.system_prompt
            user_text = self._prepare_user_prompt(text, model_spec=model_spec)
        return self._run_cli_prompt(
            binary_path=binary_path,
            cache_dir=cache_dir,
            model_spec=model_spec,
            use_hf_repo=use_hf_repo,
            system_prompt=system_prompt,
            user_text=user_text,
            warnings=warnings,
            cancel_requested=cancel_requested,
        )

    def _run_cli_prompt(
        self,
        *,
        binary_path: str,
        cache_dir: str,
        model_spec: str,
        use_hf_repo: bool,
        system_prompt: str | None,
        user_text: str,
        warnings: list[str],
        cancel_requested,
    ) -> PluginResult:
        cmd = [
            binary_path,
            "--no-display-prompt",
            "--simple-io",
            "--single-turn",
            "-n",
            "-1",
            "--temp",
            str(self.temperature),
        ]
        if self.ctx_size:
            cmd.extend(["-c", str(self.ctx_size)])
        if self.gpu_layers is not None:
            cmd.extend(["-ngl", str(self.gpu_layers)])
        if use_hf_repo:
            cmd.extend(["--hf-repo", model_spec])
        else:
            cmd.extend(["-m", model_spec])
        override_tokenizer_pre = self._effective_tokenizer_pre_override(model_spec)
        tokenizer_override_arg = ""
        if override_tokenizer_pre:
            warnings.append(f"llama_cli_tokenizer_pre_override({override_tokenizer_pre})")
            tokenizer_override_arg = f"tokenizer.ggml.pre=str:{override_tokenizer_pre}"
            cmd.extend(["--override-kv", tokenizer_override_arg])
        prompt_args, temp_prompt_files = self._prompt_transport_args(system_prompt, user_text)
        cmd.extend(prompt_args)
        if self.extra_args:
            cmd.extend(shlex.split(self.extra_args, posix=False))

        env = os.environ.copy()
        if cache_dir:
            env["LLAMA_CACHE"] = cache_dir
            env["LLAMA_CACHE_DIR"] = cache_dir
        if self.hf_token:
            env["HUGGINGFACE_HUB_TOKEN"] = self.hf_token
            env["HF_TOKEN"] = self.hf_token
            env["AIMN_HF_TOKEN"] = self.hf_token
        visible_devices = (
            str(os.getenv("AIMN_LLAMA_VISIBLE_DEVICES", "") or "").strip()
            or self.vulkan_visible_devices
        )
        if visible_devices:
            env["GGML_VK_VISIBLE_DEVICES"] = visible_devices

        logger = logging.getLogger("aimn.local.llama_cli")
        logger.info(
            "llama_cli_start model=%s launch_mode=%s model_arg=%s",
            model_spec,
            "hf_repo" if use_hf_repo else "local_file",
            model_spec,
        )
        try:
            try:
                result = _run_command_with_cancel(
                    cmd,
                    timeout_seconds=self.timeout_seconds,
                    env=env,
                    cancel_requested=cancel_requested,
                )
            except OSError as exc:
                logger.error(
                    "llama_cli_oserror model=%s winerror=%s error=%s",
                    model_spec,
                    getattr(exc, "winerror", None),
                    exc,
                )
                winerror = getattr(exc, "winerror", None)
                if os.name == "nt" and winerror:
                    warnings.append(f"llama_cli_oserror(winerror={winerror})")
                    diag = _windows_dll_diagnostics()
                    missing = diag.get("missing") if isinstance(diag, dict) else None
                    if isinstance(missing, list) and missing:
                        warnings.append("llama_cli_missing_dll=" + ",".join([str(x) for x in missing[:8]]))
                else:
                    warnings.append(f"llama_cli_error({exc})")
                return self._mock_result(warnings)
            except Exception as exc:
                logger.error("llama_cli_error model=%s error=%s", model_spec, exc)
                warnings.append(f"llama_cli_error({exc})")
                return self._mock_result(warnings)

            if getattr(result, "cancelled", False):
                logger.info("llama_cli_cancelled model=%s", model_spec)
                raise RuntimeError("cancelled_by_user")
            if getattr(result, "timed_out", False):
                logger.warning("llama_cli_timeout model=%s", model_spec)
                warnings.append("llama_cli_timeout")
                return self._mock_result(warnings)

            output = (result.stdout or "").strip()
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                if tokenizer_override_arg and self._should_retry_without_tokenizer_override(stderr):
                    retry_result = self._run_without_tokenizer_override(
                        cmd=cmd,
                        tokenizer_override_arg=tokenizer_override_arg,
                        timeout_seconds=self.timeout_seconds,
                        env=env,
                        cancel_requested=cancel_requested,
                    )
                    if getattr(retry_result, "cancelled", False):
                        logger.info("llama_cli_cancelled_retry_without_override model=%s", model_spec)
                        raise RuntimeError("cancelled_by_user")
                    if (
                        not getattr(retry_result, "timed_out", False)
                        and retry_result.returncode == 0
                        and (retry_result.stdout or "").strip()
                    ):
                        warnings.append("llama_cli_tokenizer_pre_override_disabled_after_failure")
                        logger.info("llama_cli_retry_without_tokenizer_override_ok model=%s", model_spec)
                        return self._build_result_from_output((retry_result.stdout or "").strip(), warnings)
                    warnings.append("llama_cli_retry_without_tokenizer_override_failed")
                    if getattr(retry_result, "timed_out", False):
                        warnings.append("llama_cli_retry_without_tokenizer_override_timed_out")
                    retry_stderr = str(getattr(retry_result, "stderr", "") or "").strip()
                    if retry_stderr:
                        warnings.extend(self._summarize_stderr(retry_stderr))
                logger.warning("llama_cli_failed model=%s code=%s", model_spec, result.returncode)
                warnings.append(f"llama_cli_failed(code={result.returncode})")
                if os.name == "nt":
                    try:
                        code = int(result.returncode)
                    except Exception:
                        code = None
                    hex_code = _windows_returncode_hex(code)
                    if hex_code:
                        warnings.append(f"llama_cli_failed_hex={hex_code}")
                    # 0xC0000135 == STATUS_DLL_NOT_FOUND (common when VC++ runtime is missing).
                    if code in {3221225781, -1073741515}:
                        diag = _windows_dll_diagnostics()
                        missing = diag.get("missing") if isinstance(diag, dict) else None
                        missing_hint = ""
                        if isinstance(missing, list) and missing:
                            missing_hint = ":" + ",".join([str(x) for x in missing[:8]])
                        reason = f"llama_cli_missing_dll_dependencies({hex_code or '0xC0000135'}{missing_hint})"
                        if isinstance(missing, list) and missing:
                            _remember_broken_binary(binary_path, reason, cache_dir)
                        warnings.append(reason)
                    # 0xC000007B == STATUS_INVALID_IMAGE_FORMAT (wrong arch / bad dependency).
                    if code in {3221225595, -1073741701}:
                        reason = f"llama_cli_bad_image_or_arch({hex_code or '0xC000007B'})"
                        _remember_broken_binary(binary_path, reason, cache_dir)
                        warnings.append(reason)

                if stderr:
                    warnings.extend(self._summarize_stderr(stderr))

                return self._mock_result(warnings)

            if not output:
                logger.warning("llama_cli_empty_response model=%s", model_spec)
                warnings.append("llama_cli_empty_response")
                return self._mock_result(warnings)

            logger.info("llama_cli_ok model=%s", model_spec)
            return self._build_result_from_output(output, warnings)
        finally:
            self._cleanup_temp_prompt_files(temp_prompt_files)

    def _run_chunked_summary(
        self,
        *,
        binary_path: str,
        cache_dir: str,
        model_spec: str,
        use_hf_repo: bool,
        chunk_inputs: list[str],
        warnings: list[str],
    ) -> PluginResult:
        main_prompt = self._resolved_main_prompt()
        if not main_prompt:
            return self._mock_result(list(warnings) + ["llama_cli_prompt_missing"])

        partial_summaries: list[str] = []
        merged_warnings = list(warnings)
        total_chunks = len(chunk_inputs)
        for index, chunk_input in enumerate(chunk_inputs, start=1):
            chunk_system_prompt = self._build_chunk_prompt(
                chunk_input,
                main_prompt=main_prompt,
                chunk_index=index,
                total_chunks=total_chunks,
            )
            chunk_user_text = self._prepare_user_prompt(
                "Summarize according to the system instructions.",
                model_spec=model_spec,
            )
            chunk_result = self._run_cli_prompt(
                binary_path=binary_path,
                cache_dir=cache_dir,
                model_spec=model_spec,
                use_hf_repo=use_hf_repo,
                system_prompt=chunk_system_prompt,
                user_text=chunk_user_text,
                warnings=list(merged_warnings) + [f"llama_cli_chunk_pass({index}/{total_chunks})"],
            )
            merged_warnings = self._merge_warning_lists(merged_warnings, chunk_result.warnings)
            if self._is_mock_result(chunk_result):
                merged_warnings.append(f"llama_cli_chunk_failed({index}/{total_chunks})")
                return self._mock_result(self._merge_warning_lists([], merged_warnings))
            chunk_text = self._first_summary_content(chunk_result)
            if not chunk_text:
                merged_warnings.append(f"llama_cli_chunk_empty({index}/{total_chunks})")
                return self._mock_result(self._merge_warning_lists([], merged_warnings))
            partial_summaries.append(
                f"## Chunk {index}/{total_chunks}\n{chunk_text.strip()}"
            )

        merge_runtime_input = "\n\n".join(partial_summaries).strip()
        merge_system_prompt = self._build_merge_prompt(merge_runtime_input, main_prompt=main_prompt)
        merge_user_text = self._prepare_user_prompt(
            "Summarize according to the system instructions.",
            model_spec=model_spec,
        )
        return self._run_cli_prompt(
            binary_path=binary_path,
            cache_dir=cache_dir,
            model_spec=model_spec,
            use_hf_repo=use_hf_repo,
            system_prompt=merge_system_prompt,
            user_text=merge_user_text,
            warnings=self._merge_warning_lists(merged_warnings, [f"llama_cli_chunk_merge({total_chunks})"]),
        )

    def _build_result_from_output(self, output: str, warnings: list[str]) -> PluginResult:
        sanitized, sanitize_warnings = self._sanitize_summary_output(output)
        merged_warnings = list(warnings) + sanitize_warnings
        if not sanitized:
            if "llama_cli_empty_response" not in merged_warnings:
                merged_warnings.append("llama_cli_empty_response")
            return self._mock_result(merged_warnings)
        if self._looks_corrupted_unicode(sanitized):
            merged_warnings.append("llama_cli_output_corrupted")
            return self._mock_result(merged_warnings)
        if self._looks_incomplete_summary(sanitized):
            merged_warnings.append("llama_cli_incomplete_summary")
            return self._mock_result(merged_warnings)
        outputs = [PluginOutput(kind=KIND_SUMMARY, content=sanitized, content_type="text/markdown")]
        return PluginResult(outputs=outputs, warnings=merged_warnings)

    def _prompt_transport_args(self, system_prompt: str | None, user_prompt: str) -> tuple[list[str], list[str]]:
        system_value = str(system_prompt or "").strip()
        user_value = str(user_prompt or "").strip()
        if os.name != "nt":
            args: list[str] = []
            if system_value:
                args.extend(["-sys", system_value])
            args.extend(["-p", user_value])
            return args, []

        args = []
        temp_paths: list[str] = []
        if system_value:
            sys_path = self._write_temp_prompt_file(system_value, prefix="aimn_llama_sys_")
            temp_paths.append(sys_path)
            args.extend(["-sysf", sys_path])
        prompt_path = self._write_temp_prompt_file(user_value, prefix="aimn_llama_prompt_")
        temp_paths.append(prompt_path)
        args.extend(["-f", prompt_path])
        return args, temp_paths

    @staticmethod
    def _write_temp_prompt_file(content: str, *, prefix: str) -> str:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".txt")
        os.close(fd)
        Path(path).write_text(str(content or ""), encoding="utf-8")
        return path

    @staticmethod
    def _cleanup_temp_prompt_files(paths: list[str]) -> None:
        for item in paths or []:
            try:
                Path(item).unlink(missing_ok=True)
            except Exception:
                continue

    def _effective_tokenizer_pre_override(self, model_spec: str) -> str:
        return ""

    @staticmethod
    def _should_retry_without_tokenizer_override(stderr: str) -> bool:
        lowered = str(stderr or "").lower()
        if not lowered:
            return False
        if "unable to load model" in lowered:
            return True
        if "tokenizer.ggml.pre" in lowered:
            return True
        if "tokenizer" in lowered and any(token in lowered for token in ("override", "failed", "error", "invalid")):
            return True
        return False

    @staticmethod
    def _remove_override_arg(cmd: list[str], override_arg: str) -> list[str]:
        cleaned: list[str] = []
        skip_next = False
        for index, item in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if item == "--override-kv" and index + 1 < len(cmd) and cmd[index + 1] == override_arg:
                skip_next = True
                continue
            cleaned.append(item)
        return cleaned

    def _run_without_tokenizer_override(
        self,
        *,
        cmd: list[str],
        tokenizer_override_arg: str,
        timeout_seconds: int,
        env: dict[str, str],
        cancel_requested,
    ) -> _CommandRunResult:
        retry_cmd = self._remove_override_arg(cmd, tokenizer_override_arg)
        return _run_command_with_cancel(
            retry_cmd,
            timeout_seconds=timeout_seconds,
            env=env,
            cancel_requested=cancel_requested,
        )

    @staticmethod
    def _replace_cli_arg(cmd: list[str], arg_name: str, arg_value: str) -> list[str]:
        updated: list[str] = []
        skip_next = False
        replaced = False
        for index, item in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if item == arg_name and index + 1 < len(cmd):
                updated.extend([arg_name, arg_value])
                skip_next = True
                replaced = True
                continue
            updated.append(item)
        if not replaced:
            updated.extend([arg_name, arg_value])
        return updated

    @staticmethod
    def _mock_result(warnings: list[str]) -> PluginResult:
        text = LlamaCliPlugin._fallback_summary_text(warnings)
        outputs = [PluginOutput(kind=KIND_SUMMARY, content=text, content_type="text/markdown")]
        if "mock_fallback" not in warnings:
            warnings = list(warnings) + ["mock_fallback"]
        return PluginResult(outputs=outputs, warnings=warnings)

    @staticmethod
    def _fallback_summary_text(warnings: list[str]) -> str:
        prompt_too_long = any(
            str(item or "").strip() in {"llama_cli_prompt_too_long", "llama_cli_context_overflow"}
            for item in (warnings or [])
        )
        if prompt_too_long:
            return (
                "# Llama.cpp (CLI): prompt exceeds context\n\n"
                "This is a fallback summary because the prompt did not fit into the model context window.\n\n"
                "To fix:\n"
                "- Increase `ctx_size` if your model build supports it\n"
                "- Use a model/build with a larger native context window\n"
                "- Use a shorter prompt profile (`essential`) or disable prompt profile\n"
                "- Re-run the stage"
            )
        reason = LlamaCliPlugin._fallback_reason(warnings)
        return (
            "# Llama.cpp (CLI) is not ready\n\n"
            "This is a fallback summary because the local `llama-cli` provider could not run.\n\n"
            f"Reason: {reason}\n\n"
            "To fix:\n"
            "- Configure `binary_path` to a working `llama-cli` executable\n"
            "- Configure `model_path` or `model_id` + `model_quant`, and ensure the GGUF is present in `cache_dir`\n"
            "- Then re-run the stage"
        )

    @staticmethod
    def _fallback_reason(warnings: list[str]) -> str:
        entries = [str(item).strip() for item in (warnings or []) if str(item).strip()]
        if not entries:
            return "unknown runtime error"
        for marker, message in (
            ("llama_cli_missing", "llama-cli binary path is invalid or binary is missing"),
            ("llama_cli_model_missing", "model path/model id is not configured"),
            ("llama_cli_model_file_empty", "selected local GGUF file is empty"),
            ("llama_cli_invalid_hf_repo_format", "model_id is not a valid Hugging Face repo id; use user/model or set model_path to a local GGUF file"),
            ("llama_cli_download_disabled", "model is not present locally and auto-download is disabled"),
            ("llama_cli_timeout", "llama-cli timed out"),
            ("llama_cli_empty_response", "llama-cli returned empty response"),
            ("llama_cli_output_corrupted", "llama-cli returned corrupted text output"),
            ("llama_cli_model_load_failed", "llama-cli could not load the selected model"),
            ("llama_cli_tokenizer_override_invalid", "model rejected tokenizer override; verify model build or use another GGUF"),
        ):
            if marker in entries:
                return message
        for item in entries:
            if item.startswith("llama_cli_model_file_invalid_magic_html"):
                return "selected GGUF file is HTML or an error page instead of a model file"
            if item.startswith("llama_cli_model_file_invalid_magic"):
                return "selected local file is not a valid GGUF model"
            if item.startswith("llama_cli_model_file_too_small"):
                return "selected local GGUF file is too small to be a real model"
            if item.startswith("llama_cli_model_file_unreadable"):
                return "selected local GGUF file could not be read"
            if item.startswith("llama_cli_missing_dll_dependencies"):
                return "missing runtime DLL dependencies for llama-cli"
            if item.startswith("llama_cli_failed("):
                return "llama-cli process failed during model startup or prompt execution"
            if item.startswith("llama_cli_error("):
                return item
            if item.startswith("llama_cli_oserror("):
                return item
            if item.startswith("llama_cli_stderr_tail="):
                return item.replace("llama_cli_stderr_tail=", "")[:180]
        return entries[0][:180]

    @staticmethod
    def _sanitize_summary_output(text: str) -> tuple[str, list[str]]:
        value = str(text or "").strip()
        if not value:
            return "", []
        warnings: list[str] = []

        think_re = re.compile(r"(?is)<think>.*?</think>\s*")
        if think_re.search(value):
            value = think_re.sub("", value).strip()
            warnings.append("llama_cli_reasoning_stripped")

        value = re.sub(r"(?im)\s*\[end of text\]\s*$", "", value).strip()

        stripped = LlamaCliPlugin._strip_reasoning_preamble(value)
        if stripped != value:
            value = stripped
            if "llama_cli_reasoning_stripped" not in warnings:
                warnings.append("llama_cli_reasoning_stripped")

        value = LlamaCliPlugin._unwrap_markdown_fence(value)
        return value.strip(), warnings

    @staticmethod
    def _looks_corrupted_unicode(text: str) -> bool:
        value = str(text or "")
        if not value:
            return False
        replacement_count = value.count("\ufffd")
        if replacement_count <= 0:
            return False
        compact = "".join(ch for ch in value if not ch.isspace())
        if not compact:
            return replacement_count > 0
        ratio = replacement_count / max(1, len(compact))
        return replacement_count >= 8 or ratio >= 0.02

    @staticmethod
    def _looks_incomplete_summary(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return True
        lowered = value.lower()
        if "<think>" in lowered and "</think>" not in lowered:
            return True
        if lowered.startswith("<think>"):
            return True
        compact = "".join(ch for ch in value if not ch.isspace())
        heading_count = sum(1 for line in value.splitlines() if line.strip().startswith("#"))
        if heading_count and len(compact) < 25:
            return True
        if heading_count == 1 and len(compact) < 35:
            return True
        return False

    @staticmethod
    def _unwrap_markdown_fence(text: str) -> str:
        value = str(text or "").strip()
        if not (value.startswith("```") and value.endswith("```")):
            return value
        lines = value.splitlines()
        if len(lines) < 2:
            return value
        return "\n".join(lines[1:-1]).strip()

    @staticmethod
    def _strip_reasoning_preamble(text: str) -> str:
        value = str(text or "").strip()
        if not value or not LlamaCliPlugin._looks_like_reasoning_trace(value):
            return value

        heading_match = re.search(
            r"(?im)^(#{1,3}\s*(meeting topic|тема встречи|tasks|задачи|project names|проекты|key decisions|решения|brief meeting summary|краткое резюме|short discussion flow|логика обсуждения))",
            value,
        )
        if heading_match and heading_match.start() > 0:
            return value[heading_match.start():].strip()

        lines = value.splitlines()
        drop_until = 0
        for idx, line in enumerate(lines):
            if re.match(
                r"(?im)^\s*(#{1,3}\s*(meeting topic|тема встречи|tasks|задачи|project names|проекты|key decisions|решения|brief meeting summary|краткое резюме|short discussion flow|логика обсуждения))",
                line,
            ):
                drop_until = idx
                break
        if drop_until > 0:
            return "\n".join(lines[drop_until:]).strip()
        return value

    @staticmethod
    def _looks_like_reasoning_trace(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        markers = (
            "okay, let's tackle this",
            "analyze the request",
            "analyze the transcript",
            "drafting the summary",
            "chain-of-thought",
        )
        return any(marker in lowered for marker in markers)

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

    def _resolved_main_prompt(self) -> str:
        presets = normalize_presets(self.prompt_presets) or load_prompt_presets()
        main_prompt = resolve_prompt(self.prompt_profile, presets, self.prompt_custom)
        return str(main_prompt or "").strip()

    def _chunk_runtime_input(self, runtime_input: str) -> list[str]:
        text = str(runtime_input or "").strip()
        if not text:
            return []
        max_chars = self._max_prompt_chars()
        if max_chars <= 0 or len(text) <= max_chars:
            return [text]
        context_block, transcript_block = self._split_runtime_input(text)
        transcript_text = str(transcript_block or "").strip()
        if not transcript_text:
            return [text]
        overlap = min(max(120, int(max_chars * 0.12)), 600)
        chunks = self._split_text_with_overlap(transcript_text, max_chars=max_chars, overlap_chars=overlap)
        if len(chunks) <= 1:
            return [text]
        return [self._compose_runtime_input(chunk, context_block) for chunk in chunks]

    def _max_prompt_chars(self) -> int:
        budget_tokens = self._context_prompt_budget_tokens()
        return int(budget_tokens * self._prompt_chars_per_token())

    @staticmethod
    def _split_runtime_input(text: str) -> tuple[str, str]:
        raw = str(text or "").strip()
        if not raw:
            return "", ""
        context = ""
        transcript = raw
        if _RUNTIME_CONTEXT_START in raw and _RUNTIME_CONTEXT_END in raw:
            context = raw.split(_RUNTIME_CONTEXT_START, 1)[1].split(_RUNTIME_CONTEXT_END, 1)[0].strip()
        if _RUNTIME_TRANSCRIPT_START in raw and _RUNTIME_TRANSCRIPT_END in raw:
            transcript = raw.split(_RUNTIME_TRANSCRIPT_START, 1)[1].split(_RUNTIME_TRANSCRIPT_END, 1)[0].strip()
        return context, transcript

    @staticmethod
    def _compose_runtime_input(transcript: str, context_block: str) -> str:
        body = str(transcript or "").strip()
        context = str(context_block or "").strip()
        if not context:
            return body
        return "\n".join(
            [
                _RUNTIME_CONTEXT_START,
                context,
                _RUNTIME_CONTEXT_END,
                "",
                _RUNTIME_TRANSCRIPT_START,
                body,
                _RUNTIME_TRANSCRIPT_END,
            ]
        ).strip()

    @staticmethod
    def _split_text_with_overlap(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        if max_chars <= 0 or len(raw) <= max_chars:
            return [raw]
        items: list[str] = []
        start = 0
        length = len(raw)
        while start < length:
            end = min(length, start + max_chars)
            if end < length:
                split_at = raw.rfind("\n", start, end)
                if split_at <= start + int(max_chars * 0.6):
                    split_at = raw.rfind(" ", start, end)
                if split_at > start:
                    end = split_at
            chunk = raw[start:end].strip()
            if chunk:
                items.append(chunk)
            if end >= length:
                break
            next_start = max(0, end - max(0, overlap_chars))
            if next_start <= start:
                next_start = end
            start = next_start
        return items or [raw]

    def _build_chunk_prompt(
        self,
        runtime_input: str,
        *,
        main_prompt: str,
        chunk_index: int,
        total_chunks: int,
    ) -> str:
        chunk_instruction = (
            f"{main_prompt}\n\n"
            f"This is chunk {chunk_index} of {total_chunks} from one long meeting transcript. "
            "Summarize only the facts that appear in this chunk. "
            "Preserve names, dates, tasks, decisions, blockers, and project references exactly. "
            "Return concise markdown notes for later merge. Do not mention chunk numbers."
        )
        return build_prompt(
            transcript=runtime_input,
            main_prompt=chunk_instruction,
            language_override=self.prompt_language,
            max_words=max(220, min(int(self.prompt_max_words or 600), 500)),
        )

    def _build_merge_prompt(self, partial_summaries: str, *, main_prompt: str) -> str:
        merge_instruction = (
            f"{main_prompt}\n\n"
            "The input below contains partial summaries generated from sequential chunks of one meeting transcript. "
            "Merge them into one final meeting summary. Deduplicate repeated points, but preserve every unique fact, "
            "task, date, owner, project, and decision mentioned in any chunk."
        )
        return build_prompt(
            transcript=partial_summaries,
            main_prompt=merge_instruction,
            language_override=self.prompt_language,
            max_words=self.prompt_max_words,
        )

    def _prepare_user_prompt(self, user_text: str, *, model_spec: str) -> str:
        prompt = str(user_text or "").strip()
        if self.disable_thinking and self._supports_no_think(model_spec):
            return f"/no_think\n{prompt}".strip()
        return prompt

    def _supports_no_think(self, model_spec: str) -> bool:
        haystack = " ".join(
            [
                str(self.model_id or ""),
                str(self.model_path or ""),
                str(model_spec or ""),
            ]
        ).lower()
        return "qwen3" in haystack

    @staticmethod
    def _is_mock_result(result: PluginResult) -> bool:
        return any(str(item or "").strip() == "mock_fallback" for item in (result.warnings or []))

    @staticmethod
    def _first_summary_content(result: PluginResult) -> str:
        for output in result.outputs or []:
            if getattr(output, "kind", "") == KIND_SUMMARY:
                return str(getattr(output, "content", "") or "").strip()
        return ""

    @staticmethod
    def _merge_warning_lists(left: list[str], right: list[str]) -> list[str]:
        merged: list[str] = []
        for item in list(left or []) + list(right or []):
            marker = str(item or "").strip()
            if marker and marker not in merged:
                merged.append(marker)
        return merged

    @staticmethod
    def _prompt_chars_per_token() -> float:
        raw = str(os.getenv("AIMN_LLAMA_PROMPT_CHARS_PER_TOKEN", "")).strip()
        if not raw:
            return 1.0
        try:
            parsed = float(raw)
        except Exception:
            return 1.0
        return max(0.5, min(parsed, 3.0))

    def _context_prompt_budget_tokens(self) -> int:
        ctx_size = self._safe_int(self.ctx_size, 4096)
        max_tokens = self._safe_int(self.max_tokens, 900)
        # Keep room for generated tokens and prompt scaffolding.
        budget = ctx_size - max_tokens - 384
        return max(256, budget)

    @staticmethod
    def _safe_int(value: object, fallback: int) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return fallback

    @staticmethod
    def _summarize_stderr(stderr: str) -> list[str]:
        raw = str(stderr or "").strip()
        if not raw:
            return []
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        result: list[str] = []
        lowered = raw.lower()
        if lines:
            tail_line = lines[-1]
            result.append(f"llama_cli_stderr_tail={tail_line[:300]}")
            lowered_tail = tail_line.lower()
            if "prompt is too long" in lowered_tail:
                result.append("llama_cli_prompt_too_long")
            if "context" in lowered_tail and "overflow" in lowered_tail:
                result.append("llama_cli_context_overflow")
        if "invalid hf repo format" in lowered:
            result.append("llama_cli_invalid_hf_repo_format")
        if "unable to load model" in lowered:
            result.append("llama_cli_model_load_failed")
        if "tokenizer.ggml.pre" in lowered and any(
            token in lowered for token in ("override", "invalid", "failed", "error")
        ):
            result.append("llama_cli_tokenizer_override_invalid")
        head = lines[0][:160] if lines else raw[:160]
        result.append(f"llama_cli_stderr_head={head}")
        result.extend(LlamaCliPlugin._stderr_diagnostic_chunks(raw))
        return result

    @staticmethod
    def _stderr_diagnostic_chunks(stderr: str) -> list[str]:
        raw = str(stderr or "").strip()
        if not raw:
            return []
        compact = raw.replace("\r\n", "\n").replace("\r", "\n")
        compact = "\n".join(line.rstrip() for line in compact.split("\n"))
        compact = compact[:6000]
        digest = hashlib.sha1(compact.encode("utf-8", errors="ignore")).hexdigest()[:12]
        chunk_size = 900
        chunks = [compact[index:index + chunk_size] for index in range(0, len(compact), chunk_size)]
        result = [f"llama_cli_stderr_digest={digest} chars={len(compact)} chunks={len(chunks)}"]
        for index, chunk in enumerate(chunks, start=1):
            safe_chunk = chunk.replace("\t", "    ")
            result.append(f"llama_cli_stderr_chunk[{index}/{len(chunks)}]={safe_chunk}")
        return result


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_SUMMARY, ArtifactSchema(content_type="text/markdown", user_visible=True))
        ctx.register_hook_handler("derive.after_postprocess", hook_derive_summary, mode="optional", priority=100)
        ctx.register_settings_schema(settings_schema)
        ctx.register_actions(action_descriptors)
        ctx.register_job_provider(job_provider)
        _ensure_default_settings(ctx)


def hook_derive_summary(ctx: HookContext) -> PluginResult:
    params = _filtered_params(ctx.plugin_config or {})
    plugin = LlamaCliPlugin(**params) if params else LlamaCliPlugin()
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


def _filtered_params(params: dict) -> dict:
    allowed = {
        "binary_path",
        "model_path",
        "model_id",
        "model_quant",
        "allow_download",
        "cache_dir",
        "hf_token",
        "system_prompt",
        "prompt_profile",
        "prompt_custom",
        "prompt_language",
        "prompt_presets",
        "prompt_max_words",
        "temperature",
        "ctx_size",
        "gpu_layers",
        "vulkan_visible_devices",
        "disable_thinking",
        "extra_args",
        "timeout_seconds",
    }
    filtered: dict = {}
    for key, value in params.items():
        if key in allowed:
            filtered[key] = value
    return _normalize_selected_model_params(filtered, params)


def _normalize_selected_model_params(filtered: dict, params: dict) -> dict:
    normalized = dict(filtered)
    model_path = str(normalized.get("model_path", "") or "").strip()
    if model_path:
        return normalized
    models = params.get("models")
    if not isinstance(models, list):
        return normalized

    current_model_id = str(normalized.get("model_id", "") or "").strip()
    current_row = _find_matching_model_row(models, current_model_id)
    if current_row and _model_row_installed(current_row):
        return normalized

    replacement = _preferred_installed_model_row(models)
    if not replacement:
        return normalized

    replacement_model_id = str(replacement.get("model_id", "") or "").strip()
    replacement_quant = str(replacement.get("quant", "") or "").strip()
    if replacement_model_id:
        normalized["model_id"] = replacement_model_id
    normalized["model_path"] = ""
    if replacement_quant:
        normalized["model_quant"] = replacement_quant
    return normalized


def _find_matching_model_row(rows: list[object], model_id: str) -> dict | None:
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    for item in rows:
        if not isinstance(item, dict):
            continue
        current = str(item.get("model_id", "") or "").strip()
        if current == wanted:
            return dict(item)
    return None


def _model_row_installed(row: dict) -> bool:
    installed = row.get("installed")
    if isinstance(installed, bool):
        return installed
    status = str(row.get("status", "") or "").strip().lower()
    availability = str(row.get("availability_status", "") or "").strip().lower()
    return status == "installed" or availability == "ready"


def _preferred_installed_model_row(rows: list[object]) -> dict | None:
    best_row: dict | None = None
    best_score: tuple[int, int, int, int] | None = None
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("model_id", "") or "").strip()
        if not model_id or not _model_row_installed(item):
            continue
        score = (
            1 if _coerce_bool(item.get("favorite")) else 0,
            1 if _coerce_bool(item.get("enabled")) else 0,
            1 if _coerce_bool(item.get("observed_success")) else 0,
            -index,
        )
        if best_score is None or score > best_score:
            best_score = score
            best_row = item
    return dict(best_row) if isinstance(best_row, dict) else None


_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "Provider Settings",
        "description": "Manage local models.",
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
                "description": "Manage local model files.",
                "columns": [
                    {"id": "model_id", "label": "Model ID", "type": "string"},
                    {"id": "quant", "label": "Quant", "type": "string"},
                    {"id": "file", "label": "File", "type": "string", "readonly": True},
                    {"id": "enabled", "label": "Enabled", "type": "bool"},
                    {"id": "status", "label": "Status", "type": "status", "readonly": True},
                ],
                "row_id": "model_id",
                "row_actions": [
                    {
                        "id": "download_model",
                        "label": "Download",
                        "params": [
                            {"id": "model_id", "source": "row.model_id"},
                            {"id": "quant", "source": "row.quant"},
                        ],
                    },
                    {
                        "id": "remove_model",
                        "label": "Remove",
                        "dangerous": True,
                        "confirm": {"title": "Remove model?", "message": "This deletes local files."},
                        "params": [
                            {"id": "model_id", "source": "row.model_id"},
                            {"id": "quant", "source": "row.quant"},
                            {"id": "file", "source": "row.file"},
                        ],
                    },
                ],
            },
        ],
    }


def action_descriptors() -> list[ActionDescriptor]:
    return [
        ActionDescriptor(
            action_id="list_models",
            label="Refresh Models",
            description="Load available local model catalog and installation status.",
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
            action_id="validate_hf_token",
            label="Validate Hugging Face Token",
            description="Check that the configured Hugging Face token is valid.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_validate_hf_token,
        ),
        ActionDescriptor(
            action_id="download_model",
            label="Download Model",
            description="Download a model file in the background.",
            params_schema={
                "fields": [
                    {"id": "model_id", "type": "string", "required": True},
                    {"id": "quant", "type": "string", "required": False},
                ]
            },
            dangerous=False,
            run_mode="sync",
            handler=action_download_model,
        ),
        ActionDescriptor(
            action_id="remove_model",
            label="Remove Model",
            description="Remove a cached model file.",
            params_schema={
                "fields": [
                    {"id": "model_id", "type": "string", "required": True},
                    {"id": "quant", "type": "string", "required": False},
                    {"id": "file", "type": "string", "required": False},
                ]
            },
            dangerous=True,
            handler=action_remove_model,
        ),
    ]


def action_list_models(settings: dict, params: dict) -> ActionResult:
    builtin_rows: dict[str, dict] = {}
    for entry in _builtin_model_rows():
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if not model_id:
            continue
        builtin_rows[model_id] = {
            "model_id": model_id,
            "product_name": str(entry.get("product_name", model_id) or entry.get("name", model_id)).strip()
            or model_id,
            "quant": str(entry.get("quant", "")).strip() or "Q4_K_M",
            "file": str(entry.get("file", "")).strip(),
            "source_url": str(entry.get("source_url", "") or "").strip(),
            "download_url": str(entry.get("download_url", "") or "").strip(),
            "description": str(entry.get("notes", "") or entry.get("description", "") or "").strip(),
            "enabled": bool(entry.get("enabled", False)),
            "catalog_source": str(entry.get("catalog_source", "") or "builtin").strip() or "builtin",
            "user_added": False,
        }

    rows_by_id: dict[str, dict] = {}
    raw_models = settings.get("models")
    settings_rows: list[dict] = [dict(item) for item in raw_models if isinstance(item, dict)] if isinstance(raw_models, list) else []
    for entry in settings_rows:
        model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if not model_id:
            continue
        user_added = bool(entry.get("user_added", False))
        builtin = builtin_rows.get(model_id, {})
        product_name = str(entry.get("product_name", "") or builtin.get("product_name", "") or model_id).strip() or model_id
        rows_by_id[model_id] = {
            "model_id": model_id,
            "product_name": product_name,
            "quant": str(entry.get("quant", "") or builtin.get("quant", "")).strip() or "Q4_K_M",
            "file": str(entry.get("file", "") or builtin.get("file", "")).strip(),
            "source_url": str(entry.get("source_url", "") or builtin.get("source_url", "") or "").strip(),
            "download_url": str(entry.get("download_url", "") or builtin.get("download_url", "") or "").strip(),
            "description": str(entry.get("description", "") or builtin.get("description", "") or "").strip(),
            "enabled": bool(entry.get("enabled", False)),
            "catalog_source": str(entry.get("catalog_source", "") or ("user" if user_added else "catalog")).strip()
            or ("user" if user_added else "catalog"),
            "user_added": user_added,
        }
    rows = list(rows_by_id.values())

    cache_dir = str(settings.get("cache_dir", "models/llama")).strip() or "models/llama"
    root = _resolved_cache_root(cache_dir)

    models: list[dict] = []
    for row in rows:
        model_id = str(row.get("model_id", "")).strip()
        if not model_id:
            continue
        quant = str(row.get("quant", "")).strip() or "Q4_K_M"
        source_url = str(row.get("source_url", "") or "").strip()
        download_url = str(row.get("download_url", "") or "").strip()
        file_name = _known_model_filename(
            str(row.get("file", "")).strip(),
            download_url=download_url,
            source_url=source_url,
        )
        installed = bool(file_name and (root / file_name).exists())
        models.append(
            {
                "model_id": model_id,
                "product_name": str(row.get("product_name", model_id)).strip() or model_id,
                "quant": quant,
                "file": file_name,
                "source_url": source_url,
                "download_url": download_url,
                "description": str(row.get("description", "") or "").strip(),
                "enabled": bool(row.get("enabled", False)),
                "installed": bool(installed),
                "status": "installed" if installed else "",
                "availability_status": "ready" if installed else "needs_setup",
                "catalog_source": str(row.get("catalog_source", "") or ("user" if row.get("user_added", False) else "catalog")).strip()
                or ("user" if row.get("user_added", False) else "catalog"),
                "user_added": bool(row.get("user_added", False)),
            }
        )
    return ActionResult(status="success", message="models_loaded", data={"models": models})

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

    runtime = LlamaCliPlugin(**_filtered_params(settings))
    binary_path = _resolve_path(runtime.binary_path, "AIMN_LLAMA_CLI_PATH")
    if not binary_path:
        return ActionResult(status="error", message="llama_cli_missing")

    cache_dir = _resolve_dir(runtime.cache_dir, "AIMN_LLAMA_CACHE_DIR")
    model_spec, use_hf_repo, resolve_warnings = _resolve_model_execution_spec(
        model_path=runtime.model_path,
        model_id=runtime.model_id,
        model_quant=runtime.model_quant,
        cache_dir=cache_dir,
        allow_download=runtime.allow_download,
    )
    if not model_spec:
        return ActionResult(
            status="error",
            message=resolve_warnings[0] if resolve_warnings else "llama_cli_model_missing",
        )
    if not use_hf_repo:
        model_file_warnings = _validate_local_gguf_file(model_spec)
        if model_file_warnings:
            return ActionResult(status="error", message=model_file_warnings[0], data={"model_path": model_spec})

    cmd = [
        binary_path,
        "--no-display-prompt",
        "--simple-io",
        "--single-turn",
        "-n",
        "-1",
        "--temp",
        str(runtime.temperature),
    ]
    if runtime.ctx_size:
        cmd.extend(["-c", str(runtime.ctx_size)])
    if runtime.gpu_layers is not None:
        cmd.extend(["-ngl", str(runtime.gpu_layers)])
    cmd.extend(["-sys", _prompt_refiner_system_prompt()])
    if use_hf_repo:
        cmd.extend(["--hf-repo", model_spec])
    else:
        cmd.extend(["-m", model_spec])
    cmd.extend(["-p", _prompt_refiner_user_text(prompt_text, objective)])
    if runtime.extra_args:
        cmd.extend(shlex.split(runtime.extra_args, posix=False))

    env = os.environ.copy()
    if cache_dir:
        env["LLAMA_CACHE"] = cache_dir
        env["LLAMA_CACHE_DIR"] = cache_dir
    if runtime.hf_token:
        env["HUGGINGFACE_HUB_TOKEN"] = runtime.hf_token
        env["HF_TOKEN"] = runtime.hf_token
        env["AIMN_HF_TOKEN"] = runtime.hf_token
    visible_devices = (
        str(os.getenv("AIMN_LLAMA_VISIBLE_DEVICES", "") or "").strip()
        or runtime.vulkan_visible_devices
    )
    if visible_devices:
        env["GGML_VK_VISIBLE_DEVICES"] = visible_devices

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=runtime.timeout_seconds,
            env=env,
            creationflags=_subprocess_creationflags(),
        )
    except subprocess.TimeoutExpired:
        return ActionResult(status="error", message="llama_cli_timeout")
    except Exception as exc:
        return ActionResult(status="error", message=f"llama_cli_error({exc})")

    if int(result.returncode) != 0:
        tail = str(result.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else f"code={result.returncode}"
        return ActionResult(
            status="error",
            message=f"llama_cli_failed({result.returncode})",
            data={"detail": str(detail)[:300]},
        )
    refined = _sanitize_refined_prompt(result.stdout or "")
    if not refined:
        return ActionResult(status="error", message="refined_prompt_empty")
    return ActionResult(status="success", message="prompt_refined", data={"prompt": refined, "model_id": model_spec})


def action_validate_hf_token(settings: dict, params: dict) -> ActionResult:
    _ = params
    hf_token = str(settings.get("hf_token", "") or "").strip()
    if not hf_token:
        return ActionResult(status="error", message="hf_token_missing")

    url = "https://huggingface.co/api/whoami-v2"
    request = _request_with_optional_hf_auth(url, accept="application/json", hf_token=hf_token)
    try:
        with _urlopen_with_hf_proxy_retry(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ActionResult(
            status="error",
            message="hf_token_invalid",
            data={"error": _huggingface_access_error(url, "", getattr(exc, "code", None))},
        )
    except Exception as exc:
        return ActionResult(
            status="error",
            message="hf_token_validation_failed",
            data={"error": str(exc)},
        )

    data = payload if isinstance(payload, dict) else {}
    user_name = str(data.get("name", "") or data.get("fullname", "") or "").strip()
    response_data: dict[str, object] = {}
    if user_name:
        response_data["account"] = user_name
    return ActionResult(status="success", message="hf_token_valid", data=response_data)


def action_download_model(settings: dict, params: dict) -> ActionResult:
    model_id = str(params.get("model_id", "")).strip()
    if not model_id:
        return ActionResult(status="error", message="model_id_missing")
    quant = str(params.get("quant", "")).strip() or "Q4_K_M"
    cache_dir = str(settings.get("cache_dir", "models/llama")).strip() or "models/llama"
    hf_token = str(settings.get("hf_token", "") or "").strip()
    logging.getLogger("aimn.local.llama_cli").info(
        "model_download_requested model=%s quant=%s cache_dir=%s direct_url=%s",
        model_id,
        quant,
        cache_dir,
        bool(str(params.get("download_url", "") or "").strip()),
    )
    model_row = _find_model_row(settings, model_id)
    download_url = str(params.get("download_url", "") or model_row.get("download_url", "") or "").strip()
    source_url = str(model_row.get("source_url", "") or "").strip()
    direct_download_url = download_url if _infer_filename_from_download_url(download_url) else ""
    file_name = _known_model_filename(
        str(params.get("file", "") or model_row.get("file", "") or "").strip(),
        download_url=direct_download_url,
        source_url=source_url,
    )
    if not file_name and not direct_download_url:
        try:
            file_name = _resolve_hf_filename(model_id, quant, hf_token=hf_token)
        except Exception as exc:
            return ActionResult(
                status="error",
                message="model_file_resolution_failed",
                data={"model_id": model_id, "error": str(exc)},
            )
    job_id = _start_download_job(
        model_id,
        quant,
        cache_dir,
        download_url=direct_download_url,
        file_name=file_name,
        hf_token=hf_token,
    )
    return ActionResult(
        status="accepted",
        message="download_started",
        job_id=job_id,
        data={"model_id": model_id, "quant": quant, "download_url": direct_download_url, "file": file_name},
    )


def action_remove_model(settings: dict, params: dict) -> ActionResult:
    model_id = str(params.get("model_id", "")).strip()
    quant = str(params.get("quant", "")).strip() or "Q4_K_M"
    cache_dir = str(settings.get("cache_dir", "models/llama")).strip() or "models/llama"
    hf_token = str(settings.get("hf_token", "") or "").strip()
    model_row = _find_model_row(settings, model_id)
    download_url = str(params.get("download_url", "") or model_row.get("download_url", "") or "").strip()
    source_url = str(model_row.get("source_url", "") or "").strip()
    filename = _known_model_filename(
        str(params.get("file", "") or model_row.get("file", "") or "").strip(),
        download_url=download_url,
        source_url=source_url,
    )
    removed, removed_file = _remove_model_file(
        model_id,
        quant,
        cache_dir,
        filename,
        download_url=download_url,
        source_url=source_url,
        hf_token=hf_token,
    )
    raw_models = settings.get("models")
    settings_rows: list[dict] = [dict(item) for item in raw_models if isinstance(item, dict)] if isinstance(raw_models, list) else []
    remove_from_settings = any(
        str(entry.get("model_id", "") or entry.get("id", "")).strip() == model_id and bool(entry.get("user_added", False))
        for entry in settings_rows
    )
    refreshed = action_list_models(settings, {})
    data: dict[str, object] = {"model_id": model_id}
    if removed_file:
        data["file"] = removed_file
    data["remove_from_settings"] = remove_from_settings
    if isinstance(refreshed.data, dict):
        data.update(refreshed.data)
    if removed:
        return ActionResult(status="success", message="model_removed", data=data)
    return ActionResult(status="success", message="model_not_found_for_remove", data=data)


def job_provider() -> dict:
    return {"get_status": _get_job_status}


def _start_download_job(
    model_id: str,
    quant: str,
    cache_dir: str,
    *,
    download_url: str = "",
    file_name: str = "",
    hf_token: str = "",
) -> str:
    job_id = str(uuid.uuid4())
    logging.getLogger("aimn.local.llama_cli").info(
        "model_download_job_started job_id=%s model=%s quant=%s cache_dir=%s",
        job_id,
        model_id,
        quant,
        cache_dir,
    )
    with _JOB_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0.0,
            "message": "queued",
            "updated_at": _now_iso(),
        }

    def _worker() -> None:
        _update_job(job_id, status="running", message="downloading")
        try:
            filename = str(file_name or "").strip()
            direct_url = str(download_url or "").strip()
            if direct_url:
                if not filename:
                    filename = _infer_filename_from_download_url(direct_url)
                if not filename:
                    _update_job(job_id, status="error", message="model_file_not_found")
                    return
            else:
                filename = _resolve_hf_filename(model_id, quant, hf_token=hf_token)
            if not filename:
                _update_job(job_id, status="error", message="model_file_not_found")
                return
            target_dir = Path(cache_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            if target.exists():
                _update_job(job_id, status="success", progress=1.0, message="already_downloaded")
                return
            partial_target = _partial_download_path(target)
            if partial_target.exists():
                partial_target.unlink()
            url = direct_url or f"https://huggingface.co/{model_id}/resolve/main/{filename}"
            _download_file(url, target, job_id, hf_token=hf_token)
            _update_job(job_id, status="success", progress=1.0, message="downloaded")
            logging.getLogger("aimn.local.llama_cli").info(
                "model_download_job_success job_id=%s model=%s file=%s",
                job_id,
                model_id,
                target.name,
            )
        except Exception as exc:
            _update_job(job_id, status="error", message=str(exc))
            logging.getLogger("aimn.local.llama_cli").warning(
                "model_download_job_failed job_id=%s model=%s error=%s",
                job_id,
                model_id,
                exc,
            )

    threading.Thread(target=_worker, daemon=True).start()
    return job_id


def _download_file(url: str, target: Path, job_id: str, *, hf_token: str = "") -> None:
    partial_target = _partial_download_path(target)
    request = _request_with_optional_hf_auth(url, hf_token=hf_token)
    try:
        with _urlopen_with_hf_proxy_retry(request) as response:
            total_size = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            chunk_size = 1024 * 1024
            with partial_target.open("wb") as handle:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = min(1.0, downloaded / total_size)
                        _update_job(job_id, progress=percent, message="downloading")
        partial_target.replace(target)
        validation_warnings = _validate_local_gguf_file(str(target))
        if validation_warnings:
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError(validation_warnings[0])
    except urllib.error.HTTPError as exc:
        try:
            if partial_target.exists():
                partial_target.unlink()
        except Exception:
            pass
        raise RuntimeError(_huggingface_access_error(url, "", getattr(exc, "code", None))) from exc
    except Exception:
        try:
            if partial_target.exists():
                partial_target.unlink()
        except Exception:
            pass
        raise


def _partial_download_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.part")


def _infer_filename_from_download_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    path = urlparse(raw).path
    name = Path(path).name
    if name.lower().endswith(".gguf"):
        return name
    return ""


def _known_model_filename(file_name: str = "", *, download_url: str = "", source_url: str = "") -> str:
    explicit = str(file_name or "").strip()
    if explicit:
        return explicit
    for raw_url in (download_url, source_url):
        inferred = _infer_filename_from_download_url(raw_url)
        if inferred:
            return inferred
    return ""


def _hf_auth_token() -> str:
    return _hf_auth_token_from("")


def _hf_auth_token_from(explicit_token: str) -> str:
    explicit = str(explicit_token or "").strip()
    if explicit:
        return explicit
    for key in _HF_TOKEN_ENV_KEYS:
        value = str(os.getenv(key, "") or "").strip()
        if value:
            return value
    return ""


def _is_huggingface_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw:
        return False
    host = urlparse(raw).netloc.lower()
    return host == "huggingface.co" or host.endswith(".huggingface.co") or host == "hf.co"


def _request_with_optional_hf_auth(url: str, *, accept: str = "", hf_token: str = "") -> urllib.request.Request:
    headers = {"User-Agent": "AIMN Llama CLI"}
    if accept:
        headers["Accept"] = accept
    if _is_huggingface_url(url):
        token = _hf_auth_token_from(hf_token)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _request_url(request: urllib.request.Request | str) -> str:
    if isinstance(request, urllib.request.Request):
        return str(getattr(request, "full_url", "") or "").strip()
    return str(request or "").strip()


def _proxy_settings_present() -> bool:
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return False
    if not isinstance(proxies, dict):
        return False
    for key in ("http", "https", "all"):
        if str(proxies.get(key, "") or "").strip():
            return True
    return False


def _is_proxy_retryable_error(url: str, exc: BaseException) -> bool:
    if not _is_huggingface_url(url):
        return False
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if not _proxy_settings_present():
        return False
    reason = getattr(exc, "reason", None)
    if isinstance(reason, OSError):
        winerror = getattr(reason, "winerror", None)
        errno = getattr(reason, "errno", None)
        if winerror in {10061} or errno in {61, 111}:
            return True
    text = " ".join(
        [
            str(exc or ""),
            str(reason or ""),
            str(getattr(reason, "strerror", "") or ""),
        ]
    ).lower()
    return any(
        token in text
        for token in (
            "127.0.0.1:9",
            "proxy",
            "connection refused",
            "actively refused",
            "cannot connect",
        )
    )


def _urlopen_with_hf_proxy_retry(
    request: urllib.request.Request | str,
    *,
    timeout: int | float | None = None,
):
    url = _request_url(request)
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except Exception as exc:
        if not _is_proxy_retryable_error(url, exc):
            raise
        logging.getLogger("aimn.local.llama_cli").warning(
            "hf_proxy_retry_without_proxy url=%s error=%s",
            url,
            exc,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)


def _huggingface_access_error(url: str, model_id: str, code: int | None) -> str:
    target = f" for '{model_id}'" if str(model_id or "").strip() else ""
    status = f" ({code})" if code else ""
    if _is_huggingface_url(url) and code in {401, 403}:
        return (
            f"Hugging Face access denied{status}{target}. "
            "If the repository is gated/private, accept the model license and set "
            "HUGGINGFACE_HUB_TOKEN, HF_TOKEN, or AIMN_HF_TOKEN."
        )
    return f"HTTP access failed{status}{target}: {url}"


def _find_model_row(settings: dict, model_id: str) -> dict:
    wanted = str(model_id or "").strip()
    raw_models = settings.get("models")
    if isinstance(raw_models, list):
        for entry in raw_models:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("model_id", "") or "").strip() == wanted:
                return dict(entry)
    for entry in _builtin_model_rows():
        if str(entry.get("model_id", "") or entry.get("id", "") or "").strip() == wanted:
            return dict(entry)
    return {}


def _resolve_hf_filename(model_id: str, quant: str, *, hf_token: str = "") -> str:
    api_url = f"https://huggingface.co/api/models/{model_id}"
    request = _request_with_optional_hf_auth(api_url, accept="application/json", hf_token=hf_token)
    try:
        with _urlopen_with_hf_proxy_retry(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_huggingface_access_error(api_url, model_id, getattr(exc, "code", None))) from exc
    siblings = data.get("siblings", [])
    files = []
    for entry in siblings:
        if isinstance(entry, dict):
            name = entry.get("rfilename") or entry.get("name") or ""
        else:
            name = str(entry)
        if name.lower().endswith(".gguf"):
            files.append(name)
    if not files:
        return ""
    quant_token = quant.lower().replace("-", "_")
    for name in files:
        if quant_token and quant_token in name.lower().replace("-", "_"):
            return name
    if len(files) == 1:
        return files[0]
    return ""


def _remove_model_file(
    model_id: str,
    quant: str,
    cache_dir: str,
    filename: str,
    *,
    download_url: str = "",
    source_url: str = "",
    hf_token: str = "",
) -> tuple[bool, str]:
    root = _resolved_cache_root(cache_dir)
    candidates: list[Path] = []
    known_name = _known_model_filename(filename, download_url=download_url, source_url=source_url)
    if known_name:
        candidates.append(root / known_name)
    elif model_id:
        try:
            resolved = _resolve_hf_filename(model_id, quant, hf_token=hf_token)
        except Exception:
            resolved = ""
        if resolved:
            candidates.append(root / resolved)

    seen: set[str] = set()
    for target in candidates:
        normalized = str(target)
        if normalized in seen:
            continue
        seen.add(normalized)
        if not target.exists() or not target.is_file():
            continue
        target.unlink()
        return True, target.name
    return False, ""


def _get_job_status(job_id: str) -> dict | None:
    with _JOB_LOCK:
        status = _JOBS.get(job_id)
        return dict(status) if status else None


def _update_job(job_id: str, **updates: object) -> None:
    with _JOB_LOCK:
        status = _JOBS.get(job_id)
        if not status:
            return
        status.update(updates)
        status["updated_at"] = _now_iso()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ensure_default_settings(ctx) -> None:
    settings = ctx.get_settings()
    if settings.get("models"):
        return
    models: list[dict] = []
    for entry in _builtin_model_rows():
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id", "") or entry.get("id", "")).strip()
        if not model_id:
            continue
        quant = str(entry.get("quant", "")).strip() or "Q4_K_M"
        models.append(
            {
                "model_id": model_id,
                "product_name": str(entry.get("product_name", "") or entry.get("name", "") or model_id).strip()
                or model_id,
                "quant": quant,
                "file": str(entry.get("file", "")).strip(),
                "source_url": str(entry.get("source_url", "") or "").strip(),
                "download_url": str(entry.get("download_url", "") or "").strip(),
                "description": str(entry.get("description", "") or entry.get("notes", "") or "").strip(),
                "size_hint": str(entry.get("size_hint", "") or "").strip(),
                "enabled": bool(entry.get("enabled", True)),
                "status": "",
            }
        )
    if models:
        payload = dict(settings)
        payload["models"] = models
        ctx.set_settings(payload, secret_fields=[])
