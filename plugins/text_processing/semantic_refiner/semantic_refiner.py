from __future__ import annotations

import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from huggingface_hub import snapshot_download

from aimn.plugins.interfaces import (
    KIND_EDITED,
    ActionDescriptor,
    ActionResult,
    ArtifactSchema,
    HookContext,
    PluginOutput,
    PluginResult,
)
from plugins.text_processing import utils

_EMBEDDING_MODELS: dict[str, dict[str, str]] = {
    "intfloat/multilingual-e5-small": {
        "product_name": "Multilingual E5 Small",
        "description": "Fast multilingual embedding model for semantic cleanup and keyword extraction.",
        "size_hint": "~0.5 GB",
        "source_url": "https://huggingface.co/intfloat/multilingual-e5-small",
    },
    "intfloat/multilingual-e5-base": {
        "product_name": "Multilingual E5 Base",
        "description": "Stronger multilingual embedding model for semantic cleanup and keyword extraction.",
        "size_hint": "~1.1 GB",
        "source_url": "https://huggingface.co/intfloat/multilingual-e5-base",
    },
}

_EN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "next",
    "today",
    "team",
    "users",
}


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(
            KIND_EDITED,
            ArtifactSchema(content_type="text/markdown", user_visible=True),
        )
        ctx.register_artifact_kind(
            "semantic_blocks",
            ArtifactSchema(content_type="application/json", user_visible=True),
        )
        ctx.register_artifact_kind(
            "important_keywords",
            ArtifactSchema(content_type="application/json", user_visible=True),
        )
        ctx.register_hook_handler("postprocess.after_transcribe", self.hook_postprocess, priority=50)
        ctx.register_actions(action_descriptors)

    def hook_postprocess(self, ctx: HookContext) -> PluginResult:
        text = str(ctx.input_text or "").strip()
        if not text:
            return ctx.build_result()

        plugin = SemanticRefiner(
            extract_keywords=_as_bool(ctx.get_setting("extract_keywords", True), default=True),
            min_block_length=_as_int(ctx.get_setting("min_block_length", 100), default=100, min_value=30),
            keyword_limit=_as_int(ctx.get_setting("keyword_limit", 10), default=10, min_value=3),
            similarity_threshold=_as_float(
                ctx.get_setting("semantic_similarity_threshold", 0.72),
                default=0.72,
                min_value=0.3,
                max_value=0.95,
            ),
            model_id=str(
                ctx.get_setting("embeddings_model_id")
                or ctx.get_setting("model_id")
                or "intfloat/multilingual-e5-base"
            ).strip(),
            model_path=str(ctx.get_setting("embeddings_model_path") or ctx.get_setting("model_path") or "").strip(),
            allow_download=_as_bool(
                ctx.get_setting("embeddings_allow_download", ctx.get_setting("allow_download", True)),
                default=True,
            ),
            embeddings_enabled=_as_bool(ctx.get_setting("embeddings_enabled", True), default=True),
        )
        return plugin.run(ctx)


def action_descriptors() -> list[ActionDescriptor]:
    return [
        ActionDescriptor(
            action_id="list_models",
            label="Refresh Models",
            description="Load embedding model catalog and local installation status.",
            params_schema={"fields": []},
            dangerous=False,
            handler=action_list_models,
        ),
        ActionDescriptor(
            action_id="download_model",
            label="Download Model",
            description="Download selected Hugging Face embedding model snapshot.",
            params_schema={"fields": [{"id": "model_id", "type": "string", "required": True}]},
            dangerous=False,
            handler=action_download_model,
        ),
        ActionDescriptor(
            action_id="remove_model",
            label="Remove Model",
            description="Remove selected local embedding model snapshot.",
            params_schema={"fields": [{"id": "model_id", "type": "string", "required": True}]},
            dangerous=True,
            handler=action_remove_model,
        ),
    ]


