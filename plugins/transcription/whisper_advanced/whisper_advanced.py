from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from aimn.plugins.api import ArtifactSchema, HookContext, emit_result
from aimn.plugins.interfaces import (
    KIND_ASR_SEGMENTS_JSON,
    KIND_TRANSCRIPT,
    ActionDescriptor,
    ActionResult,
    PluginOutput,
    PluginResult,
)

from .whisper_basic import (
    _MODEL_FILES,
    _WHISPER_CPP_MODEL_REPO,
    _coerce_bool,
    _default_model_url,
    _extract_transcript_from_stdout,
    _language_code_options,
    _language_mode_options,
    _normalize_language_code,
    _normalize_language_mode,
    _raise_validation_error,
    _read_text_best_effort,
    _rebuild_transcript_from_json,
    _repo_root,
    _resolve_language_arg,
    _resolve_model_path,
    _resolve_vad_model_path,
    _resolve_whisper_path,
    _run_whisper,
    _validate_local_executable,
    _validate_whisper_model_file,
    download_model,
)

KIND_ASR_DIAGNOSTICS_JSON = "asr_diagnostics_json"

_DEFAULT_NONSPEECH_TAG_REGEX = r"(?i)^\s*\[[^\]]+\]\s*$"
_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, object]] = {}


def _coerce_int(raw: object, *, default: int | None = None) -> int | None:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _coerce_float(raw: object, *, default: float | None = None) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _coerce_enum(raw: object, allowed: set[str], *, default: str) -> str:
    value = str(raw or "").strip().lower()
    return value if value in allowed else default


def _compile_regex(raw: str | None, *, fallback: str) -> re.Pattern[str]:
    value = str(raw or "").strip() or fallback
    try:
        return re.compile(value)
    except re.error:
        return re.compile(fallback)


def _parse_asr_entries(asr_json: str) -> list[dict]:
    try:
        payload = json.loads(asr_json) if asr_json and asr_json.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return []
    entries = payload.get("transcription")
    if not isinstance(entries, list):
        entries = payload.get("segments")
    return entries if isinstance(entries, list) else []


def _entry_text(entry: dict) -> str:
    return str(entry.get("text", "") or "").strip()


def _entry_start_ms(entry: dict) -> int | None:
    offsets = entry.get("offsets")
    if isinstance(offsets, dict):
        value = offsets.get("from")
        try:
            return int(value)
        except Exception:
            return None
    try:
        value = entry.get("start_ms")
        return int(value) if value is not None else None
    except Exception:
        return None


def _format_ts_ms(ms: int | None) -> str:
    if ms is None:
        return ""
    total = int(ms)
    if total < 0:
        total = 0
    s, milli = divmod(total, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}"


