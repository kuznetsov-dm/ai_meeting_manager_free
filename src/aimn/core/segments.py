from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from aimn.domain.meeting import SegmentIndex
from aimn.core.atomic_io import atomic_write_text


def segments_from_asr_json(raw_json: str) -> Tuple[List[SegmentIndex], List[Dict[str, object]]]:
    data: Any = json.loads(raw_json) if raw_json else {}

    # Some providers wrap the payload.
    if isinstance(data, dict):
        has_outer_segments = isinstance(data.get("segments"), list) and bool(data.get("segments"))
        has_outer_transcription = isinstance(data.get("transcription"), list) and bool(data.get("transcription"))
        if not (has_outer_segments or has_outer_transcription) and isinstance(data.get("result"), dict):
            inner = data.get("result") or {}
            if isinstance(inner.get("segments"), list) and bool(inner.get("segments")):
                data = inner
            elif isinstance(inner.get("transcription"), list) and bool(inner.get("transcription")):
                data = inner

    index_items: List[SegmentIndex] = []
    records: List[Dict[str, object]] = []

    # whisper.cpp JSON schema variants:
    # - {"segments": [{"start": seconds, "end": seconds, "text": "..."}]}
    # - {"transcription": [{"offsets": {"from": ms, "to": ms}, "text": "..."}]}
    segments = data.get("segments", []) if isinstance(data, dict) else []
    if isinstance(segments, list) and segments:
        for idx, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            start_ms = int(float(seg.get("start", 0) or 0) * 1000)
            end_ms = int(float(seg.get("end", 0) or 0) * 1000)
            text = str(seg.get("text", "")).strip()
            speaker = seg.get("speaker")
            confidence = seg.get("confidence")
            index_items.append(
                SegmentIndex(
                    index=idx,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speaker=speaker,
                    confidence=confidence,
                )
            )
            records.append(
                {
                    "index": idx,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": text,
                    "speaker": speaker,
                    "confidence": confidence,
                }
            )
        return index_items, records

    transcription = data.get("transcription", []) if isinstance(data, dict) else []
    if isinstance(transcription, list) and transcription:
        idx = 0
        for item in transcription:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            offsets = item.get("offsets") if isinstance(item.get("offsets"), dict) else {}
            start_ms = int(offsets.get("from", 0) or 0)
            end_ms = int(offsets.get("to", 0) or 0)
            index_items.append(SegmentIndex(index=idx, start_ms=start_ms, end_ms=end_ms))
            records.append(
                {
                    "index": idx,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": text,
                    "speaker": None,
                    "confidence": None,
                }
            )
            idx += 1
        return index_items, records

    return index_items, records


def write_segments_file(path: str, records: List[Dict[str, object]]) -> None:
    data = json.dumps(records, ensure_ascii=True, indent=2)
    atomic_write_text(Path(path), data)
