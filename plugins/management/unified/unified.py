from __future__ import annotations

import json
import re
from dataclasses import dataclass

from aimn.plugins.api import ArtifactSchema, HookContext, open_management_store
from aimn.plugins.interfaces import KIND_EDITED, KIND_MANAGEMENT_SUGGESTIONS, KIND_SEGMENTS, KIND_SUMMARY, KIND_TRANSCRIPT


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_MANAGEMENT_SUGGESTIONS, ArtifactSchema(content_type="json", user_visible=True))
        ctx.register_hook_handler("derive.after_summary", hook_unified_management, mode="optional", priority=100)


@dataclass(frozen=True)
class _Candidate:
    kind: str
    title: str
    description: str
    normalized_key: str
    confidence: float
    reasoning_short: str
    evidence: list[dict]


def hook_unified_management(ctx: HookContext):
    source_text, source_kind, source_alias, warning = _resolve_source_text(ctx)
    if warning:
        ctx.emit_warning(warning)
    if not source_text:
        return None

    store = open_management_store(ctx)
    suggestions: list[dict] = []
    try:
        candidates: list[_Candidate] = []
        rejected_counts = {"task": 0, "project": 0, "agenda": 0}
        tasks, has_actions_section = _extract_action_items(source_text)
        if not has_actions_section:
            ctx.emit_warning("management_tasks_section_missing")
        for title in tasks:
            candidate = _build_task_candidate(ctx, source_text, source_kind, source_alias, title)
            if candidate is None:
                rejected_counts["task"] += 1
                continue
            candidates.append(candidate)

        projects, has_projects_section = _extract_projects(source_text)
        if not has_projects_section and not projects:
            ctx.emit_warning("management_projects_section_missing")
        for name in projects:
            candidate = _build_project_candidate(ctx, source_text, source_kind, source_alias, name)
            if candidate is None:
                rejected_counts["project"] += 1
                continue
            candidates.append(candidate)

        agenda_text, agenda_title = _extract_agenda_block(source_text)
        if agenda_text:
            candidate = _build_agenda_candidate(ctx, source_text, source_kind, source_alias, agenda_title, agenda_text)
            if candidate is None:
                rejected_counts["agenda"] += 1
            else:
                candidates.append(candidate)

        deduped = _dedupe_candidates(candidates)
        _hide_stale_suggestions(
            store,
            meeting_id=ctx.meeting_id,
            source_kind=source_kind,
            source_alias=source_alias,
            keep_keys={(item.kind, item.normalized_key) for item in deduped},
        )
        for item in deduped:
            suggestion_id = store.upsert_suggestion(
                kind=item.kind,
                title=item.title,
                description=item.description,
                normalized_key=item.normalized_key,
                source_meeting_id=ctx.meeting_id,
                source_kind=source_kind,
                source_alias=source_alias,
                confidence=item.confidence,
                reasoning_short=item.reasoning_short,
                evidence=item.evidence,
            )
            suggestions.append(_suggestion_by_id(store, suggestion_id))

        for kind, count in rejected_counts.items():
            if count > 0:
                ctx.emit_warning(f"management_{kind}_candidates_rejected({count})")
        if not deduped:
            ctx.emit_warning("management_suggestions_empty")
        payload = json.dumps(suggestions, indent=2, ensure_ascii=True)
        ctx.write_artifact(KIND_MANAGEMENT_SUGGESTIONS, payload, content_type="json")
    finally:
        store.close()
    return None


def _resolve_source_text(ctx: HookContext) -> tuple[str | None, str, str, str | None]:
    summary = ctx.get_artifact(KIND_SUMMARY)
    if summary and summary.content:
        return summary.content, KIND_SUMMARY, _alias_from_relpath(str(summary.meta.path or "")), None
    edited = ctx.get_artifact(KIND_EDITED)
    if edited and edited.content:
        return edited.content, KIND_EDITED, _alias_from_relpath(str(edited.meta.path or "")), None
    return None, KIND_SUMMARY, "", "management_missing_input"


_ALIAS_RE = re.compile(r"__([^.]*)\.")


def _alias_from_relpath(relpath: str) -> str:
    raw = str(relpath or "")
    match = _ALIAS_RE.search(raw)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalized_word_count(value: str) -> int:
    return len([part for part in _normalize_text(value).split(" ") if part])


