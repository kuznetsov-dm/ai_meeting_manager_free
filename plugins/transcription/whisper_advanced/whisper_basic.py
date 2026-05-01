from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from aimn.plugins.api import ArtifactSchema, HookContext, emit_result, parse_progress
from aimn.plugins.interfaces import (
    KIND_ASR_SEGMENTS_JSON,
    KIND_TRANSCRIPT,
    PluginOutput,
    PluginResult,
)

_WHISPER_CPP_MODEL_REPO = "https://huggingface.co/ggerganov/whisper.cpp"

_MODEL_FILES = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
    "small-q8_0": "ggml-small-q8_0.bin",
    "medium": "ggml-medium.bin",
    "medium-q8_0": "ggml-medium-q8_0.bin",
    "large-v3-turbo": "ggml-large-v3-turbo.bin",
    "large-v3-turbo-q5_0": "ggml-large-v3-turbo-q5_0.bin",
    "large-v3-turbo-q8_0": "ggml-large-v3-turbo-q8_0.bin",
    "large-v3": "ggml-large-v3.bin",
    "large-v3-q5_0": "ggml-large-v3-q5_0.bin",
}

_DEFAULT_VAD_MODEL_PATH = "models/whisper/ggml-silero-v6.2.0.bin"

_TS_LINE = re.compile(
    r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\]\s*(.*)$"
)
_LANG_CODE_RE = re.compile(r"^[a-z]{2,8}(?:-[a-z0-9]{2,8})?$")
_LANG_DETECT_RE = re.compile(r"Detected language:\s*([a-zA-Z-]+)")
_LANG_OPTIONS: list[tuple[str, str]] = [
    ("(not set)", ""),
    ("English (en)", "en"),
    ("Russian (ru)", "ru"),
    ("Ukrainian (uk)", "uk"),
    ("German (de)", "de"),
    ("French (fr)", "fr"),
    ("Spanish (es)", "es"),
    ("Italian (it)", "it"),
    ("Portuguese (pt)", "pt"),
    ("Polish (pl)", "pl"),
    ("Turkish (tr)", "tr"),
    ("Arabic (ar)", "ar"),
    ("Hindi (hi)", "hi"),
    ("Chinese (zh)", "zh"),
    ("Japanese (ja)", "ja"),
    ("Korean (ko)", "ko"),
]


def _subprocess_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_text_best_effort(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "cp866"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _resolve_binary_candidate(raw: str) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(_repo_root() / path)
        candidates.append(path)
    if path.suffix == ".exe":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(""))
    if path.suffix == "" and os.name == "nt":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(".exe"))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    system = shutil.which(str(raw)) or shutil.which(Path(raw).name)
    if system:
        return Path(system)
    return candidates[0] if candidates else None


def _default_whisper_path() -> Path:
    resolved = _resolve_binary_candidate("bin/whisper_cpp/whisper-cli")
    if resolved:
        return resolved
    fallback = "bin/whisper_cpp/whisper-cli.exe" if os.name == "nt" else "bin/whisper_cpp/whisper-cli"
    return _repo_root() / fallback


def _default_model_dir() -> Path:
    return _repo_root() / "models" / "whisper"


def _resolve_whisper_path(raw: str | None) -> Path:
    if raw:
        resolved = _resolve_binary_candidate(raw)
        if resolved:
            return resolved
    return _default_whisper_path()


def _validate_local_executable(path: Path, *, label: str) -> list[str]:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return [f"{label}_missing"]
    try:
        size = int(target.stat().st_size)
    except Exception:
        size = 0
    if size <= 0:
        return [f"{label}_empty"]
    if size < 4096:
        return [f"{label}_too_small(bytes={size})"]
    return []


def _resolve_model_path(model: str, models_dir: str | None) -> Path:
    model_key = model if model in _MODEL_FILES else "small"
    filename = _MODEL_FILES[model_key]
    base = Path(models_dir) if models_dir else _default_model_dir()
    if not base.is_absolute():
        base = _repo_root() / base
    return base / filename


def _resolve_vad_model_path(raw: str | None) -> Path:
    candidate = str(raw or "").strip() or _DEFAULT_VAD_MODEL_PATH
    path = Path(candidate)
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


def _validate_whisper_model_file(path: Path, *, label: str) -> list[str]:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return [f"{label}_missing"]
    try:
        size = int(target.stat().st_size)
    except Exception:
        size = 0
    try:
        with target.open("rb") as handle:
            head = handle.read(16)
    except Exception as exc:
        return [f"{label}_unreadable({exc})"]
    if size <= 0:
        return [f"{label}_empty"]
    lowered = head.lower()
    if lowered.startswith((b"<!do", b"<html", b"<?xm")):
        return [f"{label}_invalid_magic_html({target.name})"]
    if size < 1024:
        return [f"{label}_too_small(bytes={size})"]
    if target.suffix.lower() != ".bin":
        return [f"{label}_invalid_extension({target.suffix.lower()})"]
    return []