def action_list_models(settings: dict, _params: dict) -> ActionResult:
    rows = _configured_model_rows(settings)
    models: list[dict[str, object]] = []
    for model_id, meta in _model_catalog(rows).items():
        installed = _model_installed(model_id)
        models.append(
            {
                "model_id": model_id,
                "product_name": str(meta.get("product_name", "") or model_id),
                "description": str(meta.get("description", "") or ""),
                "size_hint": str(meta.get("size_hint", "") or ""),
                "enabled": _model_enabled(rows, model_id),
                "installed": bool(installed),
                "status": "installed" if installed else "",
                "availability_status": "ready" if installed else "needs_setup",
                "source_url": str(meta.get("source_url", "") or f"https://huggingface.co/{model_id}"),
                "download_url": str(meta.get("download_url", "") or f"https://huggingface.co/{model_id}"),
            }
        )
    return ActionResult(status="success", message="models_loaded", data={"models": models})


def action_download_model(settings: dict, params: dict) -> ActionResult:
    model_id = str(params.get("model_id", "") or "").strip()
    if model_id not in _model_catalog(_configured_model_rows(settings)):
        return ActionResult(status="error", message="model_not_supported", data={"model_id": model_id})
    target_root = Path(utils.get_models_dir())
    target_root.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_id, cache_dir=str(target_root))
    refreshed = action_list_models(settings, {})
    data = dict(refreshed.data or {}) if isinstance(refreshed.data, dict) else {}
    data["model_id"] = model_id
    return ActionResult(status="success", message="model_downloaded", data=data)


def action_remove_model(settings: dict, params: dict) -> ActionResult:
    model_id = str(params.get("model_id", "") or "").strip()
    if not model_id:
        return ActionResult(status="error", message="model_id_missing")
    removed = False
    for path in _model_cache_paths(model_id):
        try:
            if path.is_dir():
                shutil.rmtree(path)
                removed = True
            elif path.exists():
                path.unlink()
                removed = True
        except Exception as exc:
            return ActionResult(status="error", message=str(exc), data={"model_id": model_id})
    refreshed = action_list_models(settings, {})
    data = dict(refreshed.data or {}) if isinstance(refreshed.data, dict) else {}
    data["model_id"] = model_id
    return ActionResult(
        status="success",
        message="model_removed" if removed else "model_not_found_for_remove",
        data=data,
    )


def _configured_model_rows(settings: dict) -> list[dict]:
    raw = settings.get("models") if isinstance(settings, dict) else None
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _model_catalog(rows: list[dict]) -> dict[str, dict[str, str]]:
    catalog = {model_id: dict(meta) for model_id, meta in _EMBEDDING_MODELS.items()}
    for row in rows:
        model_id = str(row.get("model_id", "") or row.get("id", "")).strip()
        if not model_id:
            continue
        merged = dict(catalog.get(model_id, {}))
        merged.update(
            {
                "product_name": str(row.get("product_name", "") or row.get("name", "") or merged.get("product_name", "") or model_id),
                "description": str(row.get("description", "") or merged.get("description", "")),
                "size_hint": str(row.get("size_hint", "") or merged.get("size_hint", "")),
                "source_url": str(row.get("source_url", "") or merged.get("source_url", "") or f"https://huggingface.co/{model_id}"),
                "download_url": str(row.get("download_url", "") or merged.get("download_url", "") or f"https://huggingface.co/{model_id}"),
            }
        )
        catalog[model_id] = merged
    return catalog


def _model_enabled(rows: list[dict], model_id: str) -> bool:
    for row in rows:
        if str(row.get("model_id", "") or row.get("id", "")).strip() == model_id:
            return bool(row.get("enabled", False))
    return False


def _model_cache_paths(model_id: str) -> list[Path]:
    root = Path(utils.get_models_dir())
    hf_slug = str(model_id or "").replace("/", "--")
    human_slug = str(model_id or "").replace("/", "_")
    return [
        root / f"models--{hf_slug}",
        root / human_slug,
        root / str(model_id or ""),
    ]


def _model_installed(model_id: str) -> bool:
    for path in _model_cache_paths(model_id):
        if not path.exists():
            continue
        if (path / "config.json").exists():
            return True
        snapshots = path / "snapshots"
        if snapshots.exists() and any((item / "config.json").exists() for item in snapshots.iterdir() if item.is_dir()):
            return True
    return False


