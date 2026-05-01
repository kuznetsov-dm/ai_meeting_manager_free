from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_EXPECTED_STAGE_ACTION_ERRORS = (
    AttributeError,
    ImportError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class StageActionRequest:
    action: str
    stage_id: str
    provider_id: str


@dataclass(frozen=True)
class StageActionOutcome:
    handled: bool
    level: str = ""
    title: str = ""
    message: str = ""
    rerender_drawer: bool = False
    refresh_pipeline_ui: bool = False


class StageActionFlowController:
    @staticmethod
    def resolve_request(stage_id: str, payload: dict) -> StageActionRequest | None:
        sid = str(stage_id or "").strip()
        if not sid:
            return None
        data = dict(payload or {})
        action_type = str(data.get("type", "") or "").strip()
        if action_type == "refresh_models":
            provider_id = str(data.get("provider_id", "") or "").strip()
            if not provider_id:
                return None
            return StageActionRequest(action="refresh_models", stage_id=sid, provider_id=provider_id)
        return None

    @staticmethod
    def refresh_provider_models(
        stage_id: str,
        plugin_id: str,
        *,
        invalidate_provider_cache: Callable[[str], None],
        refresh_models_from_provider: Callable[[str], tuple[bool, str]],
        is_settings_open_for_stage: Callable[[str], bool],
        tr: Callable[[str, str], str],
        fmt: Callable[..., str],
        log_failure: Callable[[str, str, Exception], None],
    ) -> StageActionOutcome | None:
        sid = str(stage_id or "").strip()
        pid = str(plugin_id or "").strip()
        if not sid or not pid:
            return None
        invalidate_provider_cache(pid)
        try:
            ok, status = refresh_models_from_provider(pid)
            if not ok:
                raise RuntimeError(str(status or "models_refresh_failed"))
            return StageActionOutcome(
                handled=True,
                level="info",
                title=tr("models.refreshed_title", "Available models refreshed"),
                message=fmt(
                    "models.refreshed_message",
                    "Updated available models for {plugin_id}.",
                    plugin_id=pid,
                ),
                rerender_drawer=is_settings_open_for_stage(sid),
                refresh_pipeline_ui=True,
            )
        except _EXPECTED_STAGE_ACTION_ERRORS as exc:
            log_failure(sid, pid, exc)
            return StageActionOutcome(
                handled=True,
                level="warning",
                title=tr("models.refresh_failed_title", "Available model refresh failed"),
                message=fmt(
                    "models.refresh_failed_message",
                    "{plugin_id}: {error}",
                    plugin_id=pid,
                    error=exc,
                ),
                rerender_drawer=is_settings_open_for_stage(sid),
                refresh_pipeline_ui=True,
            )
