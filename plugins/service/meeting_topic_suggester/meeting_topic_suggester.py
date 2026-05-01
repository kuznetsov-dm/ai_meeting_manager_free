from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aimn.plugins.interfaces import ActionDescriptor, ActionResult

_TOPIC_LINE_RE = re.compile(
    r"^\s{0,3}(?:[#>*-]+\s*)?(?:meeting\s+topic|topic|theme|тема(?:\s+встречи)?)\s*[:\-]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_TOPICS_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(topics?|themes?)\b", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_TOPIC_KEYS = {"topic", "topics", "theme", "themes", "meeting_topic", "meeting_topics", "тема"}
_KIND_WEIGHTS = {
    "edited": 3,
    "summary": 2,
    "decisions": 1,
    "actions": 1,
}


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_actions(_actions)


def _actions() -> list[ActionDescriptor]:
    return [
        ActionDescriptor(
            action_id="suggest_topics",
            label="Suggest meeting topics",
            description="Extract meeting topic suggestions from AI artifacts for rename flow.",
            params_schema={
                "fields": [
                    {"key": "base_name", "label": "Meeting base name", "type": "string", "required": True},
                    {"key": "meeting_id", "label": "Meeting ID", "type": "string"},
                    {"key": "limit", "label": "Max suggestions", "type": "number"},
                ]
            },
            handler=action_suggest_topics,
        )
    ]


def action_suggest_topics(_settings: dict, params: dict) -> ActionResult:
    base_name = str(
        params.get("base_name")
        or params.get("meeting_base_name")
        or params.get("meeting")
        or ""
    ).strip()
    if not base_name:
        return ActionResult(status="error", message="missing_base_name")

    limit = _coerce_limit(params.get("limit"), default=8)
    app_root = resolve_app_root()
    output_dir = app_root / "output"
    meeting_path = output_dir / f"{base_name}__MEETING.json"
    if not meeting_path.exists():
        return ActionResult(status="error", message="meeting_manifest_not_found")

    try:
        manifest = json.loads(meeting_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ActionResult(status="error", message=f"meeting_manifest_invalid:{exc}")
    if not isinstance(manifest, dict):
        return ActionResult(status="error", message="meeting_manifest_invalid")

    ranked = _collect_ranked_topics(manifest, output_dir)
    if not ranked:
        fallback = _fallback_from_manifest(manifest)
        ranked = [(fallback, 1, "fallback")] if fallback else []

    items = [
        {"title": title, "score": score, "source": source}
        for title, score, source in ranked[:limit]
    ]
    return ActionResult(
        status="ok",
        message="ok" if items else "empty",
        data={
            "base_name": base_name,
            "meeting_id": str(manifest.get("meeting_id", "") or ""),
            "suggestions": items,
        },
    )


def _collect_ranked_topics(manifest: dict, output_dir: Path) -> list[tuple[str, int, str]]:
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    source_by_key: dict[str, str] = {}
    title_by_key: dict[str, str] = {}
    order = 0

    for relpath, kind in _candidate_artifacts(manifest):
        path = (output_dir / relpath).resolve()
        if not str(path).startswith(str(output_dir.resolve())):
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
        except Exception:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        topics = _extract_topics_from_text(text)
        if not topics:
            continue
        weight = int(_KIND_WEIGHTS.get(kind, 1))
        source = kind or "artifact"
        for topic in topics:
            key = _topic_key(topic)
            if not key:
                continue
            counts[key] += weight
            if key not in first_seen:
                first_seen[key] = order
                order += 1
                source_by_key[key] = source
                title_by_key[key] = topic

    ranked: list[tuple[str, int, str]] = []
    for key, score in counts.items():
        title = title_by_key.get(key, key)
        ranked.append((title, int(score), source_by_key.get(key, "artifact")))
    ranked.sort(key=lambda item: (-item[1], first_seen.get(_topic_key(item[0]), 9999), item[0]))
    return ranked


def _candidate_artifacts(manifest: dict) -> Iterable[tuple[str, str]]:
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        return []

    selected_aliases: list[str] = []
    pinned = manifest.get("pinned_aliases")
    if isinstance(pinned, dict):
        alias = str(pinned.get("llm_processing", "") or "").strip()
        if alias:
            selected_aliases.append(alias)

    llm_aliases: list[tuple[str, str]] = []
    for alias, raw in nodes.items():
        if not isinstance(raw, dict):
            continue
        if str(raw.get("stage_id", "")).strip() != "llm_processing":
            continue
        created = str(raw.get("created_at", "") or "")
        llm_aliases.append((str(alias), created))
    llm_aliases.sort(key=lambda item: item[1], reverse=True)
    selected_aliases.extend([alias for alias, _created in llm_aliases if alias not in selected_aliases])

    out: list[tuple[str, str]] = []
    for alias in selected_aliases:
        node = nodes.get(alias)
        if not isinstance(node, dict):
            continue
        artifacts = node.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            relpath = str(item.get("path", "") or "").strip()
            kind = str(item.get("kind", "") or "").strip().lower()
            if not relpath:
                continue
            if kind and kind not in {"edited", "summary", "decisions", "actions"}:
                continue
            out.append((relpath, kind))
    return out


def _extract_topics_from_text(text: str) -> list[str]:
    raw = str(text or "")
    if not raw.strip():
        return []

    topics: list[str] = []
    for line in raw.splitlines():
        m = _TOPIC_LINE_RE.match(line)
        if not m:
            continue
        topic = _clean_topic(m.group(1))
        if topic:
            topics.append(topic)

    lines = raw.splitlines()
    in_topics_section = False
    for line in lines:
        stripped = line.strip()
        if _TOPICS_HEADING_RE.match(stripped):
            in_topics_section = True
            continue
        if in_topics_section and stripped.startswith("#"):
            break
        if not in_topics_section:
            continue
        bullet = _BULLET_RE.match(stripped)
        if not bullet:
            continue
        topic = _clean_topic(bullet.group(1))
        if topic:
            topics.append(topic)

    for topic in _extract_topics_from_json_like(raw):
        cleaned = _clean_topic(topic)
        if cleaned:
            topics.append(cleaned)

    return _dedupe_topics(topics, limit=16)


def _extract_topics_from_json_like(text: str) -> list[str]:
    candidate = str(text or "").strip()
    if not candidate or candidate[0] not in "{[":
        return []
    try:
        payload = json.loads(candidate)
    except Exception:
        return []
    values: list[str] = []
    _collect_topics_from_object(payload, values)
    return values


def _collect_topics_from_object(value: Any, out: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_norm = _topic_key(str(key or ""))
            if key_norm in _TOPIC_KEYS:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, list):
                    for entry in item:
                        if isinstance(entry, str):
                            out.append(entry)
            _collect_topics_from_object(item, out)
        return
    if isinstance(value, list):
        for item in value:
            _collect_topics_from_object(item, out)


def _fallback_from_manifest(manifest: dict) -> str:
    display_title = str(manifest.get("display_title", "") or "").strip()
    if display_title:
        return display_title
    base_name = str(manifest.get("base_name", "") or "").strip()
    if not base_name:
        return ""
    if "_" in base_name:
        return base_name.split("_", 1)[1].replace("_", " ").strip()
    return base_name


def _clean_topic(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = text.strip(" -:;,.")
    if not text:
        return ""
    if len(text) > 140:
        text = text[:140].rstrip()
    return text


def _dedupe_topics(values: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = _topic_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
        if len(out) >= limit:
            break
    return out


def _topic_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _coerce_limit(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(parsed, 20))


def resolve_app_root() -> Path:
    raw = os.environ.get("AIMN_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[3]
