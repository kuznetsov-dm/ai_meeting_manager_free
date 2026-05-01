from __future__ import annotations

import re
import sys
from pathlib import Path


TOKENS = [
    "whisper",
    "openrouter",
    "deepseek",
    "llama",
    "ollama",
]

ALLOW_PATTERNS = [
    re.compile(r"\bwhisper_json\b", re.IGNORECASE),
    re.compile(r"\bsegments_from_whisper_json\b", re.IGNORECASE),
]


def _is_allowed(line: str) -> bool:
    return any(pattern.search(line) for pattern in ALLOW_PATTERNS)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    core_root = repo_root / "src" / "aimn" / "core"
    if not core_root.exists():
        print("core_dir_missing")
        return 2

    token_patterns = [re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE) for token in TOKENS]
    violations = []

    for path in core_root.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line_num, line in enumerate(text.splitlines(), start=1):
            for token, pattern in zip(TOKENS, token_patterns):
                match = pattern.search(line)
                if not match:
                    continue
                if _is_allowed(line):
                    continue
                col = match.start() + 1
                rel = path.relative_to(repo_root)
                violations.append(f"{rel}:{line_num}:{col}: {token}")

    if violations:
        print("provider_name_lint_failed")
        for item in violations:
            print(item)
        return 1

    print("provider_name_lint_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
