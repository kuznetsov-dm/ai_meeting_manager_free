from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EditedVariant:
    alias: str
    stage_id: str
    plugin_id: str
    relpath: str
    text: str


def _tokenize(text: str) -> list[str]:
    cleaned = str(text or "").lower()
    return re.findall(r"[0-9a-zа-яё]+(?:[-'][0-9a-zа-яё]+)?", cleaned)


def _tf(tokens: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in tokens:
        out[t] = out.get(t, 0.0) + 1.0
    return out


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, av in a.items():
        bv = b.get(k)
        if bv is not None:
            dot += av * bv
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return float(dot / (na * nb))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return float(inter / max(1, union))


def _find_default_meeting(repo_root: Path) -> Path | None:
    out_dir = repo_root / "output"
    if not out_dir.exists():
        return None
    files = sorted(out_dir.glob("*_MEETING.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _load_variants(meeting_path: Path) -> list[EditedVariant]:
    base_dir = meeting_path.parent
    data = json.loads(meeting_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", {}) if isinstance(data, dict) else {}
    out: list[EditedVariant] = []
    if not isinstance(nodes, dict):
        return out
    for alias, node in nodes.items():
        if not isinstance(node, dict):
            continue
        stage_id = str(node.get("stage_id", "") or "").strip()
        plugin_id = str(node.get("plugin_id", "") or "").strip()
        artifacts = node.get("artifacts", [])
        if not isinstance(artifacts, list):
            continue
        for art in artifacts:
            if not isinstance(art, dict):
                continue
            if str(art.get("kind", "") or "").strip() != "edited":
                continue
            relpath = str(art.get("path", "") or "").strip()
            if not relpath:
                continue
            path = base_dir / relpath
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            out.append(
                EditedVariant(
                    alias=str(alias),
                    stage_id=stage_id,
                    plugin_id=plugin_id,
                    relpath=relpath,
                    text=text,
                )
            )
    return out


def _print_matrix(labels: list[str], values: list[list[float]], *, title: str) -> None:
    width = max(10, min(40, max((len(x) for x in labels), default=10)))
    print("")
    print(title)
    header = " " * (width + 2) + " ".join([f"{i:>6d}" for i in range(len(labels))])
    print(header)
    for i, label in enumerate(labels):
        row = " ".join([f"{values[i][j]:6.2f}" for j in range(len(labels))])
        print(f"{label[:width]:<{width}}  {row}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Compare 'edited' outputs for a meeting.")
    parser.add_argument(
        "--meeting",
        type=str,
        default="",
        help="Path to *_MEETING.json (defaults to newest under ./output).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    meeting_path = Path(args.meeting).expanduser() if args.meeting else None
    if meeting_path and not meeting_path.is_absolute():
        meeting_path = (repo_root / meeting_path).resolve()
    if not meeting_path:
        meeting_path = _find_default_meeting(repo_root)
    if not meeting_path or not meeting_path.exists():
        print("meeting_not_found")
        return 2

    variants = _load_variants(meeting_path)
    if not variants:
        print(f"no_edited_variants_found: {meeting_path}")
        return 0

    labels: list[str] = []
    sets: list[set[str]] = []
    tfs: list[dict[str, float]] = []
    for v in variants:
        label = f"{len(labels)}:{v.alias}:{v.plugin_id}".strip(":")
        labels.append(label)
        tokens = _tokenize(v.text)
        sets.append(set(tokens))
        tfs.append(_tf(tokens))

    n = len(labels)
    jac: list[list[float]] = [[0.0] * n for _ in range(n)]
    cos: list[list[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                jac[i][j] = 1.0
                cos[i][j] = 1.0
            else:
                jac[i][j] = _jaccard(sets[i], sets[j])
                cos[i][j] = _cosine(tfs[i], tfs[j])

    print(f"Meeting: {meeting_path}")
    print("Variants:")
    for i, v in enumerate(variants):
        print(f"- {i}: alias={v.alias} stage={v.stage_id} plugin={v.plugin_id} path={v.relpath}")

    _print_matrix(labels, jac, title="Jaccard similarity (token sets)")
    _print_matrix(labels, cos, title="Cosine similarity (term frequency)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

