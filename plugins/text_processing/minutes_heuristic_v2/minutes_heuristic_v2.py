from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher
from typing import Any, Iterable

from aimn.plugins.interfaces import (
    KIND_ASR_SEGMENTS_JSON,
    KIND_EDITED,
    KIND_SEGMENTS,
    HookContext,
    PluginOutput,
    PluginResult,
)
from plugins.text_processing import utils


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _fmt_ts(seconds: float | int | None) -> str:
    total = max(0, int(float(seconds or 0)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_asr_segments(content: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(content)
    except Exception:
        return []
    if isinstance(payload, dict):
        payload = payload.get("segments", [])
    if not isinstance(payload, list):
        return []
    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        text = _norm(item.get("text", ""))
        if not text:
            continue
        if "start_ms" in item or "end_ms" in item:
            start = float(item.get("start_ms", 0.0) or 0.0) / 1000.0
            end = float(item.get("end_ms", start * 1000.0) or start * 1000.0) / 1000.0
        else:
            start = float(item.get("start", 0.0) or 0.0)
            end = float(item.get("end", start) or start)
        out.append({"start": start, "end": max(end, start), "text": text})
    out.sort(key=lambda x: (x["start"], x["end"]))
    return out


def _dedupe(items: Iterable[str], *, threshold: float = 0.9) -> list[str]:
    out: list[str] = []
    for item in items:
        value = _norm(item)
        if not value:
            continue
        if any(SequenceMatcher(None, value.lower(), existing.lower()).ratio() >= threshold for existing in out):
            continue
        out.append(value)
    return out


def _truncate(text: str, limit: int) -> str:
    value = _norm(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _join_sentences(sentences: Iterable[str], *, limit: int) -> str:
    return _truncate(" ".join(_norm(item) for item in sentences if _norm(item)), limit)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except Exception:
        return default


def _parse_model_list(raw: str, *, max_items: int) -> list[str]:
    parts = re.split(r"[;,|\n]+", str(raw or ""))
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = part.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= max_items:
            break
    return out


def _extract_action_items(
    segments: list[dict[str, Any]],
    *,
    limit: int,
    max_chars: int,
) -> list[str]:
    hits: list[str] = []
    for seg in segments:
        text = _norm(seg.get("text", ""))
        if not text:
            continue
        if "?" in text:
            continue
        if utils.extract_actions(text):
            hits.append(f"{_truncate(text, max_chars)} ({_fmt_ts(seg.get('start'))})")
            continue
        if re.search(
            r"\b(?:todo|action item|please|need to|must|should|follow up|owner|deadline)\b",
            text,
            re.I,
        ):
            hits.append(f"{_truncate(text, max_chars)} ({_fmt_ts(seg.get('start'))})")
    return _dedupe(hits)[:limit]


def _extract_decisions(text: str, *, limit: int, max_chars: int) -> list[str]:
    pat = re.compile(r"\b(?:decided|agreed|approved|picked|selected|resolved)\b", re.I)
    items = [sentence for sentence in utils.split_sentences(text) if pat.search(sentence)]
    return [_truncate(item, max_chars) for item in _dedupe(items)[:limit]]


def _extract_sentence_windows(sentences: list[str], *, window_size: int = 3, min_chars: int = 90) -> list[list[str]]:
    items = [_norm(item) for item in sentences if _norm(item)]
    if not items:
        return []
    windows: list[list[str]] = []
    for index in range(len(items)):
        chunk = items[index : index + window_size]
        if len(" ".join(chunk)) < min_chars and index > 0:
            chunk = items[max(0, index - 1) : min(len(items), index + window_size)]
        if chunk:
            windows.append(chunk)
    return windows


def _normalize_vector(vector: list[float]) -> list[float]:
    if not vector:
        return []
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        return []
    return [value / norm for value in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _cluster_windows(model, windows: list[list[str]], *, similarity_threshold: float) -> list[list[str]]:
    if not model or not windows:
        return []
    window_texts = [_join_sentences(chunk, limit=420) for chunk in windows]
    try:
        vectors = model.encode(window_texts)
    except Exception:
        return []
    if hasattr(vectors, "tolist"):
        vectors = vectors.tolist()

    normalized: list[list[float]] = []
    for row in vectors or []:
        if hasattr(row, "tolist"):
            row = row.tolist()
        if not isinstance(row, list):
            continue
        normalized.append(_normalize_vector([float(item) for item in row]))
    if len(normalized) != len(window_texts):
        return []

    clusters: list[dict[str, Any]] = []
    for index, (chunk, vector) in enumerate(zip(windows, normalized)):
        if not vector:
            continue
        best_index = -1
        best_score = -1.0
        for cluster_index, cluster in enumerate(clusters):
            score = _cosine_similarity(vector, cluster["centroid"])
            if score > best_score:
                best_score = score
                best_index = cluster_index
        if best_index >= 0 and best_score >= similarity_threshold:
            cluster = clusters[best_index]
            cluster["chunks"].append(chunk)
            cluster["positions"].append(index)
            count = len(cluster["vectors"]) + 1
            cluster["centroid"] = [
                ((cluster["centroid"][i] * (count - 1)) + vector[i]) / count for i in range(len(vector))
            ]
            cluster["vectors"].append(vector)
            continue
        clusters.append(
            {
                "chunks": [chunk],
                "positions": [index],
                "vectors": [vector],
                "centroid": list(vector),
            }
        )

    ranked = sorted(
        clusters,
        key=lambda item: (len(item["chunks"]), -min(item["positions"])),
        reverse=True,
    )
    ranked.sort(key=lambda item: min(item["positions"]))

    groups: list[list[str]] = []
    for cluster in ranked:
        merged: list[str] = []
        for chunk in cluster["chunks"]:
            for sentence in chunk:
                value = _norm(sentence)
                if value and value not in merged:
                    merged.append(value)
        if merged:
            groups.append(merged)
    return groups


def _build_discussion_points(
    groups: list[list[str]],
    *,
    limit: int,
    title_chars: int,
    detail_chars: int,
) -> list[str]:
    points: list[str] = []
    for group in groups[:limit]:
        if not group:
            continue
        topic = _truncate(utils.generate_topic_name(" ".join(group)) or "Discussion point", title_chars)
        detail = _join_sentences(group[:2], limit=detail_chars)
        points.append(f"**{topic}.** {detail}" if detail else f"**{topic}.**")
    return _dedupe(points)


_CASCADE_PRESETS = {
    "balanced": {"summary_mode": "hybrid", "actions_mode": "hybrid", "max_summary_bullets": 6},
    "fast": {"summary_mode": "heuristic", "actions_mode": "regex", "max_summary_bullets": 5},
    "quality": {"summary_mode": "ml", "actions_mode": "ml", "max_summary_bullets": 7},
}


class MinutesHeuristicV2Plugin:
    def __init__(self, **kwargs: Any) -> None:
        cascade = str(kwargs.get("cascade", "balanced") or "balanced").strip().lower()
        preset = dict(_CASCADE_PRESETS.get(cascade, _CASCADE_PRESETS["balanced"]))
        preset.update({k: v for k, v in kwargs.items() if v is not None})

        self.max_summary_bullets = _coerce_int(preset.get("max_summary_bullets", 6), 6)
        self.max_action_items = _coerce_int(preset.get("max_action_items", 12), 12)
        self.max_decisions = _coerce_int(preset.get("max_decisions", 8), 8)
        self.max_chars = _coerce_int(preset.get("max_chars", 9000), 9000)
        self.max_bullet_chars = _coerce_int(preset.get("max_bullet_chars", 240), 240)
        self.summary_mode = str(preset.get("summary_mode", "hybrid") or "hybrid").strip().lower()
        self.actions_mode = str(preset.get("actions_mode", "hybrid") or "hybrid").strip().lower()
        self.model_id = str(
            preset.get("model_id")
            or preset.get("embeddings_model_id")
            or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        ).strip()
        self.model_path = str(preset.get("model_path") or preset.get("embeddings_model_path") or "").strip()
        self.embeddings_enabled = _coerce_bool(preset.get("embeddings_enabled", True), True)
        self.allow_download = _coerce_bool(
            preset.get("embeddings_allow_download", preset.get("allow_download", True)),
            True,
        )
        self.compare_enabled = _coerce_bool(preset.get("compare_enabled", False), False)
        self.compare_models_raw = str(preset.get("compare_models", "") or "").strip()
        self.compare_max_models = _coerce_int(preset.get("compare_max_models", 4), 4)

    def _load_model(self, ctx: HookContext, model_id: str):
        if not model_id or not self.embeddings_enabled:
            return None
        model_path = self.model_path if model_id == self.model_id and self.model_path else None
        if self.allow_download:
            ctx.notice(
                f"Please wait: downloading embeddings model {model_id}. Processing will resume automatically."
            )
        model = utils.try_sentence_transformer(
            model_id,
            allow_download=self.allow_download,
            model_path=model_path,
            progress_callback=ctx.progress_callback,
        )
        if model and self.allow_download:
            ctx.notice(f"Embeddings model {model_id} is ready. Continuing processing.")
        return model

    def _extract_summary_ml(self, model, sentences: list[str]) -> list[str]:
        groups = _cluster_windows(
            model,
            _extract_sentence_windows(sentences, window_size=3),
            similarity_threshold=0.58,
        )
        return _build_discussion_points(
            groups,
            limit=max(3, self.max_summary_bullets),
            title_chars=72,
            detail_chars=self.max_bullet_chars,
        )

    def _extract_summary_heuristic(self, sentences: list[str]) -> list[str]:
        groups = _extract_sentence_windows(sentences, window_size=3)
        return _build_discussion_points(
            groups,
            limit=max(3, self.max_summary_bullets),
            title_chars=72,
            detail_chars=self.max_bullet_chars,
        )

    def run(self, ctx: HookContext) -> PluginResult:
        warnings: list[str] = []
        model_ids = [self.model_id] if self.model_id else []
        if self.compare_enabled and self.compare_models_raw:
            model_ids = _parse_model_list(self.compare_models_raw, max_items=self.compare_max_models) or model_ids
        if not model_ids:
            model_ids = [""]

        segments: list[dict[str, Any]] = []
        artifact = ctx.get_artifact(KIND_SEGMENTS) or ctx.get_artifact(KIND_ASR_SEGMENTS_JSON)
        if artifact and artifact.content:
            segments = _parse_asr_segments(artifact.content)
            if not segments:
                warnings.append("minutes_heuristic_v2_segments_parse_failed")
        else:
            warnings.append("minutes_heuristic_v2_segments_missing")

        full_text = " ".join(_norm(item.get("text", "")) for item in segments) if segments else _norm(ctx.input_text)
        if not full_text:
            warnings.append("minutes_heuristic_v2_empty_input")
            content = "\n".join(
                [
                    "# Meeting Summary",
                    "",
                    "## Summary",
                    "_No transcript text available._",
                    "",
                    "## Action Items",
                    "_No action items detected._",
                    "",
                    "## Decisions",
                    "_No decisions detected._",
                    "",
                ]
            )
            return PluginResult(
                outputs=[PluginOutput(kind=KIND_EDITED, content=content, content_type="text/markdown")],
                warnings=warnings,
            )

        topic = utils.generate_topic_name(full_text) or "Meeting Summary"
        summary_candidates = [item for item in utils.split_sentences(full_text) if len(_norm(item)) >= 20]
        markers: list[str] = []
        out: list[str] = [f"# {topic}", ""]

        if len(model_ids) > 1:
            out.extend([f"_Compare mode: {', '.join([item for item in model_ids if item])}_", ""])
        if not segments:
            markers.append("segments_missing")

        for mid in model_ids:
            model = None
            if mid and self.summary_mode in {"ml", "hybrid"}:
                model = self._load_model(ctx, mid)
            if mid and not model and self.summary_mode in {"ml", "hybrid"}:
                status = utils.get_last_sentence_transformer_status()
                warnings.append(f"minutes_heuristic_v2_model_missing:{mid}")
                if status and status not in {"unknown", "ready", "model_missing"}:
                    warnings.append(f"minutes_heuristic_v2_{status}:{mid}")
                detail = utils.get_last_sentence_transformer_error_detail()
                if detail:
                    warnings.append(f"minutes_heuristic_v2_model_error_detail:{detail}")
                markers.extend(["heuristic_fallback", f"model_missing:{mid}"])

            if len(model_ids) > 1:
                out.extend([f"## Model: {mid or 'heuristic'}", ""])

            if self.summary_mode == "ml" and model:
                summary = self._extract_summary_ml(model, summary_candidates)
            elif self.summary_mode == "hybrid" and model:
                summary = self._extract_summary_ml(model, summary_candidates) or self._extract_summary_heuristic(
                    summary_candidates
                )
            else:
                summary = self._extract_summary_heuristic(summary_candidates)

            actions = _extract_action_items(
                segments if segments else [{"start": 0.0, "text": item} for item in summary_candidates],
                limit=self.max_action_items,
                max_chars=self.max_bullet_chars,
            )
            decisions = _extract_decisions(
                full_text,
                limit=self.max_decisions,
                max_chars=self.max_bullet_chars,
            )

            out.extend(["## Summary"])
            if summary:
                out.extend([f"- {item}" for item in summary[: self.max_summary_bullets]])
            else:
                out.append("_No summary available._")
            out.append("")

            out.extend(["## Action Items"])
            if actions:
                out.extend([f"- [ ] {item}" for item in actions])
            else:
                out.append("_No action items detected._")
            out.append("")

            out.extend(["## Decisions"])
            if decisions:
                out.extend([f"- {item}" for item in decisions])
            else:
                out.append("_No decisions detected._")
            out.append("")

        content = ("\n".join(out).strip() + "\n")
        if markers:
            content = utils.add_hidden_markers(content, markers)
        if len(content) > self.max_chars:
            warnings.append("minutes_heuristic_v2_truncated")
            content = content[: self.max_chars - 2].rstrip() + "\n"

        return PluginResult(
            outputs=[PluginOutput(kind=KIND_EDITED, content=content, content_type="text/markdown")],
            warnings=warnings,
        )


class Plugin:
    def register(self, ctx) -> None:
        from aimn.plugins.api import ArtifactSchema

        ctx.register_artifact_kind(KIND_EDITED, ArtifactSchema(content_type="text/markdown", user_visible=True))
        ctx.register_hook_handler("postprocess.after_transcribe", hook_postprocess, mode="optional", priority=100)
        ctx.register_hook_handler("derive.after_postprocess", hook_postprocess, mode="optional", priority=100)


def hook_postprocess(ctx: HookContext) -> PluginResult:
    plugin = MinutesHeuristicV2Plugin(**(ctx.plugin_config or {}))
    return plugin.run(ctx)