def _raise_validation_error(warnings: list[str]) -> None:
    reason = warnings[0] if warnings else "whisper_validation_failed"
    raise RuntimeError(reason)


def _default_model_url(model: str) -> str:
    filename = _MODEL_FILES.get(str(model or "").strip(), "")
    if not filename:
        return ""
    return f"{_WHISPER_CPP_MODEL_REPO}/resolve/main/{filename}"


def _coerce_bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_language_mode(raw: str | None) -> str:
    mode = str(raw or "").strip().lower()
    if mode in {"auto", "none", "forced"}:
        return mode
    return "auto"


def _normalize_language_code(raw: str | None) -> str:
    code = str(raw or "").strip().lower()
    if not code or code in {"auto", "none"}:
        return ""
    if not _LANG_CODE_RE.match(code):
        return ""
    return code


def _detect_language(whisper: Path, model_path: Path, media_path: Path) -> str:
    cmd = [
        str(whisper),
        "-m",
        str(model_path),
        "-f",
        str(media_path),
        "-dl",
    ]
    lines: list[str] = []
    rc = _run_whisper(cmd, os.environ.copy(), None, lines)
    if rc != 0:
        return ""
    for line in lines:
        match = _LANG_DETECT_RE.search(str(line or ""))
        if not match:
            continue
        normalized = _normalize_language_code(match.group(1))
        if normalized:
            return normalized
    return ""


def _resolve_language_arg(
    *,
    whisper: Path,
    model_path: Path,
    media_path: Path,
    language_mode: str,
    language_code: str,
    two_pass: bool,
) -> str:
    mode = _normalize_language_mode(language_mode)
    code = _normalize_language_code(language_code)

    if mode == "forced":
        if not code:
            raise ValueError("language_code is required when language_mode=forced")
        return code

    detected = ""
    if two_pass and mode in {"auto", "none"}:
        detected = _detect_language(whisper, model_path, media_path)

    if mode == "auto":
        if detected and detected != "en":
            return detected
        return "auto"

    if mode == "none":
        if detected and detected != "en":
            return detected
        return ""

    return "auto"


