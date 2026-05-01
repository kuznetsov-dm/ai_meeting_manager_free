from __future__ import annotations

from aimn.core.search_index import SearchHit, SqliteFtsSearchIndex, resolve_app_root
from aimn.core.search_query import normalize_search_query, query_tokens, query_variants


def _hit_key(hit: SearchHit) -> tuple[str, str, str, str, int, int, str]:
    return (
        str(hit.meeting_id or ""),
        str(hit.stage_id or ""),
        str(hit.alias or ""),
        str(hit.kind or ""),
        int(hit.segment_index if hit.segment_index is not None else -1),
        int(hit.start_ms if hit.start_ms is not None else -1),
        str(hit.relpath or ""),
    )


def _rank_hit(hit: SearchHit, *, query: str, query_tokens_: list[str], variant: str, variant_index: int) -> float:
    text = " ".join([str(hit.snippet or ""), str(hit.context or ""), str(hit.content or "")]).casefold()
    q = str(query or "").strip().casefold()
    v = str(variant or "").strip().casefold()
    coverage = sum(1 for token in query_tokens_ if token and token in text)
    exact = 1 if q and q in text else 0
    variant_match = 1 if v and v in text else 0
    return float(coverage * 7 + exact * 4 + variant_match * 4 + max(0, 5 - int(variant_index)))


class BuiltinSearchService:
    def __init__(self, *, index_relpath: str = "search/simple_index.sqlite") -> None:
        self._index = SqliteFtsSearchIndex(app_root=resolve_app_root(), index_relpath=index_relpath)
        self._rebuild_once_keys: set[str] = set()

    def on_artifact_written(self, *, meeting_id: str, stage_id: str, alias: str, kind: str, relpath: str) -> None:
        self._index.on_artifact_written(meeting_id, stage_id, alias, kind, relpath)

    def search_transcripts(self, query: str, *, limit: int = 50) -> list[SearchHit]:
        q = normalize_search_query(query)
        limit_int = max(1, min(int(limit or 50), 200))
        if not q:
            return []
        hits = self._search_ranked(q, limit=limit_int)
        if hits:
            return hits
        scope = "*"
        if scope not in self._rebuild_once_keys and self._index.document_count() == 0:
            self._rebuild_once_keys.add(scope)
            try:
                self._index.rebuild()
            except Exception:
                return []
            return self._search_ranked(q, limit=limit_int)
        return []

    def _search_ranked(self, query: str, *, limit: int) -> list[SearchHit]:
        q = str(query or "").strip()
        limit_int = max(1, min(int(limit or 50), 200))
        if not q:
            return []
        variants = query_variants(q, include_wildcards=True, max_variants=16)
        if not variants:
            return []
        buckets: list[list[SearchHit]] = []
        for idx, variant in enumerate(variants):
            per_limit = min(200, max(limit_int * (3 if idx == 0 else 2), 30 if idx == 0 else 16))
            hits = self._index.search(variant, kind="transcript", limit=per_limit)
            local_seen: set[tuple[str, str, str, str, int, int, str]] = set()
            bucket: list[SearchHit] = []
            for hit in hits:
                key = _hit_key(hit)
                if key in local_seen:
                    continue
                local_seen.add(key)
                bucket.append(hit)
                if len(bucket) >= 60:
                    break
            buckets.append(bucket)

        want = limit_int
        caps: list[int] = []
        for idx in range(len(buckets)):
            if idx == 0:
                caps.append(max(1, int(round(want * 0.6))))
            else:
                caps.append(max(1, min(4, int(round(want * 0.25)))))

        merged: list[SearchHit] = []
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

        ranked: dict[tuple[str, str, str, str, int, int, str], tuple[float, SearchHit]] = {}
        tokens = query_tokens(q)
        for idx, bucket in enumerate(buckets):
            variant = variants[idx] if idx < len(variants) else ""
            for hit in bucket:
                key = _hit_key(hit)
                score = _rank_hit(hit, query=q, query_tokens_=tokens, variant=variant, variant_index=idx)
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
