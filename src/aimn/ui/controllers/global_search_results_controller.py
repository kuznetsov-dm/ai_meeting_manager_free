from __future__ import annotations

import re
from collections.abc import Sequence

from aimn.core.api import query_variants
from aimn.ui.controllers.transcript_evidence_controller import safe_int


def format_ms_hhmmss(ms: int) -> str:
    value = max(0, safe_int(ms, 0))
    sec = value // 1000
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def truncate_result_text(value: object, *, limit: int) -> str:
    text = str(value or "")
    max_len = max(1, int(limit))
    if len(text) <= max_len:
        return text
    return f"{text[:max_len].rstrip()}..."


class GlobalSearchResultsController:
    @staticmethod
    def dedupe_terms(terms: Sequence[str], *, min_len: int = 1, max_terms: int = 40) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for item in terms:
            value = str(item or "").strip()
            if len(value) < max(1, int(min_len)):
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
            if len(unique) >= max(1, int(max_terms)):
                break
        unique.sort(key=lambda text: len(str(text or "")), reverse=True)
        return unique

    @staticmethod
    def search_terms_from_query(query: str) -> list[str]:
        variants = query_variants(str(query or ""), include_wildcards=False, max_variants=24)
        return GlobalSearchResultsController.dedupe_terms(variants, min_len=2, max_terms=48)

    @staticmethod
    def query_lexemes(query: str) -> list[str]:
        return GlobalSearchResultsController.dedupe_terms(
            re.findall(r"[\w-]+", str(query or ""), flags=re.UNICODE),
            min_len=2,
            max_terms=24,
        )

    @staticmethod
    def marked_terms_from_snippet(snippet: str) -> list[str]:
        value = str(snippet or "")
        if not value:
            return []
        terms: list[str] = []
        for match in re.finditer(r"\[([^\]]+)\]", value):
            token = str(match.group(1) or "").strip()
            if token:
                terms.append(token)
        return GlobalSearchResultsController.dedupe_terms(terms, min_len=1, max_terms=24)

    @staticmethod
    def result_payload_from_hit(hit: dict) -> dict:
        return {
            "meeting_id": str(hit.get("meeting_id", "") or "").strip(),
            "stage_id": str(hit.get("stage_id", "") or "").strip(),
            "alias": str(hit.get("alias", "") or "").strip(),
            "kind": str(hit.get("kind", "") or "").strip(),
            "segment_index": safe_int(hit.get("segment_index"), -1),
            "start_ms": safe_int(hit.get("start_ms"), -1),
        }

    @staticmethod
    def is_missing_text(value: str) -> bool:
        text = str(value or "").strip().lower()
        return text.startswith("missing:")

    @staticmethod
    def normalized_result_content(value: object) -> str:
        raw = str(value or "")
        if not raw.strip():
            return ""
        if GlobalSearchResultsController.is_missing_text(raw):
            return ""
        return raw

    @staticmethod
    def resolve_hit_content(hit: dict) -> str:
        context = GlobalSearchResultsController.normalized_result_content(hit.get("context", ""))
        if context:
            return context
        content = GlobalSearchResultsController.normalized_result_content(hit.get("content", ""))
        if content:
            return content
        return ""

    @staticmethod
    def sentence_window(text: str, terms: Sequence[str]) -> str:
        source = str(text or "").strip()
        if not source:
            return ""
        parts = [p.strip() for p in re.split(r"(?<=[\.\!\?…])\s+|\n+", source) if str(p or "").strip()]
        if not parts:
            return source
        lowered_parts = [part.casefold() for part in parts]
        wanted = [str(t or "").strip().casefold() for t in terms if str(t or "").strip()]
        idx = 0
        for i, part in enumerate(lowered_parts):
            if any(token in part for token in wanted):
                idx = i
                break
        left = max(0, idx - 1)
        right = min(len(parts), idx + 2)
        window = [parts[i] for i in range(left, right) if str(parts[i] or "").strip()]
        return " ".join(window).strip()

    @staticmethod
    def result_excerpt_from_hit(hit: dict, *, terms: Sequence[str] | None = None) -> str:
        content = GlobalSearchResultsController.resolve_hit_content(hit)
        if content:
            around = GlobalSearchResultsController.sentence_window(content, terms or [])
            if around:
                return around
            return content
        snippet = str(hit.get("snippet", "") or "").replace("[", "").replace("]", "").strip()
        if snippet:
            return snippet
        return ""

    @staticmethod
    def build_rows(query: str, hits: list[dict]) -> list[dict]:
        q = str(query or "").strip()
        rows: list[dict] = []
        seen_anchor: set[tuple[str, str, str, str, int, int]] = set()
        seen_excerpt_scope: set[tuple[str, str, str, str, str]] = set()
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            payload = GlobalSearchResultsController.result_payload_from_hit(hit)
            seg_index = safe_int(payload.get("segment_index"), -1)
            start_ms = safe_int(payload.get("start_ms"), -1)
            if seg_index < 0 and start_ms < 0:
                continue
            terms = GlobalSearchResultsController.dedupe_terms(
                GlobalSearchResultsController.search_terms_from_query(q)
                + GlobalSearchResultsController.query_lexemes(q)
                + [q]
                + GlobalSearchResultsController.marked_terms_from_snippet(str(hit.get("snippet", "") or "")),
                min_len=1,
                max_terms=32,
            )
            excerpt = GlobalSearchResultsController.result_excerpt_from_hit(hit, terms=terms)
            if not excerpt:
                continue
            meeting_id = str(payload.get("meeting_id", "") or "")
            stage_id = str(payload.get("stage_id", "") or "")
            alias = str(payload.get("alias", "") or "")
            kind = str(payload.get("kind", "") or "")
            normalized_excerpt = re.sub(r"\s+", " ", str(excerpt or "")).strip().casefold()
            if not normalized_excerpt:
                continue
            anchor_key = (meeting_id, stage_id, alias, kind, int(seg_index), int(start_ms))
            if anchor_key in seen_anchor:
                continue
            seen_anchor.add(anchor_key)
            scope_key = (meeting_id, stage_id, alias, kind, normalized_excerpt)
            if scope_key in seen_excerpt_scope:
                continue
            seen_excerpt_scope.add(scope_key)
            meeting_label = str(hit.get("meeting_label", "") or hit.get("meeting_id", "") or "").strip() or "Meeting"
            ts = format_ms_hhmmss(int(start_ms)) if int(start_ms) >= 0 else ""
            seg_part = f"#{int(seg_index)}" if int(seg_index) >= 0 else ""
            title_parts = [str(meeting_label).strip()]
            if ts:
                title_parts.append(ts)
            if seg_part:
                title_parts.append(seg_part)
            title = "  ".join([part for part in title_parts if str(part).strip()]).strip()
            rows.append(
                {
                    "title": title or f"Result {len(rows) + 1}",
                    "preview": truncate_result_text(excerpt.replace("\n", " "), limit=140),
                    "text": excerpt,
                    "payload": payload,
                    "terms": terms,
                }
            )
            if len(rows) >= 120:
                break
        return rows
