from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


_ROOT = _bundle_root()
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aimn.ui.app import run


def main() -> int:
    os.environ["AIMN_RELEASE_PROFILE"] = "core_free"
    os.environ.setdefault("AIMN_BUNDLE_ROOT", str(_ROOT))
    os.environ.setdefault("PYTHONPATH", str(_SRC))
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
