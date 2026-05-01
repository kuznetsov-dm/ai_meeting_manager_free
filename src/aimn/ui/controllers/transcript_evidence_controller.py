from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtGui import QTextCursor


_LOG = logging.getLogger(__name__)


def safe_int(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True)
class TranscriptSuggestionSpan:
    suggestion_id: str
    kind: str
    title: str
    left: int
    right: int
    confidence: float
    selected_text: str
    evidence: dict[str, object]


class TranscriptEvidenceController:
    def __init__(self, artifact_text_provider: Callable[[str], str]) -> None:
        self._artifact_text_provider = artifact_text_provider
        self._segments_cache: dict[str, list[dict]] = {}

    def clear_segments_cache(self) -> None:
        self._segments_cache = {}

    @staticmethod
    def ms_to_hhmmss(ms: int) -> str:
        value = max(0, int(ms or 0))
        sec = value // 1000
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def load_segments_records(self, relpath: str) -> list[dict]:
        key = str(relpath or "")
        if key in self._segments_cache:
            return list(self._segments_cache.get(key) or [])
        try:
            raw = self._artifact_text_provider(key)
        except Exception as exc:
            _LOG.warning("segments_artifact_load_failed relpath=%s error=%s", key, exc)
            raw = ""
        records: list[dict] = []
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError as exc:
            _LOG.warning("segments_artifact_parse_failed relpath=%s error=%s", key, exc)
            payload = None
        if isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]
        elif isinstance(payload, dict):
            candidate = payload.get("records") or payload.get("segments") or []
            if isinstance(candidate, list):
                records = [r for r in candidate if isinstance(r, dict)]
        self._segments_cache[key] = list(records)
        return list(records)

    @staticmethod
    def transcript_suggestions_for_alias(
        management_suggestions: Sequence[dict] | None,
        alias: str,
    ) -> list[dict]:
        out: list[dict] = []
        alias_value = str(alias or "").strip()
        for item in management_suggestions or []:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence")
            if not isinstance(evidence, list):
                continue
            matches = []
            for entry in evidence:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("source", "") or "").strip().lower() != "transcript":
                    continue
                entry_alias = str(entry.get("alias", "") or "").strip()
                if alias_value and entry_alias and entry_alias != alias_value:
                    continue
                matches.append(dict(entry))
            if not matches:
                continue
            row = dict(item)
            row["transcript_evidence"] = matches
            out.append(row)
        return out

    @staticmethod
    def build_transcript_suggestion_spans(
        records: list[dict],
        ranges: list[tuple[int, int] | None],
        suggestions: Sequence[dict],
    ) -> list[TranscriptSuggestionSpan]:
        if not records or not ranges or not suggestions:
            return []
        index_to_row: dict[int, int] = {}
        for row, record in enumerate(records):
            try:
                index_value = int(record.get("index") if record.get("index") is not None else row)
            except (TypeError, ValueError):
                index_value = row
            index_to_row.setdefault(index_value, row)

        spans: list[TranscriptSuggestionSpan] = []
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            evidence_entries = suggestion.get("transcript_evidence")
            if not isinstance(evidence_entries, list):
                continue
            for entry in evidence_entries:
                if not isinstance(entry, dict):
                    continue
                start_index = safe_int(
                    entry.get("segment_index_start", entry.get("segment_index")),
                    safe_int(entry.get("segment_index"), -1),
                )
                end_index = safe_int(
                    entry.get("segment_index_end", entry.get("segment_index")),
                    start_index,
                )
                if start_index < 0:
                    continue
                start_row = index_to_row.get(start_index)
                end_row = index_to_row.get(end_index, start_row)
                if start_row is None or end_row is None:
                    continue
                left_idx = min(start_row, end_row)
                right_idx = max(start_row, end_row)
                left_range = ranges[left_idx] if left_idx < len(ranges) else None
                right_range = ranges[right_idx] if right_idx < len(ranges) else None
                if not left_range or not right_range:
                    continue
                left = int(left_range[0])
                right = int(right_range[1])
                if right <= left:
                    continue
                narrowed = TranscriptEvidenceController._narrow_span_bounds(
                    records=records,
                    ranges=ranges,
                    left_row=left_idx,
                    right_row=right_idx,
                    evidence_text=str(entry.get("text", "") or "").strip(),
                    fallback_title=str(suggestion.get("title", "") or "").strip(),
                )
                if narrowed is not None:
                    left, right = narrowed
                spans.append(
                    TranscriptSuggestionSpan(
                        suggestion_id=str(suggestion.get("id", "") or "").strip(),
                        kind=str(suggestion.get("kind", "") or "").strip(),
                        title=str(suggestion.get("title", "") or "").strip(),
                        left=left,
                        right=right,
                        confidence=float(suggestion.get("confidence", 0.0) or 0.0),
                        selected_text=str(entry.get("text", "") or "").strip()
                        or str(suggestion.get("description", "") or "").strip()
                        or str(suggestion.get("title", "") or "").strip(),
                        evidence=dict(entry),
                    )
                )
                break
        spans.sort(key=lambda item: (item.left, item.right, -item.confidence))
        return spans

    @staticmethod
    def _narrow_span_bounds(
        *,
        records: list[dict],
        ranges: list[tuple[int, int] | None],
        left_row: int,
        right_row: int,
        evidence_text: str,
        fallback_title: str,
    ) -> tuple[int, int] | None:
        if left_row < 0 or right_row < left_row:
            return None
        target = TranscriptEvidenceController._normalize_match_text(evidence_text)
        if not target:
            target = TranscriptEvidenceController._normalize_match_text(fallback_title)
        if not target:
            return None

        best: tuple[tuple[int, float], tuple[int, int]] | None = None
        upper = min(int(right_row), len(records) - 1)
        for start in range(int(left_row), upper + 1):
            for end in range(start, min(upper, start + 1) + 1):
                left_range = ranges[start] if start < len(ranges) else None
                right_range = ranges[end] if end < len(ranges) else None
                if not left_range or not right_range:
                    continue
                window_text = " ".join(
                    str(records[idx].get("text", "") or "").strip()
                    for idx in range(start, end + 1)
                    if idx < len(records) and isinstance(records[idx], dict)
                ).strip()
                score = TranscriptEvidenceController._match_score(target, window_text)
                if score <= 0.0:
                    continue
                bounds = (int(left_range[0]), int(right_range[1]))
                rank = (end - start, -score)
                if best is None or rank < best[0]:
                    best = (rank, bounds)
        return None if best is None else best[1]

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _match_tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-zA-ZА-Яа-я0-9]+", str(value or "").lower())
            if len(token) >= 3
        }

    @staticmethod
    def _match_score(target: str, window_text: str) -> float:
        window = TranscriptEvidenceController._normalize_match_text(window_text)
        if not target or not window:
            return 0.0
        if target in window:
            return 1.0 + (len(target) / 10000.0)
        target_tokens = TranscriptEvidenceController._match_tokens(target)
        window_tokens = TranscriptEvidenceController._match_tokens(window)
        if not target_tokens or not window_tokens:
            return 0.0
        overlap = len(target_tokens & window_tokens) / max(1, len(target_tokens))
        if overlap < 0.72:
            return 0.0
        return overlap

    @staticmethod
    def build_segment_text_ranges(transcript_text: str, records: list[dict]) -> list[tuple[int, int] | None]:
        source = str(transcript_text or "")
        source_lower = source.lower()
        cursor = 0
        ranges: list[tuple[int, int] | None] = []
        for rec in records:
            if not isinstance(rec, dict):
                ranges.append(None)
                continue
            segment_text = str(rec.get("text") or "").strip()
            if not segment_text:
                ranges.append(None)
                continue
            needle = segment_text.lower()
            pos = source_lower.find(needle, cursor)
            if pos < 0:
                pos = source_lower.find(needle)
            if pos < 0:
                ranges.append(None)
                continue
            end = pos + len(segment_text)
            ranges.append((pos, end))
            cursor = max(cursor, end)
        return ranges

    @staticmethod
    def find_segment_row_for_cursor(position: int, ranges: list[tuple[int, int] | None]) -> int:
        pos = int(position)
        for idx, item in enumerate(ranges):
            if not item:
                continue
            start, end = int(item[0]), int(item[1])
            if start <= pos <= end:
                return idx
        return -1

    @staticmethod
    def find_segment_row_by_timestamp(records: list[dict], seconds: float) -> int:
        target_ms = int(max(0.0, float(seconds)) * 1000.0)
        for idx, rec in enumerate(records):
            if not isinstance(rec, dict):
                continue
            start_ms = int(rec.get("start_ms") or 0)
            end_ms = int(rec.get("end_ms") or start_ms)
            if start_ms <= target_ms <= max(start_ms, end_ms):
                return idx
        return -1

    @staticmethod
    def selection_evidence_payload(
        cursor: QTextCursor,
        ranges: list[tuple[int, int] | None],
        records: list[dict],
    ) -> dict[str, object]:
        start = min(int(cursor.selectionStart()), int(cursor.selectionEnd()))
        end = max(int(cursor.selectionStart()), int(cursor.selectionEnd()))
        overlapping_rows: list[int] = []
        for idx, item in enumerate(ranges):
            if not item:
                continue
            left, right = int(item[0]), int(item[1])
            if end <= left or start >= right:
                continue
            overlapping_rows.append(idx)
        if not overlapping_rows:
            row = TranscriptEvidenceController.find_segment_row_for_cursor(start, ranges)
            if row >= 0:
                overlapping_rows.append(row)
        if not overlapping_rows:
            return {}
        first = records[overlapping_rows[0]] if overlapping_rows[0] < len(records) else {}
        last = records[overlapping_rows[-1]] if overlapping_rows[-1] < len(records) else first
        payload: dict[str, object] = {
            "segment_index_start": int(first.get("index") if first.get("index") is not None else overlapping_rows[0]),
            "segment_index_end": int(last.get("index") if last.get("index") is not None else overlapping_rows[-1]),
            "start_ms": int(first.get("start_ms") or 0),
            "end_ms": int(last.get("end_ms") or int(last.get("start_ms") or 0)),
        }
        speaker = str(first.get("speaker", "") or "").strip()
        if speaker:
            payload["speaker"] = speaker
        return payload
