from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from aimn.core.contracts import ActionResult
from aimn.core.plugin_dependency_runtime import resolve_plugin_python


def run_action_subprocess(
    repo_root: Path,
    plugin_id: str,
    action_id: str,
    params: dict,
    settings_override: dict | None = None,
) -> ActionResult:
    payload = {
        "repo_root": str(repo_root),
        "plugin_id": plugin_id,
        "action_id": action_id,
        "params": params or {},
        "settings_override": settings_override,
    }
    env = dict(os.environ)
    env["AIMN_ACTION_ISOLATION"] = "0"
    env["AIMN_ACTION_FORCE_SYNC"] = "1"
    timeout_seconds = int(os.environ.get("AIMN_ACTION_TIMEOUT_SECONDS", "120") or 120)
    python_exe = resolve_plugin_python(repo_root, plugin_id)
    try:
        proc = subprocess.run(
            [python_exe, "-m", "aimn.core.action_cli"],
            input=json.dumps(payload, ensure_ascii=True),
            text=True,
            capture_output=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ActionResult(status="error", message="action_isolation_timeout")
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "action_isolation_failed"
        return ActionResult(status="error", message=message)
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except Exception:
        return ActionResult(status="error", message="action_isolation_invalid_response")
    if isinstance(data, dict):
        return ActionResult(
            status=str(data.get("status", "error")),
            message=str(data.get("message", "")),
            data=data.get("data"),
            job_id=data.get("job_id"),
            warnings=[str(w) for w in data.get("warnings", []) if str(w)],
        )
    return ActionResult(status="error", message="action_isolation_invalid_payload")
