from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    release_root = Path(__file__).resolve().parent
    repo_root = release_root.parents[1]
    os.environ["AIMN_RELEASE_PROFILE"] = "core_free"
    sys.path.insert(0, str(repo_root / "src"))
    os.environ.setdefault("PYTHONPATH", str(repo_root / "src"))

    from aimn.ui.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