def download_model(
    model: str,
    models_dir: str | None,
    model_url: str | None = None,
    progress_cb: Callable[[int], None] | None = None,
) -> Path:
    target = _resolve_model_path(model, models_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    url = model_url or _default_model_url(model)
    if not url:
        raise ValueError(f"No download URL for model: {model}")

    def _report(blocks: int, block_size: int, total_size: int) -> None:
        if not progress_cb or total_size <= 0:
            return
        progress_cb(min(100, int(blocks * block_size * 100 / total_size)))

    urllib.request.urlretrieve(url, str(target), _report)
    validation_warnings = _validate_whisper_model_file(target, label="whisper_model")
    if validation_warnings:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        _raise_validation_error(validation_warnings)
    if progress_cb:
        progress_cb(100)
    return target


def _extract_transcript_from_stdout(lines: list[str]) -> str:
    texts: list[str] = []
    for raw in lines:
        line = str(raw or "").rstrip()
        if not line:
            continue
        match = _TS_LINE.match(line)
        if not match:
            continue
        text = match.group(1).strip()
        if text:
            texts.append(text)
    return ("\n".join(texts).strip() + "\n") if texts else ""


def _rebuild_transcript_from_json(asr_json: str) -> str:
    try:
        payload = json.loads(asr_json) if asr_json and asr_json.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return ""
    entries = payload.get("transcription")
    if not isinstance(entries, list):
        entries = payload.get("segments")
    if not isinstance(entries, list):
        return ""
    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text", "") or "").strip()
        if text:
            lines.append(text)
    return ("\n".join(lines).strip() + "\n") if lines else ""


def _run_whisper(
    cmd: list[str],
    env: dict,
    progress_callback,
    output_lines: list[str],
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> int:
    total_ms: int | None = None
    last_emitted: int | None = None
    ts_range = re.compile(
        r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]"
    )
    if progress_callback:
        # Best-effort: infer total duration from WAV headers so we can show % progress even when
        # whisper-cli does not emit explicit "progress=" lines.
        try:
            idx = cmd.index("-f")
            media_path = str(cmd[idx + 1])
            if media_path.lower().endswith(".wav"):
                import wave

                with wave.open(media_path, "rb") as wf:
                    rate = int(wf.getframerate() or 0)
                    frames = int(wf.getnframes() or 0)
                if rate > 0 and frames > 0:
                    total_ms = int(frames * 1000 / rate)
        except Exception:
            total_ms = None

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
        env=env,
        creationflags=_subprocess_creationflags(),
    ) as proc:
        stop_event = threading.Event()

        def _watch_cancel() -> None:
            if not cancel_requested:
                return
            while not stop_event.is_set():
                if cancel_requested():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    for _ in range(10):
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                    if proc.poll() is None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    break
                time.sleep(0.2)

        if cancel_requested:
            threading.Thread(target=_watch_cancel, daemon=True).start()

        if proc.stdout:
            for line in proc.stdout:
                output_lines.append(line)
                if progress_callback:
                    progress = parse_progress(line)
                    if progress is not None:
                        progress_callback(progress)
                        last_emitted = progress
                        continue
                    if total_ms:
                        match = ts_range.match(str(line or ""))
                        if match:
                            hh, mm, ss, msec, ehh, emm, ess, emsec = (int(x) for x in match.groups())
                            end_ms = ((ehh * 3600 + emm * 60 + ess) * 1000) + emsec
                            inferred = int(max(0, min(99, (end_ms * 100) // max(1, total_ms))))
                            if last_emitted is None or inferred > last_emitted:
                                last_emitted = inferred
                                progress_callback(inferred)
        proc.wait()
        stop_event.set()
        if progress_callback and int(proc.returncode or 0) == 0:
            if last_emitted is None or last_emitted < 100:
                progress_callback(100)
        return int(proc.returncode or 0)


class WhisperBasicPlugin:
    def __init__(
        self,
        model: str = "small",
        whisper_path: str | None = None,
        models_dir: str | None = None,
        allow_download: bool = False,
        model_url: str | None = None,
        vad_model: str | None = None,
        language_mode: str = "auto",
        language_code: str | None = None,
        two_pass: bool = False,
    ) -> None:
        self.model = str(model or "small").strip() or "small"
        self.whisper_path = whisper_path
        self.models_dir = models_dir
        self.allow_download = _coerce_bool(allow_download)
        self.model_url = model_url
        self.vad_model = str(vad_model or "").strip()
        self.language_mode = _normalize_language_mode(language_mode)
        self.language_code = _normalize_language_code(language_code)
        self.two_pass = _coerce_bool(two_pass)

    def run(self, ctx: HookContext) -> PluginResult:
        if not ctx.input_media_path:
            raise ValueError("input_media_path is required for whisper transcription")

        whisper = _resolve_whisper_path(self.whisper_path)
        binary_warnings = _validate_local_executable(whisper, label="whisper_cli")
        if binary_warnings:
            _raise_validation_error(binary_warnings)
        model_path = _resolve_model_path(self.model, self.models_dir)
        if not model_path.exists():
            if self.allow_download:
                model_path = download_model(self.model, self.models_dir, self.model_url)
            else:
                raise FileNotFoundError(f"Model not found: {model_path}")
        model_warnings = _validate_whisper_model_file(model_path, label="whisper_model")
        if model_warnings:
            _raise_validation_error(model_warnings)

        vad_model_path = _resolve_vad_model_path(self.vad_model)
        if vad_model_path.suffix.lower() == ".onnx":
            raise RuntimeError(
                "whisper_vad_model_onnx_unsupported: whisper-cli expects ggml VAD .bin model"
            )
        vad_warnings = _validate_whisper_model_file(vad_model_path, label="whisper_vad_model")
        if vad_warnings:
            _raise_validation_error(vad_warnings)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            out_base = tmp_path / "whisper"
            language = _resolve_language_arg(
                whisper=whisper,
                model_path=model_path,
                media_path=Path(ctx.input_media_path),
                language_mode=self.language_mode,
                language_code=self.language_code,
                two_pass=self.two_pass,
            )
            cmd = [
                str(whisper),
                "-m",
                str(model_path),
                "-f",
                str(ctx.input_media_path),
                "-otxt",
                "-oj",
                "-of",
                str(out_base),
                "--vad",
                "--vad-model",
                str(vad_model_path),
            ]
            if language:
                cmd.extend(["-l", language])
            if not ctx.progress_callback:
                cmd.append("-np")

            output_lines: list[str] = []
            returncode = _run_whisper(
                cmd,
                os.environ.copy(),
                ctx.progress_callback,
                output_lines,
                cancel_requested=getattr(ctx, "cancel_requested", None),
            )
            if returncode != 0:
                tail = " | ".join(str(line or "").strip() for line in output_lines[-8:] if str(line or "").strip())
                if tail:
                    raise RuntimeError(f"whisper_cli_failed(code={returncode}): {tail}")
                raise RuntimeError(f"whisper_cli_failed(code={returncode})")

            txt_path = out_base.with_suffix(".txt")
            json_path = out_base.with_suffix(".json")
            transcript = _read_text_best_effort(txt_path) if txt_path.exists() else ""
            asr_json = _read_text_best_effort(json_path) if json_path.exists() else "{}"

            if not transcript.strip():
                transcript = _extract_transcript_from_stdout(output_lines)
            if not transcript.strip():
                transcript = _rebuild_transcript_from_json(asr_json)
            if not transcript.strip():
                raise RuntimeError("whisper_no_transcript_output")

        outputs = [
            PluginOutput(kind=KIND_TRANSCRIPT, content=transcript, content_type="text"),
            PluginOutput(kind=KIND_ASR_SEGMENTS_JSON, content=asr_json, content_type="json", user_visible=False),
        ]
        return PluginResult(outputs=outputs, warnings=[])


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_TRANSCRIPT, ArtifactSchema(content_type="text", user_visible=True))
        ctx.register_artifact_kind(
            KIND_ASR_SEGMENTS_JSON, ArtifactSchema(content_type="json", user_visible=False)
        )
        ctx.register_hook_handler("transcribe.run", hook_transcribe, mode="optional", priority=100)
        ctx.register_settings_schema(settings_schema)
        _ensure_default_settings(ctx)


def hook_transcribe(ctx: HookContext) -> PluginResult:
    params = _filtered_params(ctx.plugin_config or {})
    plugin = WhisperBasicPlugin(**params) if params else WhisperBasicPlugin()
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


def _filtered_params(params: dict) -> dict:
    allowed = {
        "model",
        "whisper_path",
        "models_dir",
        "allow_download",
        "model_url",
        "vad_model",
        "language_mode",
        "language_code",
        "two_pass",
    }
    filtered: dict = {}
    for key, value in params.items():
        if key in allowed:
            filtered[key] = value
    return filtered


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "Whisper Basic Settings",
        "description": "Local Whisper transcription using whisper-cli defaults with VAD enabled.",
        "layout": {"type": "tabs", "tabs": [{"id": "runtime", "title": "Runtime"}]},
        "views": [
            {
                "id": "runtime",
                "type": "form",
                "sections": [
                    {
                        "id": "core",
                        "title": "Core",
                        "fields": [
                            {
                                "id": "language_mode",
                                "label": "Language Mode",
                                "type": "enum",
                                "options": _language_mode_options(),
                            },
                            {
                                "id": "language_code",
                                "label": "Language Code",
                                "type": "enum",
                                "options": _language_code_options(),
                            },
                            {"id": "two_pass", "label": "Two Pass", "type": "bool"},
                        ],
                    }
                ],
            }
        ],
    }


def _model_options() -> list[dict]:
    return [{"label": key, "value": key} for key in _MODEL_FILES.keys()]


def _language_mode_options() -> list[dict]:
    return [
        {"label": "auto", "value": "auto"},
        {"label": "none", "value": "none"},
        {"label": "forced", "value": "forced"},
    ]


def _language_code_options() -> list[dict]:
    return [{"label": label, "value": value} for label, value in _LANG_OPTIONS]


def _ensure_default_settings(ctx) -> None:
    settings = ctx.get_settings()
    raw_models = settings.get("models")
    raw_model_rows: list[dict] = raw_models if isinstance(raw_models, list) else []
    existing = {str(entry.get("model_id")): entry for entry in raw_model_rows if isinstance(entry, dict)}
    models: list[dict] = []
    updated = False
    for model_id, filename in _MODEL_FILES.items():
        entry = existing.get(model_id)
        if not entry:
            models.append({"model_id": model_id, "file": filename, "enabled": True, "status": ""})
            updated = True
            continue
        entry = dict(entry)
        if entry.get("file") != filename:
            entry["file"] = filename
            updated = True
        models.append(entry)
    if len(models) != len(raw_model_rows):
        updated = True
    payload = dict(settings)
    if "language_mode" not in payload:
        payload["language_mode"] = "auto"
        updated = True
    if "language_code" not in payload:
        payload["language_code"] = ""
        updated = True
    if "two_pass" not in payload:
        payload["two_pass"] = False
        updated = True
    if "vad_model" not in payload:
        payload["vad_model"] = _DEFAULT_VAD_MODEL_PATH
        updated = True
    if updated or raw_models is None:
        payload["models"] = models
        ctx.set_settings(payload, secret_fields=[])
