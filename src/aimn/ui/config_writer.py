from __future__ import annotations

import json
from typing import Dict


def dumps_plugins_config(data: Dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
