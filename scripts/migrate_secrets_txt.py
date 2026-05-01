from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z0-9_.-]+)\s*(=|:)\s*(.*?)\s*$")


def _strip_quotes(value: str) -> str:
    raw = (value or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1].strip()
    return raw


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        key = str(m.group(1) or "").strip()
        value = _strip_quotes(str(m.group(3) or ""))
        if not key or not value:
            continue
        out[key] = value
    return out


def _dump_flat_toml(data: dict[str, object]) -> str:
    lines = ["# Local secrets (do not commit)"]
    for key in sorted(data.keys()):
        value = data[key]
        if isinstance(value, bool):
            encoded = "true" if value else "false"
        elif isinstance(value, (int, float)):
            encoded = str(value)
        else:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            encoded = f"\"{escaped}\""
        lines.append(f"{key} = {encoded}")
    return "\n".join(lines) + "\n"


def _load_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(raw) if raw.strip() else {}
    return parsed if isinstance(parsed, dict) else {}


def _pick_source(kv: dict[str, str], candidates: list[str]) -> tuple[str, str] | None:
    lower = {str(k).strip().lower(): k for k in kv.keys()}
    for cand in candidates:
        if not cand:
            continue
        direct = kv.get(cand)
        if direct:
            return cand, direct
        key = lower.get(cand.strip().lower())
        if key and kv.get(key):
            return key, kv[key]
    return None


def _migrate(in_path: Path, out_path: Path) -> list[str]:
    kv = _parse_kv(in_path.read_text(encoding="utf-8", errors="ignore"))
    data = _load_toml(out_path)

    updates: list[tuple[str, str, str]] = []
    rules: list[tuple[str, list[str]]] = [
        (
            "zai_api_key",
            [
                "zai_api_key",
                "ZAI_API_KEY",
                "AIMN_ZAI_API_KEY",
                "aimn_zai_api_key",
                "zai_key",
                "ZAI_KEY",
            ],
        ),
        (
            "openrouter_api_key",
            [
                "openrouter_api_key",
                "OPENROUTER_API_KEY",
                "openrouter_user_api_key",
                "OPENROUTER_USER_API_KEY",
                "AIMN_OPENROUTER_API_KEY",
                "AIMN_OPENROUTER_USER_KEY",
                "AIMN_OPENROUTER_USER_API_KEY",
                "AIMN_OPENROUTER_FREE_KEY",
                "aimn_openrouter_user_key",
            ],
        ),
        (
            "deepseek_api_key",
            [
                "deepseek_api_key",
                "AIMN_DEEPSEEK_API_KEY",
                "deepseek_user_api_key",
                "DEEPSEEK_USER_API_KEY",
                "DEEPSEEK_API_KEY",
                "AIMN_DEEPSEEK_USER_API_KEY",
                "AIMN_DEEPSEEK_PAID_KEY",
                "aimn_deepseek_user_api_key",
            ],
        ),
    ]

    for out_key, candidates in rules:
        picked = _pick_source(kv, candidates)
        if not picked:
            continue
        src_key, value = picked
        if not value:
            continue
        data[out_key] = str(value)
        updates.append((out_key, src_key, "<redacted>"))

    if updates:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_dump_flat_toml(data), encoding="utf-8")

    return [f"{out_key} <= {src_key}" for out_key, src_key, _ in updates]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", required=True)
    parser.add_argument("--out", dest="out_path", required=True)
    parser.add_argument("--delete-input", action="store_true")
    args = parser.parse_args(argv)

    in_path = Path(args.in_path).resolve()
    out_path = Path(args.out_path).resolve()

    if not in_path.exists():
        print("secrets input missing", file=sys.stderr)
        return 2

    updated = _migrate(in_path, out_path)
    if updated:
        print("updated:")
        for line in updated:
            print(f"- {line}")
    else:
        print("no changes")

    if args.delete_input:
        try:
            in_path.unlink()
            print("deleted input secrets.txt")
        except Exception as exc:
            print(f"failed to delete input: {exc}", file=sys.stderr)
            return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