_GENERIC_EXACT = {
    "n/a",
    "na",
    "none",
    "нет",
    "ничего",
    "tbd",
    "todo",
    "to do",
    "follow up",
    "follow-up",
    "action item",
    "action items",
    "next steps",
    "далее",
    "следующие шаги",
    "задачи",
    "проекты",
    "повестка",
    "agenda",
    "project",
    "projects",
    "task",
    "tasks",
    "\u0434\u0430\u0442\u044b \u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u044b",
}

_TASK_REJECT_PATTERNS = [
    re.compile(r"^(discuss|review|check|align|sync|think about)\b", flags=re.IGNORECASE),
    re.compile(r"^(обсудить|проверить|сверить|подумать|синхронизировать)\b", flags=re.IGNORECASE),
]
_PROJECT_REJECT_PATTERNS = [
    re.compile(r"^(todo|task|action item|follow up)\b", flags=re.IGNORECASE),
    re.compile(r"^(задача|действие|экшен|follow[- ]?up)\b", flags=re.IGNORECASE),
]


def _extract_action_items(text: str) -> tuple[list[str], bool]:
    lines = str(text or "").splitlines()
    in_section = False
    has_section = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        heading_match = re.match(r"^(#{2,6})\s+(.+?)\s*$", stripped)
        if heading_match:
            heading_text = str(heading_match.group(2) or "").strip().lower()
            if heading_text.startswith("action items") or _looks_like_ru_actions_heading(heading_text):
                in_section = True
                has_section = True
                continue
            if in_section:
                break
        if not in_section:
            continue
        match = re.match(r"^[-*]\s+\[( |x|X)\]\s+(.*)$", stripped)
        if match:
            task_text = match.group(2).strip()
        else:
            bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
            if not bullet_match:
                continue
            task_text = bullet_match.group(1).strip()
        if task_text:
            items.append(task_text)
    return items, has_section


def _extract_projects(text: str) -> tuple[list[str], bool]:
    lines = str(text or "").splitlines()
    in_section = False
    has_section = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        heading_match = re.match(r"^(#{2,6})\s+(.+?)\s*$", stripped)
        if heading_match:
            heading_text = str(heading_match.group(2) or "").strip()
            if re.match(r"^projects\s+discussed\b", heading_text, flags=re.IGNORECASE) or re.match(
                r"^projects\b", heading_text, flags=re.IGNORECASE
            ) or _looks_like_ru_projects_heading(heading_text):
                in_section = True
                has_section = True
                continue
            if in_section:
                break
        if not in_section:
            continue
        match = re.match(r"^[-*]\s+(.*)$", stripped)
        if not match:
            continue
        name = match.group(1).strip()
        if name:
            items.append(name)
    for line in lines:
        stripped = line.strip()
        match = re.match(r"^#{2,6}\s*project\s*:\s*(.+)$", stripped, flags=re.IGNORECASE)
        if not match:
            continue
        name = match.group(1).strip()
        if name:
            items.append(name)
    seen: set[str] = set()
    unique: list[str] = []
    for name in items:
        key = _normalize_text(name)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(name.strip())
    return unique, has_section

def _looks_like_ru_actions_heading(value: str) -> bool:
    text = str(value or "").strip().lower()
    return any(
        key in text
        for key in (
            "\u0437\u0430\u0434\u0430\u0447\u0438",
            "\u043f\u043e\u0440\u0443\u0447\u0435\u043d\u0438\u044f",
            "\u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u0438",
            "\u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0435 \u0448\u0430\u0433\u0438",
        )
    )


def _looks_like_ru_projects_heading(value: str) -> bool:
    text = str(value or "").strip().lower()
    return any(
        key in text
        for key in (
            "\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u044f \u043f\u0440\u043e\u0435\u043a\u0442\u043e\u0432",
            "\u043f\u0440\u043e\u0435\u043a\u0442\u044b",
        )
    )


