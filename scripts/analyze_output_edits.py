from __future__ import annotations

import sys
from pathlib import Path as _Path

# Allow running the script without installing the package (PYTHONPATH not required).
_REPO_ROOT = _Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
for _p in (str(_SRC), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from aimn.core.services.text_cleanup import cleanup_transcript as _cleanup_transcript
except Exception:  # pragma: no cover
    _cleanup_transcript = None

SCORING_PROFILE = "richer_v1_2026-02-01"


def _cleanup_for_eval(text: str) -> str:
    if not _cleanup_transcript:
        return text or ""
    cleaned, _stats = _cleanup_transcript(text or "")
    return cleaned or ""


RU_STOP = {
    "и",
    "в",
    "во",
    "на",
    "что",
    "это",
    "как",
    "мы",
    "вы",
    "они",
    "он",
    "она",
    "оно",
    "с",
    "со",
    "к",
    "ко",
    "по",
    "за",
    "от",
    "для",
    "из",
    "о",
    "об",
    "про",
    "а",
    "но",
    "не",
    "да",
    "нет",
    "или",
    "ли",
    "бы",
    "то",
    "же",
    "до",
    "у",
    "без",
    "при",
    "через",
    "между",
    "перед",
    "после",
    # conversational fillers
    "вот",
    "ну",
    "так",
    "типа",
    "короче",
    "значит",
    "вообще",
    "просто",
    "сейчас",
    "там",
    "тут",
    "здесь",
    "потом",
    "потому",
    "поэтому",
    "в",
    "принципе",
    "как",
    "бы",
    "то",
    "есть",
    "скажем",
    "допустим",
    "смотрите",
    "понимаешь",
    "знаешь",
    "наверное",
    "конечно",
    "ладно",
    "окей",
    "давай",
    "давайте",
    "ага",
    "угу",
    "мм",
    "э",
}


def _tokenize(text: str) -> list[str]:
    cleaned = str(text or "").lower()
    return re.findall(r"[0-9a-zа-яё]+(?:[-'][0-9a-zа-яё]+)?", cleaned)


def _topic_line(text: str) -> str | None:
    for line in (text or "").splitlines():
        if line.strip().lower().startswith("тема:"):
            return line.split(":", 1)[-1].strip()
    return None


def _safe_div(a: float, b: float) -> float:
    if b <= 1e-9:
        return 0.0
    return float(a / b)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _gauss(x: float, mu: float, sigma: float) -> float:
    # smooth preference curve (0..1)
    if sigma <= 1e-9:
        return 1.0 if abs(x - mu) <= 1e-9 else 0.0
    z = (x - mu) / sigma
    return float(math.exp(-0.5 * z * z))


@dataclass(frozen=True)
class VariantEval:
    meeting_base: str
    meeting_id: str
    transcript_relpath: str
    alias: str
    plugin_id: str
    plugin_version: str
    model_id: str
    edited_relpath: str
    compression_ratio: float
    score: float
    reasons: list[str]
    markers: list[str]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_model_id(params: dict) -> str:
    for k in ("model_id", "embeddings_model_id", "model"):
        v = str(params.get(k, "") or "").strip()
        if v:
            return v
    return "(default)"


def _find_transcript_relpath(meeting: dict) -> str | None:
    tr = str(meeting.get("transcript_relpath", "") or "").strip()
    if tr:
        return tr
    # fallback: try to infer from base_name
    base_name = str(meeting.get("base_name", "") or "").strip()
    if not base_name:
        return None
    # common convention: {base}.transcript.txt
    guess = f"{base_name}.transcript.txt"
    return guess


def _evaluate_variant(*, transcript_text: str, edited_text: str) -> tuple[float, float, list[str], list[str]]:
    reasons: list[str] = []
    markers: list[str] = []

    edited_len = len(edited_text or "")
    tr_len = max(1, len(transcript_text or ""))
    ratio = edited_len / tr_len

    # Structure signals
    has_topic = bool(re.search(r"(?mi)^\s*тема\s*:\s*.+$", edited_text or ""))
    has_ai_exec = "# AI Executive Summary" in (edited_text or "")
    has_summary = bool(re.search(r"(?m)^##\s+Summary\b", edited_text or ""))
    has_actions = bool(re.search(r"(?m)^##\s+Action Items\b", edited_text or ""))
    has_projects = bool(re.search(r"(?m)^##\s+Projects", edited_text or ""))
    has_decisions = bool(re.search(r"(?m)^##\s+Decisions\b", edited_text or ""))
    has_questions = bool(re.search(r"(?m)^##\s+Questions", edited_text or ""))

    section_count = sum([has_summary, has_actions, has_projects, has_decisions, has_questions])
    if has_topic:
        reasons.append("has_topic")
    if section_count:
        reasons.append(f"sections={section_count}")

    # Topic quality (avoid filler-only)
    tline = _topic_line(edited_text or "")
    topic_score = 0.0
    if tline:
        parts = [p.strip() for p in re.split(r"[•|/]+", tline) if p.strip()]
        toks = _tokenize(" ".join(parts))
        if toks:
            stop = sum(1 for t in toks if t in RU_STOP)
            stop_ratio = _safe_div(stop, len(toks))
            # prefer 3-7 tokens, low stopword ratio
            len_score = _gauss(len(toks), mu=5.0, sigma=2.0)
            stop_score = 1.0 - _clamp(stop_ratio, 0.0, 1.0)
            topic_score = 0.6 * len_score + 0.4 * stop_score
            if stop_ratio > 0.5:
                reasons.append("topic_mostly_stopwords")
        else:
            reasons.append("topic_empty")

    # Compression preference (relaxed): good outputs often need room to stay coherent.
    # We still want to avoid near-copies, but we no longer push aggressively for 5-15%.
    if tr_len >= 6000:
        target_mu = 0.28
    elif tr_len >= 2000:
        target_mu = 0.38
    else:
        target_mu = 0.55
    ratio_score = _gauss(ratio, mu=target_mu, sigma=0.18)
    if ratio > 0.80 and tr_len >= 2000:
        reasons.append("too_long_vs_transcript")
    if ratio < 0.03 and tr_len >= 2000:
        reasons.append("too_short_vs_transcript")

    # Bullet hygiene / duplication
    lines = [ln.rstrip() for ln in (edited_text or "").splitlines()]
    bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith(("-", "*"))]
    uniq = len(set(bullet_lines))
    dup_ratio = 1.0 - _safe_div(uniq, len(bullet_lines) or 1)
    dup_score = 1.0 - _clamp(dup_ratio, 0.0, 1.0)

    # Penalize "00:00" spam (often means timestamps are missing, making actions noisy)
    if (edited_text or "").count("(00:00)") >= 5:
        reasons.append("timestamp_spam")
        ts_penalty = 0.25
    else:
        ts_penalty = 0.0

    # Markers to help interpret "model works / doesn't"
    raw = edited_text or ""
    if "(heuristic_fallback)" in raw or "<!-- heuristic_fallback" in raw:
        markers.append("heuristic_fallback")
    if "(lexical_fallback)" in raw or "<!-- lexical_fallback" in raw:
        markers.append("lexical_fallback")

    # Final score (0..10)
    score = 0.0
    score += 2.0 if has_topic else 0.0
    score += 2.0 * _clamp(topic_score, 0.0, 1.0)
    score += 2.0 * _clamp(ratio_score, 0.0, 1.0)
    score += 1.0 * _clamp(dup_score, 0.0, 1.0)
    score += 1.5 if has_actions else 0.0
    score += 1.0 if (has_summary or has_ai_exec) else 0.0
    score += 0.5 * section_count  # prefer more structure, but not too important
    score -= 2.0 * ts_penalty

    # Penalize near-copies (LLM-like edits should compress significantly).
    ratio_penalty = 0.0
    if tr_len >= 1200 and ratio > 0.70:
        ratio_penalty = _clamp((ratio - 0.70) / 0.30, 0.0, 1.0) * 1.5
        score -= ratio_penalty
        reasons.append(f"ratio_penalty={ratio_penalty:.2f}")

    # Penalize over-compression (too short is usually incoherent for non-LLM methods).
    short_penalty = 0.0
    if tr_len >= 1200 and ratio < 0.06:
        short_penalty = _clamp((0.06 - ratio) / 0.06, 0.0, 1.0) * 1.5
        score -= short_penalty
        reasons.append(f"short_penalty={short_penalty:.2f}")

    # Penalize fallbacks (these are not true model outputs).
    if "heuristic_fallback" in markers:
        score -= 2.0
        reasons.append("heuristic_fallback_penalty")
    if "lexical_fallback" in markers:
        score -= 1.0
        reasons.append("lexical_fallback_penalty")

    return float(_clamp(score, 0.0, 10.0)), float(ratio), reasons, markers