def _normalize_for_stuck(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


@dataclass(frozen=True)
class StuckRun:
    start_idx: int
    length: int
    text: str
    start_ms: int | None


def _detect_longest_run(entries: list[dict]) -> StuckRun | None:
    if not entries:
        return None
    texts = [_normalize_for_stuck(_entry_text(e)) for e in entries]
    best_len = 1
    best_start = 0
    best_text = texts[0]
    run_len = 1
    run_start = 0
    run_text = texts[0]
    for idx in range(1, len(texts)):
        t = texts[idx]
        if t and t == run_text:
            run_len += 1
            continue
        if run_len > best_len and run_text:
            best_len = run_len
            best_start = run_start
            best_text = run_text
        run_text = t
        run_start = idx
        run_len = 1
    if run_len > best_len and run_text:
        best_len = run_len
        best_start = run_start
        best_text = run_text
    start_ms = _entry_start_ms(entries[best_start]) if best_len > 1 else None
    return StuckRun(start_idx=best_start, length=best_len, text=best_text, start_ms=start_ms)


def _strip_nonspeech_lines(text: str, tag_re: re.Pattern[str]) -> tuple[str, int]:
    if not text:
        return "", 0
    kept: list[str] = []
    removed = 0
    for raw_line in str(text).splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if tag_re.match(line):
            removed += 1
            continue
        kept.append(line)
    out = ("\n".join(kept).strip() + "\n") if kept else ""
    return out, removed


class WhisperAdvancedPlugin:
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
        # Decode controls
        suppress_nst: bool = True,
        no_context: bool = True,
        max_context: int | None = None,
        best_of: int | None = 5,
        beam_size: int | None = 5,
        entropy_thold: float | None = 2.4,
        logprob_thold: float | None = -1.0,
        no_speech_thold: float | None = 0.6,
        temperature: float | None = 0.0,
        temperature_inc: float | None = 0.2,
        no_fallback: bool = False,
        split_on_word: bool = False,
        initial_prompt: str | None = None,
        carry_initial_prompt: bool = False,
        dtw_model: str | None = None,
        output_json_full: bool = False,
        # Post-guards
        strip_nonspeech_tags: bool = True,
        nonspeech_tag_regex: str | None = None,
        stuck_detector_enabled: bool = True,
        stuck_min_run: int = 50,
        stuck_action: str = "truncate",
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

        self.suppress_nst = _coerce_bool(suppress_nst)
        self.no_context = _coerce_bool(no_context)
        self.max_context = _coerce_int(max_context, default=None)
        self.best_of = _coerce_int(best_of, default=None)
        self.beam_size = _coerce_int(beam_size, default=None)
        self.entropy_thold = _coerce_float(entropy_thold, default=None)
        self.logprob_thold = _coerce_float(logprob_thold, default=None)
        self.no_speech_thold = _coerce_float(no_speech_thold, default=None)
        self.temperature = _coerce_float(temperature, default=None)
        self.temperature_inc = _coerce_float(temperature_inc, default=None)
        self.no_fallback = _coerce_bool(no_fallback)
        self.split_on_word = _coerce_bool(split_on_word)
        self.initial_prompt = str(initial_prompt or "").strip()
        self.carry_initial_prompt = _coerce_bool(carry_initial_prompt)
        self.dtw_model = str(dtw_model or "").strip()
        self.output_json_full = _coerce_bool(output_json_full)

        self.strip_nonspeech_tags = _coerce_bool(strip_nonspeech_tags)
        self.nonspeech_tag_regex = str(nonspeech_tag_regex or "").strip()
        self.stuck_detector_enabled = _coerce_bool(stuck_detector_enabled)
        self.stuck_min_run = int(stuck_min_run) if int(stuck_min_run) > 0 else 50
        self.stuck_action = _coerce_enum(stuck_action, {"fail", "truncate", "keep"}, default="truncate")

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

            cmd: list[str] = [
                str(whisper),
                "-m",
                str(model_path),
                "-f",
                str(ctx.input_media_path),
                "-otxt",
                "-ojf" if self.output_json_full else "-oj",
                "-of",
                str(out_base),
                "--vad",
                "--vad-model",
                str(vad_model_path),
            ]

            if language:
                cmd.extend(["-l", language])

            if self.no_context:
                cmd.extend(["-mc", "0"])
            elif self.max_context is not None:
                cmd.extend(["-mc", str(int(self.max_context))])

            if self.best_of is not None:
                cmd.extend(["-bo", str(int(self.best_of))])
            if self.beam_size is not None:
                cmd.extend(["-bs", str(int(self.beam_size))])

            if self.entropy_thold is not None:
                cmd.extend(["-et", str(float(self.entropy_thold))])
            if self.logprob_thold is not None:
                cmd.extend(["-lpt", str(float(self.logprob_thold))])
            if self.no_speech_thold is not None:
                cmd.extend(["-nth", str(float(self.no_speech_thold))])

            if self.temperature is not None:
                cmd.extend(["--temperature", str(float(self.temperature))])
            if self.temperature_inc is not None:
                cmd.extend(["--temperature-inc", str(float(self.temperature_inc))])
            if self.no_fallback:
                cmd.append("--no-fallback")

            if self.suppress_nst:
                cmd.append("--suppress-nst")
            if self.split_on_word:
                cmd.append("--split-on-word")

            if self.initial_prompt:
                cmd.extend(["--prompt", self.initial_prompt])
                if self.carry_initial_prompt:
                    cmd.append("--carry-initial-prompt")

            if self.dtw_model:
                cmd.extend(["--dtw", self.dtw_model])

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
                tail = " | ".join(
                    str(line or "").strip()
                    for line in output_lines[-8:]
                    if str(line or "").strip()
                )
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

        # Post-processing / diagnostics are done outside tempdir so we can keep the exact outputs.
        entries = _parse_asr_entries(asr_json)
        longest = _detect_longest_run(entries)
        top_counts = Counter(_normalize_for_stuck(_entry_text(e)) for e in entries if _entry_text(e))
        top_common = [
            {"text": text, "count": int(count)}
            for text, count in top_counts.most_common(10)
            if text
        ]

        tag_re = _compile_regex(self.nonspeech_tag_regex, fallback=_DEFAULT_NONSPEECH_TAG_REGEX)
        removed_tags = 0
        if self.strip_nonspeech_tags:
            transcript, removed_tags = _strip_nonspeech_lines(transcript, tag_re)

        stuck_triggered = False
        stuck_action_taken = ""
        stuck_meta: dict[str, object] = {}
        if (
            self.stuck_detector_enabled
            and longest
            and longest.length >= self.stuck_min_run
            and longest.text
        ):
            stuck_triggered = True
            stuck_action_taken = self.stuck_action
            stuck_meta = {
                "run_len": longest.length,
                "start_idx": longest.start_idx,
                "start_ms": longest.start_ms,
                "start_ts": _format_ts_ms(longest.start_ms),
                "text": longest.text,
            }
            if self.stuck_action == "fail":
                raise RuntimeError(
                    "whisper_output_stuck:"
                    f" run_len={longest.length}"
                    f" start_idx={longest.start_idx}"
                    f" start_ts={_format_ts_ms(longest.start_ms)}"
                    f" text={longest.text!r}"
                )
            if self.stuck_action == "truncate":
                # Rebuild a clean transcript from JSON up to the stuck run.
                keep = entries[: longest.start_idx]
                transcript = ("\n".join(_entry_text(e) for e in keep if _entry_text(e)).strip() + "\n") if keep else ""

        diagnostics = {
            "plugin_id": "transcription.whisperadvanced",
            "model": str(self.model),
            "language_arg": language,
            "cmd": [str(x) for x in cmd],
            "stdout_head": [str(x) for x in output_lines[:30]],
            "strip_nonspeech_tags": bool(self.strip_nonspeech_tags),
            "nonspeech_tag_regex": (self.nonspeech_tag_regex or _DEFAULT_NONSPEECH_TAG_REGEX),
            "removed_nonspeech_lines": int(removed_tags),
            "stuck_detector_enabled": bool(self.stuck_detector_enabled),
            "stuck_min_run": int(self.stuck_min_run),
            "stuck_triggered": bool(stuck_triggered),
            "stuck_action_taken": str(stuck_action_taken),
            "stuck": stuck_meta,
            "top_repeated_texts": top_common,
        }

        outputs = [
            PluginOutput(kind=KIND_TRANSCRIPT, content=transcript, content_type="text"),
            PluginOutput(kind=KIND_ASR_SEGMENTS_JSON, content=asr_json, content_type="json", user_visible=False),
            PluginOutput(
                kind=KIND_ASR_DIAGNOSTICS_JSON,
                content=json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n",
                content_type="json",
                user_visible=False,
            ),
        ]
        return PluginResult(outputs=outputs, warnings=[])


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_TRANSCRIPT, ArtifactSchema(content_type="text", user_visible=True))
        ctx.register_artifact_kind(
            KIND_ASR_SEGMENTS_JSON, ArtifactSchema(content_type="json", user_visible=False)
        )
        ctx.register_artifact_kind(
            KIND_ASR_DIAGNOSTICS_JSON, ArtifactSchema(content_type="json", user_visible=False)
        )
        ctx.register_hook_handler("transcribe.run", hook_transcribe, mode="optional", priority=90)
        ctx.register_settings_schema(settings_schema)
        ctx.register_actions(action_descriptors)
        ctx.register_job_provider(job_provider)
        _ensure_default_settings(ctx)


