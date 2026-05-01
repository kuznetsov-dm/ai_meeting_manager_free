from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(repo_root / "src"))
    os.environ.setdefault("PYTHONPATH", str(repo_root / "src"))

    from aimn.ui.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