def _extract_agenda_block(text: str) -> tuple[str, str]:
    lines = str(text or "").splitlines()
    start = None
    title = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^##\s+(planned\s+)?agenda\b", stripped, flags=re.IGNORECASE):
            start = idx + 1
            title = "Planned agenda" if "planned" in stripped.lower() else "Agenda"
            break
    if start is None:
        return "", ""
    block: list[str] = []
    for line in lines[start:]:
        stripped = line.rstrip()
        if re.match(r"^##\s+\S", stripped.strip()):
            break
        block.append(stripped)
    agenda_text = "\n".join(block).strip()
    if not agenda_text:
        return "", ""
    return agenda_text, title


def _is_generic_candidate(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return True
    if normalized in _GENERIC_EXACT:
        return True
    return False


def _build_task_candidate(
    ctx: HookContext, source_text: str, source_kind: str, source_alias: str, title: str
) -> _Candidate | None:
    title_value = _clean_inline_candidate(title)
    normalized = _normalize_text(title_value)
    if _is_generic_candidate(title_value) or _normalized_word_count(title_value) < 2:
        return None
    if any(pattern.search(title_value) for pattern in _TASK_REJECT_PATTERNS):
        return None
    evidence = _make_evidence(ctx, source_text, title_value, source_kind=source_kind, source_alias=source_alias)
    if not evidence:
        return None
    return _Candidate(
        kind="task",
        title=title_value,
        description="",
        normalized_key=normalized,
        confidence=0.86,
        reasoning_short="Explicit action item extracted from summary/edit.",
        evidence=evidence,
    )


def _build_project_candidate(
    ctx: HookContext, source_text: str, source_kind: str, source_alias: str, name: str
) -> _Candidate | None:
    title_value = _clean_inline_candidate(name)
    normalized = _normalize_text(title_value)
    if _is_generic_candidate(title_value):
        return None
    if _normalized_word_count(title_value) < 2 and len(title_value) < 10:
        return None
    if any(pattern.search(title_value) for pattern in _PROJECT_REJECT_PATTERNS):
        return None
    evidence = _make_evidence(ctx, source_text, title_value, source_kind=source_kind, source_alias=source_alias)
    if not evidence:
        return None
    return _Candidate(
        kind="project",
        title=title_value,
        description="",
        normalized_key=normalized,
        confidence=0.73,
        reasoning_short="Repeated project/workstream marker extracted from summary/edit.",
        evidence=evidence,
    )


def _build_agenda_candidate(
    ctx: HookContext,
    source_text: str,
    source_kind: str,
    source_alias: str,
    agenda_title: str,
    agenda_text: str,
) -> _Candidate | None:
    description = str(agenda_text or "").strip()
    if len(description) < 12:
        return None
    non_empty_lines = [line.strip() for line in description.splitlines() if line.strip()]
    if not non_empty_lines:
        return None
    title_value = _clean_inline_candidate(agenda_title or "Agenda")
    if _is_generic_candidate(title_value):
        title_value = "Agenda"
    evidence = _make_evidence(
        ctx,
        source_text,
        description,
        source_kind=source_kind,
        source_alias=source_alias,
        prefer_multiline=True,
    )
    if not evidence:
        return None
    return _Candidate(
        kind="agenda",
        title=title_value,
        description=description,
        normalized_key=_normalize_text(title_value),
        confidence=0.92,
        reasoning_short="Explicit agenda block detected in the processed text.",
        evidence=evidence,
    )


def _clean_inline_candidate(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[\-\*\u2022]+\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n-:;,.")


def _dedupe_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    out: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        key = (item.kind, item.normalized_key)
        if not item.normalized_key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _hide_stale_suggestions(store, *, meeting_id: str, source_kind: str, source_alias: str, keep_keys: set[tuple[str, str]]) -> None:
    for item in store.list_suggestions(state=None, meeting_id=meeting_id):
        if str(item.get("state", "") or "").strip().lower() != "suggested":
            continue
        if str(item.get("source_kind", "") or "").strip() != str(source_kind or "").strip():
            continue
        if str(item.get("source_alias", "") or "").strip() != str(source_alias or "").strip():
            continue
        key = (
            str(item.get("kind", "") or "").strip(),
            str(item.get("normalized_key", "") or "").strip(),
        )
        if key in keep_keys:
            continue
        suggestion_id = str(item.get("id", "") or "").strip()
        if suggestion_id:
            store.set_suggestion_state(suggestion_id, state="hidden")


def _make_evidence(
    ctx: HookContext,
    source_text: str,
    fragment: str,
    *,
    source_kind: str,
    source_alias: str,
    prefer_multiline: bool = False,
) -> list[dict]:
    transcript_evidence = _make_transcript_evidence(ctx, fragment, prefer_multiline=prefer_multiline)
    if transcript_evidence:
        return [transcript_evidence]
    text = str(source_text or "")
    needle = str(fragment or "").strip()
    if not text or not needle:
        return []
    if prefer_multiline and needle in text:
        return [
            {
                "source": source_kind,
                "alias": source_alias,
                "text": needle,
            }
        ]
    for line in text.splitlines():
        stripped = line.strip()
        if needle.lower() in stripped.lower():
            return [
                {
                    "source": source_kind,
                    "alias": source_alias,
                    "text": stripped,
                }
            ]
    return [
        {
            "source": source_kind,
            "alias": source_alias,
            "text": needle,
        }
    ]


def _make_transcript_evidence(ctx: HookContext, fragment: str, *, prefer_multiline: bool = False) -> dict | None:
    segments_artifact = ctx.get_artifact(KIND_SEGMENTS)
    transcript_artifact = ctx.get_artifact(KIND_TRANSCRIPT)
    alias = _alias_from_relpath(str(getattr(getattr(segments_artifact, "meta", None), "path", "") or ""))
    if not alias:
        alias = _alias_from_relpath(str(getattr(getattr(transcript_artifact, "meta", None), "path", "") or ""))
    records = _load_segment_records(segments_artifact)
    if records:
        match = _match_segment_record(records, fragment, prefer_multiline=prefer_multiline)
        if match:
            evidence = {
                "source": KIND_TRANSCRIPT,
                "alias": alias,
                "text": str(match.get("text", "") or "").strip(),
            }
            if match.get("index") is not None:
                evidence["segment_index"] = int(match.get("index", 0) or 0)
                evidence["segment_index_start"] = int(match.get("index", 0) or 0)
            if match.get("index_end") is not None:
                evidence["segment_index_end"] = int(match.get("index_end", 0) or 0)
            if match.get("start_ms") is not None:
                evidence["start_ms"] = int(match.get("start_ms", 0) or 0)
            if match.get("end_ms") is not None:
                evidence["end_ms"] = int(match.get("end_ms", 0) or 0)
            speaker = str(match.get("speaker", "") or "").strip()
            if speaker:
                evidence["speaker"] = speaker
            return evidence
    transcript_text = str(getattr(transcript_artifact, "content", "") or "").strip()
    excerpt = _transcript_excerpt_for_fragment(transcript_text, fragment, prefer_multiline=prefer_multiline)
    if not excerpt:
        return None
    return {
        "source": KIND_TRANSCRIPT,
        "alias": alias,
        "text": excerpt,
    }


def _load_segment_records(artifact) -> list[dict]:
    raw = str(getattr(artifact, "content", "") or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _match_segment_record(records: list[dict], fragment: str, *, prefer_multiline: bool = False) -> dict | None:
    candidates = _fragment_candidates(fragment, prefer_multiline=prefer_multiline)
    if not candidates:
        return None
    windows = _segment_windows(records, max_window_size=3)
    best: tuple[float, dict] | None = None
    second_best = 0.0
    for window in windows:
        window_text = str(window.get("text", "") or "").strip()
        window_norm = _normalize_text(window_text)
        if not window_norm:
            continue
        for candidate in candidates:
            score = _candidate_window_score(candidate, window_norm)
            if score <= 0.0:
                continue
            if best is None or score > best[0]:
                second_best = best[0] if best is not None else second_best
                best = (score, window)
            elif score > second_best:
                second_best = score
    if best is None:
        return None
    best_score, best_window = best
    if best_score < 0.83:
        return None
    if best_score < 0.995 and (best_score - second_best) < 0.05:
        return None
    return best_window


def _segment_windows(records: list[dict], *, max_window_size: int = 2) -> list[dict]:
    windows: list[dict] = []
    clean_records = [dict(item) for item in records if str(item.get("text", "") or "").strip()]
    for start in range(len(clean_records)):
        parts: list[str] = []
        start_ms: int | None = None
        end_ms: int | None = None
        speakers: list[str] = []
        first_index: int | None = None
        last_index: int | None = None
        for offset in range(max_window_size):
            idx = start + offset
            if idx >= len(clean_records):
                break
            record = clean_records[idx]
            parts.append(str(record.get("text", "") or "").strip())
            if first_index is None:
                first_index = int(record.get("index", idx) or idx)
                start_ms = int(record.get("start_ms", 0) or 0)
            last_index = int(record.get("index", idx) or idx)
            end_ms = int(record.get("end_ms", 0) or 0)
            speaker = str(record.get("speaker", "") or "").strip()
            if speaker:
                speakers.append(speaker)
            windows.append(
                {
                    "index": int(first_index or 0),
                    "index_end": int(last_index if last_index is not None else first_index or 0),
                    "start_ms": int(start_ms or 0),
                    "end_ms": int(end_ms or 0),
                    "speaker": speakers[0] if speakers and len(set(speakers)) == 1 else "",
                    "text": " ".join(part for part in parts if part).strip(),
                    "segment_count": offset + 1,
                }
            )
    return windows


def _candidate_window_score(candidate: str, window_norm: str) -> float:
    candidate_norm = _normalize_text(candidate)
    if not candidate_norm or not window_norm:
        return 0.0
    if candidate_norm in window_norm:
        return 1.0 + (len(candidate_norm) / 10000.0)
    candidate_tokens = _meaningful_tokens(candidate_norm)
    window_tokens = _meaningful_tokens(window_norm)
    if not candidate_tokens or not window_tokens:
        return 0.0
    overlap = len(candidate_tokens & window_tokens) / max(1, len(candidate_tokens))
    ratio = _similarity(candidate_norm, window_norm)
    if overlap < 0.72 or ratio < 0.58:
        return 0.0
    return (0.68 * overlap) + (0.32 * ratio)


def _meaningful_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Zа-яА-Я0-9]+", str(text or "").lower()) if len(token) >= 3}


def _transcript_excerpt_for_fragment(text: str, fragment: str, *, prefer_multiline: bool = False) -> str:
    transcript = str(text or "").strip()
    if not transcript:
        return ""
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    for candidate in _fragment_candidates(fragment, prefer_multiline=prefer_multiline):
        candidate_norm = _normalize_text(candidate)
        if not candidate_norm:
            continue
        for line in lines:
            if candidate_norm in _normalize_text(line):
                return line
    return ""


def _fragment_candidates(fragment: str, *, prefer_multiline: bool = False) -> list[str]:
    text = str(fragment or "").strip()
    if not text:
        return []
    lines = [line.strip(" \t-*") for line in text.splitlines() if line.strip()]
    candidates: list[str] = []

    def _push(value: str) -> None:
        item = str(value or "").strip(" \t-*.,;:!?\"'")
        if not item:
            return
        if _normalized_word_count(item) < 2 and len(item) < 12:
            return
        if item not in candidates:
            candidates.append(item)

    _push(text)
    for line in lines:
        _push(line)

    if prefer_multiline and lines:
        return sorted(candidates, key=lambda value: (-len(value), value.lower()))[:6]

    for match in re.findall(r"[\"“”«»]([^\"“”«»]{8,})[\"“”«»]", text):
        _push(match)

    for part in re.split(r"\s*[,;]\s*", text):
        _push(part)

    meaningful = [token for token in re.findall(r"[a-zA-ZА-Яа-я0-9]+", text) if len(token) >= 3]
    for start in range(len(meaningful)):
        for width in range(4, 9):
            end = start + width
            if end > len(meaningful):
                break
            _push(" ".join(meaningful[start:end]))

    return sorted(candidates, key=lambda value: (-len(value), value.lower()))[:12]


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    from difflib import SequenceMatcher

    return float(SequenceMatcher(None, left, right).ratio())


def _suggestion_by_id(store, suggestion_id: str) -> dict:
    items = store.list_suggestions(state=None)
    for item in items:
        if str(item.get("id", "") or "").strip() == str(suggestion_id or "").strip():
            return item
    return {}
