from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from aimn.core.fingerprinting import compute_source_fingerprint


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sanitize_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")
    return cleaned[:32] if cleaned else "meeting"


_STAMP_RE = re.compile(r"(?<!\d)(\d{6}|\d{8})[-_](\d{4})(?!\d)")


def _parse_stamp(match: re.Match[str]) -> datetime | None:
    raw_date = match.group(1)
    raw_time = match.group(2)
    if len(raw_date) == 6:
        year = 2000 + int(raw_date[0:2])
        month = int(raw_date[2:4])
        day = int(raw_date[4:6])
    else:
        year = int(raw_date[0:4])
        month = int(raw_date[4:6])
        day = int(raw_date[6:8])
    hour = int(raw_time[0:2])
    minute = int(raw_time[2:4])
    try:
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_candidate_stamps(value: str) -> list[datetime]:
    raw = str(value or "")
    candidates: list[datetime] = []
    for match in _STAMP_RE.finditer(raw):
        parsed = _parse_stamp(match)
        if parsed is not None:
            candidates.append(parsed)
    return candidates


def _strip_leading_stamps(value: str) -> str:
    s = str(value or "")
    while True:
        match = _STAMP_RE.match(s)
        if not match:
            break
        s = s[match.end() :]
        s = s.lstrip("_- .")
    return s.strip()


def _strip_double_extension_markers(stem: str) -> str:
    # Common double-extension patterns for derived audio/video files.
    value = str(stem or "")
    lowered = value.lower()
    if lowered.endswith(".audio"):
        return value[: -len(".audio")]
    if lowered.endswith(".video"):
        return value[: -len(".video")]
    return value


def make_meeting_ids(media_path: Path, *, fingerprint: str | None = None) -> tuple[str, str]:
    stat = media_path.stat()
    stem = _strip_double_extension_markers(media_path.stem)

    # Prefer a timestamp embedded in the filename. This avoids "processing time" prefixes
    # creeping into meeting IDs when files are copied/re-encoded during runs.
    candidates = _extract_candidate_stamps(media_path.name)
    ts = min(candidates) if candidates else datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    stamp = ts.strftime("%y%m%d-%H%M")

    stripped = _strip_leading_stamps(stem)
    short_name = sanitize_name(stripped)
    stamp_sanitized = stamp.replace("-", "_")
    if short_name.startswith(f"{stamp_sanitized}_"):
        short_name = short_name[len(stamp_sanitized) + 1 :] or "meeting"
    base_name = f"{stamp}_{short_name}"
    fingerprint = fingerprint or compute_source_fingerprint(str(media_path))
    key_source = fingerprint.split(":", 1)[-1]
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:8]
    meeting_id = f"{stamp}_{key}"
    return meeting_id, base_name