def _iter_meetings(output_dir: Path) -> list[Path]:
    return sorted(output_dir.glob("*__MEETING.json"), key=lambda p: p.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Heuristic quality analysis for edited artifacts in ./output.")
    parser.add_argument("--output-dir", type=str, default="output", help="Output dir (default: output).")
    parser.add_argument(
        "--limit-meetings", type=int, default=0, help="Limit number of meetings (0 = all)."
    )
    parser.add_argument(
        "--dedupe-latest",
        action="store_true",
        help="When analyzing meeting manifests (no --batch-report), keep only the latest artifact per (meeting, plugin, model).",
    )
    parser.add_argument(
        "--batch-report",
        type=str,
        default="",
        help="Optional path to edit_variant_report_<batch_id>.jsonl to analyze only that benchmark batch.",
    )
    parser.add_argument(
        "--write",
        type=str,
        default="",
        help="Write Markdown report to this path (default: output/analysis/edit_quality_report_<ts>.md).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (repo_root / args.output_dir).resolve()
    if not output_dir.exists():
        raise SystemExit(f"output_dir_not_found: {output_dir}")

    # Collect evaluations (either from meeting manifests or from a benchmark batch report).
    evals: list[VariantEval] = []
    skipped: list[str] = []

    batch_report_path = str(args.batch_report or "").strip()
    if batch_report_path:
        rp = Path(batch_report_path)
        if not rp.is_absolute():
            rp = (repo_root / rp).resolve()
        if not rp.exists():
            raise SystemExit(f"batch_report_not_found: {rp}")
        for line in rp.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if str(rec.get("status", "") or "").strip() != "success":
                continue
            base_name = str(rec.get("base_name", "") or "").strip()
            meeting_id = str(rec.get("meeting_id", "") or "").strip()
            tr_rel = str(rec.get("transcript_relpath", "") or "").strip()
            edited_rel = str(rec.get("edited_relpath", "") or "").strip()
            plugin_id = str(rec.get("plugin_id", "") or "").strip() or "(unknown)"
            plugin_version = str(rec.get("plugin_version", "") or "").strip() or "unknown"
            model_id = str(rec.get("model_id", "") or "").strip() or "(default)"
            alias = str(rec.get("alias", "") or "").strip() or "(unknown)"
            if not base_name or not tr_rel or not edited_rel:
                skipped.append(base_name or "(unknown)")
                continue
            tr_path = output_dir / tr_rel
            ep = output_dir / edited_rel
            if not tr_path.exists() or not ep.exists():
                skipped.append(base_name)
                continue
            transcript_text = _cleanup_for_eval(tr_path.read_text(encoding="utf-8", errors="ignore"))
            edited_text = ep.read_text(encoding="utf-8", errors="ignore")

            score, ratio, reasons, markers = _evaluate_variant(transcript_text=transcript_text, edited_text=edited_text)
            evals.append(
                VariantEval(
                    meeting_base=base_name,
                    meeting_id=meeting_id,
                    transcript_relpath=tr_rel,
                    alias=alias,
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    model_id=model_id,
                    edited_relpath=edited_rel,
                    compression_ratio=ratio,
                    score=score,
                    reasons=reasons,
                    markers=markers,
                )
            )
    else:
        meeting_paths = _iter_meetings(output_dir)
        if args.limit_meetings and args.limit_meetings > 0:
            meeting_paths = meeting_paths[: args.limit_meetings]

        latest_candidates: dict[tuple[str, str, str], dict] = {}
        for mp in meeting_paths:
            try:
                meeting = _load_json(mp)
            except Exception:
                skipped.append(mp.name)
                continue

            base_name = str(meeting.get("base_name", "") or "").strip() or mp.name.replace("__MEETING.json", "")
            meeting_id = str(meeting.get("meeting_id", "") or "").strip()
            tr_rel = _find_transcript_relpath(meeting)
            if not tr_rel:
                skipped.append(base_name)
                continue
            tr_path = output_dir / tr_rel
            if not tr_path.exists():
                skipped.append(base_name)
                continue
            transcript_text = _cleanup_for_eval(tr_path.read_text(encoding="utf-8", errors="ignore"))

            nodes = meeting.get("nodes", {})
            if not isinstance(nodes, dict):
                skipped.append(base_name)
                continue

            for alias, node in nodes.items():
                if not isinstance(node, dict):
                    continue
                if str(node.get("stage_id", "") or "").strip() != "text_processing":
                    continue

                tool = node.get("tool", {}) if isinstance(node.get("tool"), dict) else {}
                plugin_id = str(tool.get("plugin_id", "") or "").strip()
                plugin_version = str(tool.get("version", "") or "").strip() or "unknown"
                params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
                model_id = _infer_model_id(params)
                node_created_at = str(node.get("created_at", "") or "").strip()

                artifacts = node.get("artifacts", [])
                if not isinstance(artifacts, list):
                    continue
                for art in artifacts:
                    if not isinstance(art, dict):
                        continue
                    if str(art.get("kind", "") or "").strip() != "edited":
                        continue
                    rel = str(art.get("path", "") or "").strip()
                    if not rel:
                        continue
                    ep = output_dir / rel
                    if not ep.exists():
                        continue
                    if args.dedupe_latest:
                        key = (base_name, plugin_id or "(unknown)", model_id)
                        existing = latest_candidates.get(key)
                        if existing is None or node_created_at > str(existing.get("created_at", "") or ""):
                            latest_candidates[key] = {
                                "created_at": node_created_at,
                                "meeting_base": base_name,
                                "meeting_id": meeting_id,
                                "transcript_relpath": tr_rel,
                                "alias": str(alias),
                                "plugin_id": plugin_id or "(unknown)",
                                "plugin_version": plugin_version,
                                "model_id": model_id,
                                "edited_relpath": rel,
                            }
                        continue

                    edited_text = ep.read_text(encoding="utf-8", errors="ignore")
                    score, ratio, reasons, markers = _evaluate_variant(
                        transcript_text=transcript_text, edited_text=edited_text
                    )
                    evals.append(
                        VariantEval(
                            meeting_base=base_name,
                            meeting_id=meeting_id,
                            transcript_relpath=tr_rel,
                            alias=str(alias),
                            plugin_id=plugin_id or "(unknown)",
                            plugin_version=plugin_version,
                            model_id=model_id,
                            edited_relpath=rel,
                            compression_ratio=ratio,
                            score=score,
                            reasons=reasons,
                            markers=markers,
                        )
                    )

        if args.dedupe_latest:
            for cand in latest_candidates.values():
                ep = output_dir / str(cand["edited_relpath"])
                tr_path = output_dir / str(cand["transcript_relpath"])
                if not ep.exists() or not tr_path.exists():
                    continue
                transcript_text = _cleanup_for_eval(tr_path.read_text(encoding="utf-8", errors="ignore"))
                edited_text = ep.read_text(encoding="utf-8", errors="ignore")
                score, ratio, reasons, markers = _evaluate_variant(
                    transcript_text=transcript_text, edited_text=edited_text
                )
                evals.append(
                    VariantEval(
                        meeting_base=str(cand["meeting_base"]),
                        meeting_id=str(cand["meeting_id"]),
                        transcript_relpath=str(cand["transcript_relpath"]),
                        alias=str(cand["alias"]),
                        plugin_id=str(cand["plugin_id"]),
                        plugin_version=str(cand["plugin_version"]),
                        model_id=str(cand["model_id"]),
                        edited_relpath=str(cand["edited_relpath"]),
                        compression_ratio=ratio,
                        score=score,
                        reasons=reasons,
                        markers=markers,
                    )
                )

    if not evals:
        raise SystemExit("no_edited_variants_found")

    # Best per meeting
    best_by_meeting: dict[str, VariantEval] = {}
    for ev in evals:
        prev = best_by_meeting.get(ev.meeting_base)
        if prev is None or ev.score > prev.score:
            best_by_meeting[ev.meeting_base] = ev

    # Aggregate per plugin+model
    agg: dict[tuple[str, str], dict] = {}
    for ev in evals:
        key = (ev.plugin_id, ev.model_id)
        item = agg.setdefault(
            key,
            {
                "plugin_id": ev.plugin_id,
                "model_id": ev.model_id,
                "runs": 0,
                "wins": 0,
                "score_sum": 0.0,
                "ratio_sum": 0.0,
                "fallback_heuristic": 0,
                "fallback_lexical": 0,
            },
        )
        item["runs"] += 1
        item["score_sum"] += float(ev.score)
        item["ratio_sum"] += float(ev.compression_ratio)
        if "heuristic_fallback" in ev.markers:
            item["fallback_heuristic"] += 1
        if "lexical_fallback" in ev.markers:
            item["fallback_lexical"] += 1

    for best in best_by_meeting.values():
        agg[(best.plugin_id, best.model_id)]["wins"] += 1

    rows = []
    for key, item in agg.items():
        runs = int(item["runs"])
        rows.append(
            {
                **item,
                "avg_score": float(item["score_sum"] / max(1, runs)),
                "avg_ratio": float(item["ratio_sum"] / max(1, runs)),
                "win_rate": float(item["wins"] / max(1, len(best_by_meeting))),
            }
        )

    rows.sort(key=lambda r: (r["wins"], r["avg_score"]), reverse=True)

    # Pick top 3 by wins then avg_score
    top3 = rows[:3]

    # Produce markdown report
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    default_report_path = output_dir / "analysis" / f"edit_quality_report_{ts}.md"
    report_path = Path(args.write).expanduser() if args.write else default_report_path
    if not report_path.is_absolute():
        report_path = (repo_root / report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    sample_meetings = list(sorted(best_by_meeting.values(), key=lambda e: e.score, reverse=True))[:3]
    weak_meetings = list(sorted(best_by_meeting.values(), key=lambda e: e.score))[:3]

    def _fmt_row(r: dict) -> str:
        return (
            f"- {r['plugin_id']} | {r['model_id']}\n"
            f"  - wins: {r['wins']}/{len(best_by_meeting)} | avg_score: {r['avg_score']:.2f} | avg_ratio: {r.get('avg_ratio', 0.0):.3f}\n"
            f"  - fallbacks: heuristic={r['fallback_heuristic']}, lexical={r['fallback_lexical']} (markers only)\n"
        )

    # "How I'd do it" - concise reference format and one small example from a short transcript if available.
    example_block = ""
    # pick the shortest transcript among sampled meetings to keep report readable
    best_sorted = sorted(best_by_meeting.values(), key=lambda e: (e.meeting_base))
    chosen = None
    for ev in best_sorted:
        tr = output_dir / ev.transcript_relpath
        if tr.exists():
            txt = tr.read_text(encoding="utf-8", errors="ignore").strip()
            if 200 <= len(txt) <= 1500:
                chosen = (ev, txt)
                break
    if chosen:
        ev, txt = chosen
        snippet = txt.replace("\n", " ").strip()
        snippet = snippet[:900] + ("…" if len(snippet) > 900 else "")
        example_block = (
            "\n"
            "Example (reference style, handcrafted):\n\n"
            "Input transcript snippet:\n\n"
            f"> {snippet}\n\n"
            "Reference edited (what we aim for):\n\n"
            "```\n"
            "ТЕМА: <2-6 ключевых слов без стоп-слов>\n\n"
            "## Summary\n"
            "- 3-7 bullets: что произошло / к чему пришли / контекст\n\n"
            "## Action Items\n"
            "- [ ] <кто?> <что?> <до когда?>\n\n"
            "## Decisions\n"
            "- <принятое решение>\n\n"
            "## Open Questions / Risks\n"
            "- <вопрос/риск> (owner)\n"
            "```\n"
        )

    md = []
    md.append(f"# Edit quality report ({ts} UTC)\n")
    md.append(f"Scoring profile: `{SCORING_PROFILE}`\n")
    md.append(f"Output dir: `{output_dir}`\n")
    md.append(f"Meetings analyzed (with best picked): {len(best_by_meeting)}\n")
    md.append(f"Variants analyzed: {len(evals)}\n")
    if skipped:
        md.append(f"Skipped meetings (missing/invalid transcript or manifest): {len(skipped)}\n")

    md.append("## Final recommendation (top 10)\n")
    ranked = rows[:10]
    if ranked:
        for idx, r in enumerate(ranked, start=1):
            md.append(f"### #{idx}\n")
            md.append(_fmt_row(r))

    md.append("## Why these win (what the scoring prefers)\n")
    md.append(
        "- topic line present and not dominated by filler words\n"
        "- structured sections (Summary / Action Items / Decisions / Questions)\n"
        "- enough content to be coherent (not over-compressed), but not a near-copy\n"
        "- fewer duplicated bullets / less timestamp spam\n"
    )

    md.append("## Best per meeting (top 3 examples)\n")
    for ev in sample_meetings:
        md.append(
            f"- `{ev.meeting_base}`\n"
            f"  - best: {ev.plugin_id} | {ev.model_id} | alias={ev.alias} | score={ev.score:.2f}\n"
            f"  - transcript: `{ev.transcript_relpath}`\n"
            f"  - edited: `{ev.edited_relpath}`\n"
        )

    md.append("## Worst per meeting (bottom 3 examples)\n")
    for ev in weak_meetings:
        md.append(
            f"- `{ev.meeting_base}`\n"
            f"  - best_of_bad: {ev.plugin_id} | {ev.model_id} | alias={ev.alias} | score={ev.score:.2f}\n"
            f"  - transcript: `{ev.transcript_relpath}`\n"
            f"  - edited: `{ev.edited_relpath}`\n"
            f"  - reasons: {', '.join(ev.reasons[:8])}\n"
        )

    md.append("## How I would process transcripts (target behavior)\n")
    md.append(
        "- aggressively remove conversational filler and repeated confirmations\n"
        "- normalize terminology (product/category/ticket/status), preserve IDs/SKU\n"
        "- extract explicit action items (owner + verb + object + deadline) and decisions\n"
        "- keep 1-2 levels of hierarchy: Summary -> Sections -> Bullets\n"
        "- keep user-visible output readable; avoid over-compression into incoherent fragments\n"
    )
    if example_block:
        md.append(example_block)

    md.append("## Improvement ideas (actionable)\n")
    md.append(
        "- Add a stronger RU stopword list for topic generation; forbid topic tokens like 'так', 'вот', 'тогда', 'сейчас', 'давайте'.\n"
        "- Improve sentence splitting for ASR transcripts with little punctuation: prefer chunking by speaker turns / pauses if segments exist.\n"
        "- Filter action items: require imperative verbs or explicit ownership; drop generic phrases ('давайте начнем').\n"
        "- Add a 'best selector' stage that chooses 1 best edited from multiple variants and marks it user_visible; hide others.\n"
        "- Ensure embeddings models load offline deterministically (no network probes): use local_files_only / snapshot paths.\n"
    )

    report_path.write_text("".join(md), encoding="utf-8")

    # Also write a machine-readable summary next to it
    summary_path = report_path.with_suffix(".json")
    summary_path.write_text(
        json.dumps(
            {
                "generated_at_utc": ts,
                "scoring_profile": SCORING_PROFILE,
                "output_dir": str(output_dir),
                "meetings": len(best_by_meeting),
                "variants": len(evals),
                "top3": top3,
                "top10": rows[:10],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"wrote: {report_path}")
    print(f"wrote: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
