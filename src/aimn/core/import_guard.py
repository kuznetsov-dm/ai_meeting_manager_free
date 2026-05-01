from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, List


def ensure_core_does_not_import_plugins(repo_root: Path) -> None:
    core_dir = repo_root / "src" / "aimn" / "core"
    violations = _scan_forbidden_imports(core_dir)
    if violations:
        details = ", ".join(violations)
        raise RuntimeError(f"aimn.core imports plugins modules: {details}")


def _scan_forbidden_imports(root: Path) -> List[str]:
    matches: List[str] = []
    if not root.exists():
        return matches
    for path in root.rglob("*.py"):
        matches.extend(_file_violations(path))
    return matches


def _file_violations(path: Path) -> Iterable[str]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden(alias.name):
                    yield f"{path}:{alias.name}"
        if isinstance(node, ast.ImportFrom):
            if node.module and _is_forbidden(node.module):
                yield f"{path}:{node.module}"


def _is_forbidden(module: str) -> bool:
    return module == "plugins" or module.startswith("plugins.")