class SemanticRefiner:
    def __init__(
        self,
        *,
        extract_keywords: bool,
        min_block_length: int,
        keyword_limit: int,
        similarity_threshold: float,
        model_id: str,
        model_path: str,
        allow_download: bool,
        embeddings_enabled: bool,
    ) -> None:
        self.extract_keywords = extract_keywords
        self.min_block_length = min_block_length
        self.keyword_limit = keyword_limit
        self.similarity_threshold = similarity_threshold
        self.model_id = str(model_id or "").strip()
        self.model_path = str(model_path or "").strip()
        self.allow_download = bool(allow_download)
        self.embeddings_enabled = bool(embeddings_enabled)

    def run(self, ctx: HookContext) -> PluginResult:
        cleaned_text = self._clean_text(str(ctx.input_text or ""))
        if not cleaned_text:
            return PluginResult(outputs=[], warnings=["semantic_refiner_empty_input"])

        warnings: list[str] = []
        model = self._load_model(ctx)
        if self.embeddings_enabled and self.model_id and model is None:
            warnings.append(f"semantic_refiner_model_missing:{self.model_id}")
            status = utils.get_last_sentence_transformer_status()
            if status and status not in {"unknown", "ready", "model_missing"}:
                warnings.append(f"semantic_refiner_{status}:{self.model_id}")
            detail = utils.get_last_sentence_transformer_error_detail()
            if detail:
                warnings.append(f"semantic_refiner_model_error_detail:{detail}")

        sentences = [item for item in utils.split_sentences(cleaned_text) if item.strip()]
        blocks = self._extract_blocks(sentences, cleaned_text, model)
        keywords = self._extract_keywords(cleaned_text, blocks, model) if self.extract_keywords else []
        structured_markdown = self._render_structured_transcript(blocks, cleaned_text)

        outputs = [
            PluginOutput(
                kind=KIND_EDITED,
                content=structured_markdown,
                content_type="text/markdown",
                user_visible=True,
            ),
            PluginOutput(
                kind="semantic_blocks",
                content=json.dumps(blocks, ensure_ascii=False, indent=2),
                content_type="application/json",
                user_visible=True,
            ),
            PluginOutput(
                kind="important_keywords",
                content=json.dumps(keywords, ensure_ascii=False, indent=2),
                content_type="application/json",
                user_visible=True,
            ),
        ]
        return PluginResult(outputs=outputs, warnings=warnings)

    def _render_structured_transcript(self, blocks: list[dict[str, Any]], fallback_text: str) -> str:
        if not blocks:
            return f"# Structured Transcript\n\n{fallback_text.strip()}\n"
        lines = ["# Structured Transcript", ""]
        for index, block in enumerate(blocks, start=1):
            title = str(block.get("title", "") or "").strip() or f"Block {index}"
            content = str(block.get("content", "") or "").strip()
            keywords = block.get("keywords") if isinstance(block.get("keywords"), list) else []
            lines.append(f"## Block {index}. {title}")
            if keywords:
                lines.append(f"_Focus: {', '.join(str(item).strip() for item in keywords[:5] if str(item).strip())}_")
            lines.append("")
            lines.extend(self._paragraphize_block(content))
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _paragraphize_block(self, content: str) -> list[str]:
        sentences = [item.strip() for item in utils.split_sentences(content) if item.strip()]
        if not sentences:
            return [content.strip()] if content.strip() else []
        paragraphs: list[str] = []
        current: list[str] = []
        current_len = 0
        for sentence in sentences:
            current.append(sentence)
            current_len += len(sentence)
            if current_len >= max(140, self.min_block_length):
                paragraphs.append(" ".join(current).strip())
                current = []
                current_len = 0
        if current:
            paragraphs.append(" ".join(current).strip())
        return paragraphs

    def _load_model(self, ctx: HookContext):
        if not self.embeddings_enabled or not self.model_id:
            return None
        if self.allow_download:
            ctx.notice(
                f"Подождите: загружается embeddings-модель {self.model_id}. После загрузки пайплайн продолжится автоматически."
            )
        model = utils.try_sentence_transformer(
            self.model_id,
            allow_download=self.allow_download,
            model_path=self.model_path or None,
            progress_callback=ctx.progress_callback,
        )
        if model and self.allow_download:
            ctx.notice(f"Embeddings-модель {self.model_id} готова. Продолжаю обработку.")
        return model

    def _clean_text(self, text: str) -> str:
        value = utils.clean_text_deep(text or "")
        value = re.sub(r"(?i)\b(?:эээ|ээ|эм|мм+)\b", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(
            r"(^|[.!?]\s+)([a-zа-яё])",
            lambda match: match.group(1) + match.group(2).upper(),
            value,
            flags=re.IGNORECASE,
        )
        return value

    def _extract_blocks(self, sentences: list[str], text: str, model) -> list[dict[str, Any]]:
        if not sentences:
            return []
        if model:
            vectors = self._encode_rows(model, sentences)
            if vectors:
                return self._semantic_blocks(sentences, vectors)
        return self._heuristic_blocks(sentences, text)

    def _semantic_blocks(self, sentences: list[str], vectors: list[list[float]]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        current_sentences: list[str] = []
        current_vectors: list[list[float]] = []
        for sentence, vector in zip(sentences, vectors, strict=False):
            normalized = _normalize_vector(vector)
            if not normalized:
                continue
            if current_sentences:
                similarity = _cosine_similarity(normalized, _average_vector(current_vectors))
                current_length = len(" ".join(current_sentences))
                if similarity < self.similarity_threshold and current_length >= self.min_block_length:
                    blocks.append(self._build_block(current_sentences, current_vectors))
                    current_sentences = []
                    current_vectors = []
            current_sentences.append(sentence)
            current_vectors.append(normalized)
        if current_sentences:
            blocks.append(self._build_block(current_sentences, current_vectors))
        return blocks or self._heuristic_blocks(sentences, " ".join(sentences))

    def _heuristic_blocks(self, sentences: list[str], text: str) -> list[dict[str, Any]]:
        if not sentences:
            return []
        blocks: list[dict[str, Any]] = []
        current: list[str] = []
        current_length = 0
        for sentence in sentences:
            current.append(sentence)
            current_length += len(sentence)
            if current_length >= self.min_block_length:
                blocks.append(self._build_block(current, []))
                current = []
                current_length = 0
        if current:
            blocks.append(self._build_block(current, []))
        if blocks:
            return blocks
        return [
            {
                "title": utils.generate_topic_name(text),
                "content": text.strip(),
                "sentence_count": len(sentences),
                "keywords": self._heuristic_keywords(text, limit=min(5, self.keyword_limit)),
            }
        ]

    def _build_block(self, sentences: list[str], vectors: list[list[float]]) -> dict[str, Any]:
        content = " ".join(item.strip() for item in sentences if item.strip()).strip()
        return {
            "title": utils.generate_topic_name(content),
            "content": content,
            "sentence_count": len(sentences),
            "keywords": self._keywords_for_block(content, vectors),
        }

    def _keywords_for_block(self, text: str, vectors: list[list[float]]) -> list[str]:
        candidates = self._candidate_keywords(text)
        if not candidates:
            return []
        if not vectors:
            return candidates[: min(5, self.keyword_limit)]
        ranked = candidates
        return ranked[: min(5, self.keyword_limit)] or candidates[: min(5, self.keyword_limit)]

    def _extract_keywords(self, text: str, blocks: list[dict[str, Any]], model) -> list[str]:
        candidates = self._candidate_keywords(text)
        if not candidates:
            return []
        priority_entities = self._priority_entities(text)
        if not model or not blocks:
            return _merge_unique(priority_entities, self._heuristic_keywords(text, limit=self.keyword_limit))[
                : self.keyword_limit
            ]
        block_centroids: list[list[float]] = []
        for block in blocks:
            block_text = str(block.get("content", "")).strip()
            if not block_text:
                continue
            vectors = self._encode_rows(model, [block_text])
            if vectors:
                block_centroids.append(_normalize_vector(vectors[0]))
        if not block_centroids:
            return _merge_unique(priority_entities, self._heuristic_keywords(text, limit=self.keyword_limit))[
                : self.keyword_limit
            ]
        centroid = _average_vector(block_centroids)
        ranked = self._rank_candidates_with_embeddings(model, candidates, centroid)
        merged = _merge_unique(priority_entities, ranked)
        if merged:
            return merged[: self.keyword_limit]
        return self._heuristic_keywords(text, limit=self.keyword_limit)

    def _rank_candidates_with_embeddings(self, model, candidates: list[str], centroid: list[float]) -> list[str]:
        if not candidates or not centroid:
            return candidates
        candidate_vectors = self._encode_rows(model, candidates)
        scored: list[tuple[float, int, str]] = []
        for index, (candidate, vector) in enumerate(zip(candidates, candidate_vectors, strict=False)):
            normalized = _normalize_vector(vector)
            if not normalized:
                continue
            score = _cosine_similarity(normalized, centroid) + (0.02 * max(0, len(candidate.split()) - 1))
            if candidate[:1].isupper():
                score += 0.12
            if " " in candidate and all(part[:1].isupper() for part in candidate.split() if part):
                score += 0.05
            scored.append((score, -index, candidate))
        scored.sort(reverse=True)
        return [item[2] for item in scored]

    def _candidate_keywords(self, text: str) -> list[str]:
        tokens = utils.tokenize(text)
        stops = utils.stopwords_ru()
        filtered = [item for item in tokens if item not in stops and item not in _EN_STOPWORDS and len(item) >= 4]
        counts = Counter(filtered)
        candidates: list[str] = []
        seen: set[str] = set()

        for phrase in self._titlecase_candidates(text):
            normalized = phrase.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(phrase)

        for a, b in zip(tokens, tokens[1:], strict=False):
            if a in stops or b in stops or a in _EN_STOPWORDS or b in _EN_STOPWORDS:
                continue
            if len(a) < 4 or len(b) < 4:
                continue
            phrase = f"{a} {b}"
            normalized = phrase.casefold()
            if normalized in seen:
                continue
            if counts.get(a, 0) + counts.get(b, 0) < 2:
                continue
            seen.add(normalized)
            candidates.append(phrase)

        for token, _count in counts.most_common(max(self.keyword_limit * 2, 12)):
            normalized = token.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(token)
        return candidates[: max(self.keyword_limit * 3, 15)]

    def _titlecase_candidates(self, text: str) -> list[str]:
        raw = re.findall(r"\b(?:[A-ZА-ЯЁ][\w-]{2,})(?:\s+[A-ZА-ЯЁ][\w-]{2,}){0,2}\b", text or "")
        ordered: list[str] = []
        seen: set[str] = set()
        for item in raw:
            normalized_token = item.casefold()
            if normalized_token in _EN_STOPWORDS:
                continue
            normalized = item.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(item)
        return ordered

    def _priority_entities(self, text: str) -> list[str]:
        ordered = []
        for item in self._titlecase_candidates(text):
            if item.casefold() in _EN_STOPWORDS:
                continue
            ordered.append(item)
        return ordered[: min(4, self.keyword_limit)]

    def _heuristic_keywords(self, text: str, *, limit: int) -> list[str]:
        candidates = self._candidate_keywords(text)
        return candidates[:limit]

    @staticmethod
    def _encode_rows(model, rows: list[str]) -> list[list[float]]:
        try:
            vectors = model.encode(rows)
        except Exception:
            return []
        if hasattr(vectors, "tolist"):
            vectors = vectors.tolist()
        result: list[list[float]] = []
        for row in vectors or []:
            if hasattr(row, "tolist"):
                row = row.tolist()
            if not isinstance(row, list):
                continue
            try:
                result.append([float(item) for item in row])
            except Exception:
                continue
        return result


def _normalize_vector(vector: list[float]) -> list[float]:
    if not vector:
        return []
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        return []
    return [value / norm for value in vector]


def _average_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    width = len(vectors[0])
    if width <= 0:
        return []
    acc = [0.0] * width
    count = 0
    for vector in vectors:
        if len(vector) != width:
            continue
        count += 1
        for index, value in enumerate(vector):
            acc[index] += value
    if count <= 0:
        return []
    return _normalize_vector([value / count for value in acc])


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False))


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (first, second):
        for item in source:
            value = str(item or "").strip()
            if not value:
                continue
            marker = value.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            merged.append(value)
    return merged


def _as_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(value: Any, *, default: int, min_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, parsed)


def _as_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))