def hook_transcribe(ctx: HookContext) -> PluginResult:
    params = _filtered_params(ctx.plugin_config or {})
    plugin = WhisperAdvancedPlugin(**params) if params else WhisperAdvancedPlugin()
    result = plugin.run(ctx)
    emit_result(ctx, result)
    return None


def _filtered_params(params: dict) -> dict:
    allowed = {
        # Core
        "model",
        "whisper_path",
        "models_dir",
        "allow_download",
        "model_url",
        "vad_model",
        # Language
        "language_mode",
        "language_code",
        "two_pass",
        # Decode
        "suppress_nst",
        "no_context",
        "max_context",
        "best_of",
        "beam_size",
        "entropy_thold",
        "logprob_thold",
        "no_speech_thold",
        "temperature",
        "temperature_inc",
        "no_fallback",
        "split_on_word",
        "initial_prompt",
        "carry_initial_prompt",
        "dtw_model",
        "output_json_full",
        # Guards
        "strip_nonspeech_tags",
        "nonspeech_tag_regex",
        "stuck_detector_enabled",
        "stuck_min_run",
        "stuck_action",
    }
    filtered: dict = {}
    for key, value in params.items():
        if str(key).strip() in allowed:
            filtered[str(key).strip()] = value
    return filtered


def settings_schema() -> dict:
    return {
        "schema_version": 2,
        "title": "Whisper Advanced Settings",
        "description": "Improved local Whisper transcription with model management handled by cards.",
        "layout": {
            "type": "tabs",
            "tabs": [
                {"id": "core", "title": "Core"},
            ],
        },
        "views": [
            {
                "id": "core",
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
            },
        ],
    }


