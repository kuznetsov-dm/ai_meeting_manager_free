from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from aimn.ui.controllers.transcript_evidence_controller import TranscriptSuggestionSpan, safe_int


@dataclass(frozen=True)
class TranscriptSegmentItem:
    label: str
    payload: dict[str, object]


class TranscriptViewModelController:
    @staticmethod
    def build_segment_items(
        records: Sequence[dict],
        ranges: Sequence[tuple[int, int] | None],
        *,
        format_ms: Callable[[int], str],
    ) -> list[TranscriptSegmentItem]:
        items: list[TranscriptSegmentItem] = []
        for idx, rec in enumerate(records):
            if not isinstance(rec, dict):
                continue
            start_ms = safe_int(rec.get("start_ms"), 0)
            end_ms = safe_int(rec.get("end_ms"), start_ms)
            seg_index = safe_int(rec.get("index"), idx)
            speaker = str(rec.get("speaker") or "").strip()
            text = str(rec.get("text") or "").strip()
            ts = str(format_ms(start_ms) or "").strip()
            preview = text if len(text) <= 80 else text[:77] + "..."
            label = f"{ts}  {speaker}  {preview}".strip()
            items.append(
                TranscriptSegmentItem(
                    label=label,
                    payload={
                        "row": idx,
                        "segment_index": seg_index,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "text_range": ranges[idx] if idx < len(ranges) else None,
                    },
                )
            )
        return items

    @staticmethod
    def suggestion_span_at_position(
        spans: Sequence[TranscriptSuggestionSpan],
        position: int,
    ) -> TranscriptSuggestionSpan | None:
        pos = int(position)
        matches = [item for item in spans if int(item.left) <= pos <= int(item.right)]
        if not matches:
            return None
        matches.sort(key=lambda item: (item.right - item.left, -item.confidence))
        return matches[0]
