from __future__ import annotations

import re


_PROGRESS_PATTERNS = [
    re.compile(r"progress\s*=\s*(\d{1,3})\s*%", re.IGNORECASE),
    re.compile(r"progress\s*:\s*(\d{1,3})\s*%", re.IGNORECASE),
    re.compile(r"whisper_print_progress[^0-9]*(\d{1,3})\s*%", re.IGNORECASE),
    re.compile(r"(?:processing|processed)[^0-9]{0,12}(\d{1,3})\s*%", re.IGNORECASE),
]


def parse_progress(line: str) -> int | None:
    value = None
    for pattern in _PROGRESS_PATTERNS:
        match = pattern.search(line)
        if match:
            value = int(match.group(1))
            break
    if value is None:
        return None
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value
