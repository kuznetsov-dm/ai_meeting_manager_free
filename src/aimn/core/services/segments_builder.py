from __future__ import annotations

from aimn.core.segments import segments_from_asr_json
from aimn.domain.meeting import SegmentIndex


def build_segments_from_asr(
    raw_json: str, *, fallback_transcript: str | None = None
) -> tuple[list[SegmentIndex], list[dict[str, object]]]:
    segments_index, records = segments_from_asr_json(raw_json)
    if records:
        return segments_index, records

    transcript = (fallback_transcript or "").strip()
    if not transcript:
        return segments_index, records

    segments_index = [SegmentIndex(index=0, start_ms=0, end_ms=0)]
    records = [
        {
            "index": 0,
            "start_ms": 0,
            "end_ms": 0,
            "text": transcript,
            "speaker": None,
            "confidence": None,
        }
    ]
    return segments_index, records