def action_descriptors() -> list[ActionDescriptor]:
    return [
        ActionDescriptor(
            action_id="list_models",
            label="Refresh Models",
            description="Load Whisper model catalog and local installation status.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_list_models,
        ),
        ActionDescriptor(
            action_id="pull_model",
            label="Download Model",
            description="Download selected Whisper model file.",
            params_schema={"fields": [{"id": "model_id", "type": "string", "required": True}]},
            dangerous=False,
            handler=action_pull_model,
        ),
        ActionDescriptor(
            action_id="cancel_download",
            label="Cancel Download",
            description="Cancel active Whisper model download job.",
            params_schema={"fields": [{"id": "job_id", "type": "string", "required": True}]},
            dangerous=False,
            handler=action_cancel_download,
        ),
        ActionDescriptor(
            action_id="remove_model",
            label="Remove Model",
            description="Delete selected Whisper model file.",
            params_schema={"fields": [{"id": "model_id", "type": "string", "required": True}]},
            dangerous=True,
            handler=action_remove_model,
        ),
    ]


def action_list_models(settings: dict, params: dict) -> ActionResult:
    raw = settings.get("models")
    raw_rows: list[dict] = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    rows: list[dict] = [
        row for row in raw_rows if str(row.get("model_id", "") or row.get("id", "")).strip() in _MODEL_FILES
    ]
    known = {str(item.get("model_id", "")).strip() for item in rows if isinstance(item, dict)}
    for model_id, filename in _MODEL_FILES.items():
        if model_id in known:
            continue
        rows.append({"model_id": model_id, "file": filename, "enabled": False, "status": ""})

    models_dir = str(settings.get("models_dir", "")).strip()
    root = Path(models_dir) if models_dir else (_repo_root() / "models" / "whisper")
    if not root.is_absolute():
        root = (_repo_root() / root).resolve()

    models: list[dict] = []
    for row in rows:
        model_id = str(row.get("model_id", "")).strip()
        if not model_id:
            continue
        file_name = str(row.get("file", "")).strip() or _MODEL_FILES.get(model_id, "")
        installed = bool(file_name) and (root / file_name).exists()
        models.append(
            {
                "model_id": model_id,
                "product_name": _display_model_name(model_id),
                "file": file_name,
                "enabled": bool(row.get("enabled", False)),
                "installed": bool(installed),
                "status": "installed" if installed else "",
                "availability_status": "ready" if installed else "needs_setup",
                "source_url": _WHISPER_CPP_MODEL_REPO,
                "download_url": _default_model_url(model_id),
            }
        )
    return ActionResult(status="success", message="models_loaded", data={"models": models})


