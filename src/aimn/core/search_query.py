from __future__ import annotations

import re
import unicodedata

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


def normalize_search_query(query: str) -> str:
    raw = str(query or "")
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\u2029", " ").replace("\u2028", " ").replace("\xa0", " ")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = re.sub(r"\s+", " ", text, flags=re.UNICODE)
    return text.strip()


def query_tokens(query: str) -> list[str]:
    raw = normalize_search_query(query).lower()
    if not raw:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[\w-]+", raw, flags=re.UNICODE):
        value = str(token or "").strip("_-")
        if len(value) < 3:
            continue
        if value in _STOPWORDS:
            continue
        if value in seen:
            continue
        seen.add(value)
        tokens.append(value)
    return tokens


def stem_token(token: str) -> str:
    value = str(token or "").strip().lower()
    if len(value) < 5:
        return value
    for ending in _COMMON_RU_ENDINGS:
        if value.endswith(ending):
            stem = value[: -len(ending)]
            if len(stem) >= 4:
                return stem
    return value


def query_variants(
    query: str,
    *,
    include_wildcards: bool = False,
    max_variants: int = 16,
) -> list[str]:
    base = normalize_search_query(query)
    if not base:
        return []
    tokens = query_tokens(base)
    variants: list[str] = [base]
    if tokens:
        variants.append(" ".join(tokens[: min(4, len(tokens))]))
    for token in tokens[:8]:
        variants.append(token)
        if include_wildcards and len(token) >= 4:
            variants.append(f"{token}*")
        stem = stem_token(token)
        if stem and stem != token:
            variants.append(stem)
            if include_wildcards and len(stem) >= 4:
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
        if len(unique) >= max(1, int(max_variants)):
            break
    return unique

