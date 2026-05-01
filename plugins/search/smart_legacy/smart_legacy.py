from __future__ import annotations

import re

from aimn.plugins.interfaces import ActionDescriptor, ActionResult

from ..search_index import SqliteFtsSearchIndex, resolve_app_root

_PLUGIN_ID = "search.smart"
_INDEX_RELPATH = "search/simple_index.sqlite"
_EMPTY_RESULT_REBUILD_ONCE_KEYS: set[str] = set()
_STOPWORDS: set[str] = {
    "и",
    "в",
    "во",
    "на",
    "по",
    "к",
    "ко",
    "с",
    "со",
    "у",
    "о",
    "об",
    "от",
    "до",
    "за",
    "для",
    "из",
    "или",
    "а",
    "но",
    "не",
    "что",
    "это",
    "the",
    "and",
    "or",
    "to",
    "in",
    "on",
    "for",
    "of",
}
_COMMON_RU_ENDINGS: tuple[str, ...] = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "иях",
    "ях",
    "ах",
    "ов",
    "ев",
    "ей",
    "ий",
    "ый",
    "ой",
    "ам",
    "ям",
    "ом",
    "ем",
    "ую",
    "юю",
    "ия",
    "ья",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)


def _open_index() -> SqliteFtsSearchIndex:
    return SqliteFtsSearchIndex(app_root=resolve_app_root(), index_relpath=_INDEX_RELPATH)


def _query_tokens(query: str) -> list[str]:
    raw = str(query or "").strip().lower()
    if not raw:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[\w-]+", raw, flags=re.UNICODE):
        value = str(token or "").strip("_-")
        if len(value) < 3 or value in _STOPWORDS or value in seen:
            continue
        seen.add(value)
        tokens.append(value)
    return tokens


def _stem_token(token: str) -> str:
    value = str(token or "").strip().lower()
    if len(value) < 5:
        return value
    for ending in _COMMON_RU_ENDINGS:
        if value.endswith(ending):
            stem = value[: -len(ending)]
            if len(stem) >= 4:
                return stem
    return value


def _build_query_variants(query: str) -> list[str]:
    base = str(query or "").strip()
    if not base:
        return []
    tokens = _query_tokens(base)
    variants: list[str] = [base]
    if tokens:
        variants.append(" ".join(tokens[: min(4, len(tokens))]))
    for token in tokens[:8]:
        variants.append(token)
        if len(token) >= 4:
            variants.append(f"{token}*")
        stem = _stem_token(token)
        if stem and stem != token:
            variants.append(stem)
            if len(stem) >= 4:
                variants.append(f"{stem}*")
    unique: list[str] = []
    seen: set[str] = set()
    for item in variants:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
        if len(unique) >= 12:
            break
    return unique


class Plugin:
    def register(self, ctx) -> None:
        # Smart search consumes the same index as Simple Search for now. No widget.
        ctx.register_actions(_actions)


def _actions() -> list[ActionDescriptor]:
    return [
        ActionDescriptor(
            action_id="search",
            label="Smart search",
            description="Answer with sources (degraded mode: keyword retrieval + grounded summary).",
            params_schema={
                "fields": [
                    {"key": "query", "label": "Query", "type": "string", "required": True},
                    {"key": "meeting_id", "label": "Meeting ID", "type": "string"},
                    {"key": "kind", "label": "Artifact kind", "type": "string"},
                    {"key": "stage_id", "label": "Stage ID", "type": "string"},
                    {"key": "alias", "label": "Alias", "type": "string"},
                    {"key": "limit", "label": "Limit", "type": "number"},
                ]
            },
            handler=_action_search,
        )
    ]


def _query_variants(query: str) -> list[str]:
    return _build_query_variants(str(query or ""))


def _hit_key(hit: object) -> tuple[str, str, str, str, int, int, str]:
    def _safe_int(value: object) -> int:
        try:
            return int(value)
        except Exception:
            return -1

    return (
        str(getattr(hit, "meeting_id", "") or ""),
        str(getattr(hit, "stage_id", "") or ""),
        str(getattr(hit, "alias", "") or ""),
        str(getattr(hit, "kind", "") or ""),
        _safe_int(getattr(hit, "segment_index", -1)),
        _safe_int(getattr(hit, "start_ms", -1)),
        str(getattr(hit, "relpath", "") or ""),
    )


def _rank_hit(hit: object, *, query: str, query_tokens: list[str], variant: str, variant_index: int) -> float:
    text = " ".join(
        [
            str(getattr(hit, "snippet", "") or ""),
            str(getattr(hit, "context", "") or ""),
            str(getattr(hit, "content", "") or ""),
        ]
    ).casefold()
    q = str(query or "").strip().casefold()
    v = str(variant or "").strip().casefold()
    coverage = sum(1 for token in query_tokens if token and token in text)
    exact = 1 if q and q in text else 0
    variant_match = 1 if v and v in text else 0
    # Keep exact matches on top, but do not completely suppress contextual variants.
    return float(coverage * 7 + exact * 4 + variant_match * 4 + max(0, 5 - int(variant_index)))