def action_pull_model(settings: dict, params: dict) -> ActionResult:
    model_id = str(params.get("model_id", "")).strip()
    if model_id not in _MODEL_FILES:
        return ActionResult(status="error", message="model_not_supported")
    models_dir = str(settings.get("models_dir", "")).strip() or None
    model_url = _download_url_for_model(settings, model_id)
    file_name = _MODEL_FILES.get(model_id, "")
    job_id = _start_download_job(model_id, models_dir, model_url)
    return ActionResult(
        status="accepted",
        message="download_started",
        job_id=job_id,
        data={"model_id": model_id, "file": file_name},
    )


def action_remove_model(settings: dict, params: dict) -> ActionResult:
    model_id = str(params.get("model_id", "")).strip()
    if model_id not in _MODEL_FILES:
        return ActionResult(status="error", message="model_not_supported")
    path = _resolve_model_path(model_id, str(settings.get("models_dir", "")).strip() or None)
    data: dict[str, object] = {"model_id": model_id, "file": path.name}
    if not path.exists():
        refreshed = action_list_models(settings, {})
        if isinstance(refreshed.data, dict):
            data.update(refreshed.data)
        return ActionResult(status="success", message="model_not_found_for_remove", data=data)
    try:
        path.unlink()
    except Exception as exc:
        return ActionResult(status="error", message=str(exc), data=data)
    refreshed = action_list_models(settings, {})
    if isinstance(refreshed.data, dict):
        data.update(refreshed.data)
    return ActionResult(status="success", message="model_removed", data=data)


def _display_model_name(model_id: str) -> str:
    labels = {
        "tiny": "Whisper Tiny",
        "base": "Whisper Base",
        "small": "Whisper Small",
        "small-q8_0": "Whisper Small Q8_0",
        "medium": "Whisper Medium",
        "medium-q8_0": "Whisper Medium Q8_0",
        "large-v3-turbo": "Whisper Large v3 Turbo",
        "large-v3-turbo-q5_0": "Whisper Large v3 Turbo Q5_0",
        "large-v3-turbo-q8_0": "Whisper Large v3 Turbo Q8_0",
        "large-v3": "Whisper Large v3",
        "large-v3-q5_0": "Whisper Large v3 Q5_0",
    }
    return labels.get(str(model_id or "").strip(), str(model_id or "").strip())


def _download_url_for_model(settings: dict, model_id: str) -> str | None:
    raw_models = settings.get("models")
    if isinstance(raw_models, list):
        for row in raw_models:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("model_id", "") or row.get("id", "")).strip()
            if row_id != model_id:
                continue
            url = str(row.get("download_url", "") or "").strip()
            if url:
                return url
            break
    return _default_model_url(model_id) or None


def action_cancel_download(settings: dict, params: dict) -> ActionResult:
    job_id = str(params.get("job_id", "")).strip()
    if not job_id:
        return ActionResult(status="error", message="job_id_missing")
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not isinstance(job, dict):
            return ActionResult(status="error", message="job_not_found")
        cancel_event = job.get("cancel_event")
        if not isinstance(cancel_event, threading.Event):
            return ActionResult(status="error", message="job_not_cancellable")
        status = str(job.get("status", "") or "").strip().lower()
        if status in {"success", "error", "failed", "cancelled"}:
            return ActionResult(status="success", message="job_already_finished", data={"job_id": job_id})
        cancel_event.set()
        job["message"] = "cancelling"
        job["updated_at"] = _now_iso()
    return ActionResult(status="success", message="cancel_requested", data={"job_id": job_id})


def job_provider() -> dict:
    return {"get_status": _get_job_status}


