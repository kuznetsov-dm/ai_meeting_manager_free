from __future__ import annotations

import re


_ASR_NOISE_TOKEN_RE = re.compile(
    r"(?i)\[(?:blank_audio|foreign|music|noise|laughter|inaudible|silence|unknown)\]"
)
_ASR_NOISE_WORD_RE = re.compile(
    r"(?i)\b(?:blank_audio|inaudible|foreign|music|noise|laughter)\b"
)

_ASR_HALLUCINATION_LINES_RE = re.compile(
    r"(?i)^\s*(?:редактор\s+субтитров|корректор)\b.*$"
)

_FILLER_HEAD_RE = re.compile(
    r"(?i)^\s*(?:"
    r"(?:ну|вот|типа|короче|значит|собственно|просто)\b|"
    r"в\s+общем|в\s+принципе|как\s+бы|то\s+есть|"
    r"(?:скажем|допустим|смотрите|слушай|слушайте)\b"
    r")\s*(?:[,—-]\s*)?"
)

_FILLER_REPEAT_RE = re.compile(r"(?i)\b(ну|вот|типа|короче|значит)\b(?:\s+\1\b)+")

_FILLER_PHRASES_RE = re.compile(
    r"(?i)\b(?:"
    r"все\s+равно|"
    r"может\s+быть|"
    r"мне\s+кажется|"
    r"как\s+бы|"
    r"то\s+есть|"
    r"в\s+общем|"
    r"в\s+принципе|"
    r"на\s+самом\s+деле|"
    r"по\s+сути|"
    r"в\s+любом\s+случае|"
    r"скажем\s+так|"
    r"так\s+сказать|"
    r"если\s+честно"
    r")\b"
)

_FILLER_TOKENS_RE = re.compile(
    r"(?i)\b(?:"
    r"все|всё|"
    r"ну|вот|типа|короче|значит|собственно|просто|вообще|кстати|"
    r"реально|буквально|вроде|прям|"
    r"бла|"
    r"ладно|окей|"
    r"скажем|допустим|"
    r"слушай|слушайте|смотрите|"
    r"ага|угу|"
    r"э|эм|мм|м"
    r")\b"
)


def _strip_fillers(text: str) -> str:
    value = str(text or "")
    if not value.strip():
        return ""

    # Remove common discourse markers at line/sentence head (repeat a few times).
    for _ in range(3):
        new = _FILLER_HEAD_RE.sub("", value)
        if new == value:
            break
        value = new

    # Collapse repeated fillers like "ну ну ну" / "вот вот".
    value = _FILLER_REPEAT_RE.sub(r"\1", value)

    # Remove "вот X вот" pattern (common in ASR).
    value = re.sub(r"(?i)\bвот\s+([0-9a-zа-яё-]{2,})\s+вот\b", r"\1", value)

    # Remove common filler phrases/tokens anywhere (best-effort).
    value = _FILLER_PHRASES_RE.sub(" ", value)
    value = _FILLER_TOKENS_RE.sub(" ", value)

    # Collapse repeated words like "формирует формирует" / "stm stm".
    value = re.sub(r"(?i)\b([0-9a-zа-яё-]{3,})\b(?:\s+\1\b)+", r"\1", value)
    # Collapse "да да" / "нет нет" runs without removing single confirmations.
    value = re.sub(r"(?i)\b(да|нет)\b(?:\s+\1\b)+", r"\1", value)

    # Cleanup spaces around punctuation.
    value = re.sub(r"\s+([,.;:!?…])", r"\1", value)
    value = re.sub(r"([,.;:!?…])\s{2,}", r"\1 ", value)
    return re.sub(r"\s+", " ", value).strip()


def _strip_asr_noise(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    # Drop common whisper hallucinations on silence (subtitle credits).
    if _ASR_HALLUCINATION_LINES_RE.match(value):
        return ""
    value = _ASR_NOISE_TOKEN_RE.sub(" ", value)
    value = _ASR_NOISE_WORD_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip()
    if not value:
        return ""
    return _strip_fillers(value)


def cleanup_transcript(text: str) -> tuple[str, dict]:
    stats = {
        "lines_removed": 0,
        "sentences_removed": 0,
        "blank_lines_removed": 0,
    }
    raw = str(text or "")
    if not raw.strip():
        return raw, stats

    lines = [_strip_asr_noise(line) for line in raw.splitlines()]
    cleaned_lines: list[str] = []
    last_line: str | None = None
    repeat_count = 0
    any_non_empty = False
    for line in lines:
        if line and line == last_line:
            repeat_count += 1
            if repeat_count >= 2:
                stats["lines_removed"] += 1
                continue
        else:
            repeat_count = 0
        if not line:
            cleaned_lines.append("")
            last_line = line
            continue
        any_non_empty = True
        cleaned_lines.append(_dedupe_sentences(line, stats))
        last_line = line

    collapsed: list[str] = []
    blank_run = 0
    for line in cleaned_lines:
        if line == "":
            blank_run += 1
            if blank_run > 1:
                stats["blank_lines_removed"] += 1
                continue
        else:
            blank_run = 0
        collapsed.append(line)

    cleaned = "\n".join(collapsed).strip()
    if not cleaned:
        # If the transcript is nothing but ASR noise tokens (FOREIGN/BLANK_AUDIO/etc),
        # keep it empty to make downstream handling explicit.
        return ("" if not any_non_empty else raw), stats
    return cleaned, stats


def _dedupe_sentences(line: str, stats: dict) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", stripped)
    if len(parts) <= 1:
        return stripped
    out: list[str] = []
    last: str | None = None
    for part in parts:
        sentence = _strip_asr_noise(part.strip())
        if not sentence:
            stats["sentences_removed"] += 1
            continue
        if sentence == last:
            stats["sentences_removed"] += 1
            continue
        out.append(sentence)
        last = sentence
    return " ".join(out).strip()