def _search_smart(
    index: SqliteFtsSearchIndex,
    *,
    query: str,
    meeting_id: str,
    kind: str,
    stage_id: str,
    alias: str,
    limit: int,
) -> list[object]:
    variants = _query_variants(query)
    if not variants:
        return []
    query_tokens = _query_tokens(query)
    buckets: list[list[object]] = []
    for idx, variant in enumerate(variants):
        per_limit = min(200, max(int(limit) * (3 if idx == 0 else 2), 30 if idx == 0 else 16))
        try:
            hits = index.search(
                variant,
                meeting_id=meeting_id,
                kind=kind,
                stage_id=stage_id,
                alias=alias,
                limit=per_limit,
            )
        except Exception:
            buckets.append([])
            continue
        local_seen: set[tuple[str, str, str, str, int, int, str]] = set()
        bucket: list[object] = []
        for hit in hits:
            key = _hit_key(hit)
            if key in local_seen:
                continue
            local_seen.add(key)
            bucket.append(hit)
            if len(bucket) >= 60:
                break
        buckets.append(bucket)

    want = max(1, int(limit))
    caps: list[int] = []
    for idx in range(len(buckets)):
        if idx == 0:
            caps.append(max(1, int(round(want * 0.6))))
        else:
            caps.append(max(1, min(4, int(round(want * 0.25)))))

    merged: list[object] = []
    used: set[tuple[str, str, str, str, int, int, str]] = set()
    taken = [0] * len(buckets)
    pos = [0] * len(buckets)

    changed = True
    while len(merged) < want and changed:
        changed = False
        for idx, bucket in enumerate(buckets):
            if len(merged) >= want:
                break
            if idx != 0 and taken[idx] >= caps[idx]:
                continue
            while pos[idx] < len(bucket):
                hit = bucket[pos[idx]]
                pos[idx] += 1
                key = _hit_key(hit)
                if key in used:
                    continue
                used.add(key)
                merged.append(hit)
                taken[idx] += 1
                changed = True
                break

    if len(merged) >= want:
        return merged[:want]

    ranked: dict[tuple[str, str, str, str, int, int, str], tuple[float, object]] = {}
    for idx, bucket in enumerate(buckets):
        variant = variants[idx] if idx < len(variants) else ""
        for hit in bucket:
            key = _hit_key(hit)
            score = _rank_hit(
                hit,
                query=query,
                query_tokens=query_tokens,
                variant=variant,
                variant_index=idx,
            )
            prev = ranked.get(key)
            if prev is None or score > prev[0]:
                ranked[key] = (score, hit)

    ordered = sorted(ranked.values(), key=lambda pair: pair[0], reverse=True)
    for _score, hit in ordered:
        if len(merged) >= want:
            break
        key = _hit_key(hit)
        if key in used:
            continue
        used.add(key)
        merged.append(hit)
    return merged[:want]


def _action_search(_settings: dict, params: dict) -> ActionResult:
    query = str(params.get("query", "") or "").strip()
    meeting_id = str(params.get("meeting_id", "") or "").strip()
    kind = str(params.get("kind", "") or "").strip()
    stage_id = str(params.get("stage_id", "") or "").strip()
    alias = str(params.get("alias", "") or "").strip()
    limit = params.get("limit", 20)
    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 20
    limit_int = max(1, min(limit_int, 50))

    if not query:
        return ActionResult(status="ok", message="empty_query", data={"query": "", "hits": [], "total": 0})

    index = _open_index()
    try:
        hits = _search_smart(
            index,
            query=query,
            meeting_id=meeting_id,
            kind=kind,
            stage_id=stage_id,
            alias=alias,
            limit=limit_int,
        )
        if not hits and index.document_count() == 0:
            index.rebuild(meeting_id=meeting_id)
            hits = _search_smart(
                index,
                query=query,
                meeting_id=meeting_id,
                kind=kind,
                stage_id=stage_id,
                alias=alias,
                limit=limit_int,
            )
        if not hits:
            rebuild_key = str(meeting_id or "*")
            if rebuild_key not in _EMPTY_RESULT_REBUILD_ONCE_KEYS:
                _EMPTY_RESULT_REBUILD_ONCE_KEYS.add(rebuild_key)
                try:
                    index.rebuild(meeting_id=meeting_id)
                except Exception:
                    pass
                hits = _search_smart(
                    index,
                    query=query,
                    meeting_id=meeting_id,
                    kind=kind,
                    stage_id=stage_id,
                    alias=alias,
                    limit=limit_int,
                )
    except Exception:
        try:
            index.rebuild(meeting_id=meeting_id)
            hits = _search_smart(
                index,
                query=query,
                meeting_id=meeting_id,
                kind=kind,
                stage_id=stage_id,
                alias=alias,
                limit=limit_int,
            )
        except Exception as exc:
            return ActionResult(status="error", message=str(exc))

    # Degraded grounded answer: top snippets only (no LLM, no embeddings).
    bullets = []
    citations = []
    for idx, hit in enumerate(hits[:5]):
        snippet = (hit.snippet or "").strip()
        if snippet:
            bullets.append(f"- {snippet}")
            citations.append(
                {
                    "index": idx,
                    "meeting_id": hit.meeting_id,
                    "stage_id": hit.stage_id,
                    "alias": hit.alias,
                    "kind": hit.kind,
                    "relpath": hit.relpath,
                    "segment_index": hit.segment_index,
                    "start_ms": hit.start_ms,
                }
            )
    answer = "\n".join(bullets) if bullets else "No grounded matches found."

    payload = {
        "query": query,
        "total": len(hits),
        "answer": answer,
        "citations": citations,
        "hits": [
            {
                "meeting_id": hit.meeting_id,
                "alias": hit.alias,
                "stage_id": hit.stage_id,
                "kind": hit.kind,
                "relpath": hit.relpath,
                "snippet": hit.snippet,
                "score": hit.score,
                "segment_index": hit.segment_index,
                "start_ms": hit.start_ms,
                "end_ms": hit.end_ms,
                "content": hit.content,
                "context": str(getattr(hit, "context", "") or ""),
            }
            for hit in hits
        ],
    }
    return ActionResult(status="ok", message="degraded_fts", data=payload)
