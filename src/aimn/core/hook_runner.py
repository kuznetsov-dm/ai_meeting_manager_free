from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from aimn.core.contracts import PluginOutput, PluginResult
from aimn.core.plugin_dependency_runtime import resolve_plugin_python
from aimn.core.plugin_services import HookExecution


def run_hook_subprocess(
    repo_root: Path,
    plugin_id: str,
    hook_name: str,
    payload: dict,
) -> HookExecution:
    payload = dict(payload)
    payload.update(
        {
            "repo_root": str(repo_root),
            "plugin_id": plugin_id,
            "hook_name": hook_name,
        }
    )
    timeout_seconds = int(os.environ.get("AIMN_HOOK_TIMEOUT_SECONDS", "300") or 300)
    python_exe = resolve_plugin_python(repo_root, plugin_id)
    try:
        proc = subprocess.run(
            [python_exe, "-m", "aimn.core.hook_cli"],
            input=json.dumps(payload, ensure_ascii=True),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return HookExecution(
            plugin_id=plugin_id,
            handler_id="isolated",
            result=None,
            error="hook_isolation_timeout",
            mode="optional",
        )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "hook_isolation_failed"
        return HookExecution(
            plugin_id=plugin_id,
            handler_id="isolated",
            result=None,
            error=message,
            mode="optional",
        )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return HookExecution(
            plugin_id=plugin_id,
            handler_id="isolated",
            result=None,
            error="hook_isolation_invalid_response",
            mode="optional",
        )
    if data.get("status") != "ok":
        return HookExecution(
            plugin_id=plugin_id,
            handler_id="isolated",
            result=None,
            error=str(data.get("message", "hook_isolation_failed")),
            mode="optional",
        )
    execution = data.get("execution") if isinstance(data, dict) else None
    if not isinstance(execution, dict):
        return HookExecution(
            plugin_id=plugin_id,
            handler_id="isolated",
            result=None,
            error="hook_isolation_empty",
            mode="optional",
        )
    result = _deserialize_result(execution.get("result"))
    return HookExecution(
        plugin_id=str(execution.get("plugin_id", plugin_id)),
        handler_id=str(execution.get("handler_id", "isolated")),
        result=result,
        error=execution.get("error"),
        mode=str(execution.get("mode", "optional")),
    )


def _deserialize_result(payload: object) -> PluginResult | None:
    if not isinstance(payload, dict):
        return None
    outputs: list[PluginOutput] = []
    for output in payload.get("outputs", []) if isinstance(payload.get("outputs"), list) else []:
        if not isinstance(output, dict):
            continue
        outputs.append(
            PluginOutput(
                kind=str(output.get("kind", "")),
                content=str(output.get("content", "")),
                content_type=str(output.get("content_type", "")),
                user_visible=bool(output.get("user_visible", True)),
            )
        )
    warnings = [str(item) for item in payload.get("warnings", []) if str(item)]
    return PluginResult(outputs=outputs, warnings=warnings)