def _start_download_job(model_id: str, models_dir: str | None, model_url: str | None) -> str:
    job_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    download_impl = download_model
    with _JOB_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0.0,
            "message": "queued",
            "updated_at": _now_iso(),
            "cancel_event": cancel_event,
            "model_id": str(model_id or "").strip(),
        }

    def _worker() -> None:
        _update_job(job_id, status="running", progress=0.0, message="downloading")
        try:
            target = _resolve_model_path(model_id, models_dir)
            if target.exists() and target.is_file():
                _update_job(
                    job_id,
                    status="success",
                    progress=1.0,
                    message="already_downloaded",
                    path=str(target),
                )
                return

            def _progress(percent: int) -> None:
                if cancel_event.is_set():
                    raise RuntimeError("download_cancelled")
                try:
                    normalized = max(0.0, min(1.0, float(percent) / 100.0))
                except Exception:
                    normalized = 0.0
                _update_job(job_id, status="running", progress=normalized, message="downloading")

            path = download_impl(model_id, models_dir, model_url, progress_cb=_progress)
            if cancel_event.is_set():
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass
                _update_job(job_id, status="cancelled", message="download_cancelled")
                return
            _update_job(
                job_id,
                status="success",
                progress=1.0,
                message="downloaded",
                path=str(path),
            )
        except Exception as exc:
            if cancel_event.is_set() or "download_cancelled" in str(exc):
                target = _resolve_model_path(model_id, models_dir)
                try:
                    target.unlink(missing_ok=True)
                except Exception:
                    pass
                _update_job(job_id, status="cancelled", message="download_cancelled")
                return
            _update_job(job_id, status="error", message=str(exc) or "download_failed")

    threading.Thread(target=_worker, name=f"aimn.whisper.download:{model_id}", daemon=True).start()
    return job_id


def _get_job_status(job_id: str) -> dict | None:
    with _JOB_LOCK:
        status = _JOBS.get(str(job_id or "").strip())
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
    raw_models = settings.get("models")
    raw_model_rows: list[dict] = raw_models if isinstance(raw_models, list) else []
    existing = {str(entry.get("model_id")): entry for entry in raw_model_rows if isinstance(entry, dict)}
    models: list[dict] = []
    updated = False
    for model_id, filename in _MODEL_FILES.items():
        entry = existing.get(model_id)
        if not entry:
            models.append({"model_id": model_id, "file": filename, "enabled": False, "status": ""})
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

    if "suppress_nst" not in payload:
        payload["suppress_nst"] = True
        updated = True
    if "no_context" not in payload:
        payload["no_context"] = True
        updated = True
    if "best_of" not in payload:
        payload["best_of"] = 5
        updated = True
    if "beam_size" not in payload:
        payload["beam_size"] = 5
        updated = True
    if "entropy_thold" not in payload:
        payload["entropy_thold"] = 2.4
        updated = True
    if "logprob_thold" not in payload:
        payload["logprob_thold"] = -1.0
        updated = True
    if "no_speech_thold" not in payload:
        payload["no_speech_thold"] = 0.6
        updated = True
    if "temperature" not in payload:
        payload["temperature"] = 0.0
        updated = True
    if "temperature_inc" not in payload:
        payload["temperature_inc"] = 0.2
        updated = True
    if "no_fallback" not in payload:
        payload["no_fallback"] = False
        updated = True

    if "strip_nonspeech_tags" not in payload:
        payload["strip_nonspeech_tags"] = True
        updated = True
    if "nonspeech_tag_regex" not in payload:
        payload["nonspeech_tag_regex"] = _DEFAULT_NONSPEECH_TAG_REGEX
        updated = True
    if "stuck_detector_enabled" not in payload:
        payload["stuck_detector_enabled"] = True
        updated = True
    if "stuck_min_run" not in payload:
        payload["stuck_min_run"] = 50
        updated = True
    if "stuck_action" not in payload:
        payload["stuck_action"] = "truncate"
        updated = True

    if updated or raw_models is None:
        payload["models"] = models
        ctx.set_settings(payload, secret_fields=[])
