from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_MEETING_STORAGE_ERRORS = (FileNotFoundError, OSError, RuntimeError, ValueError)


@dataclass(frozen=True)
class MeetingDeleteFlowCallbacks:
    load_meeting: Callable[[str], object]
    is_active_base: Callable[[str], bool]
    clear_audio_path: Callable[[], None]
    confirm_delete: Callable[[], bool]
    cleanup_meeting_for_delete: Callable[[str], bool]
    delete_meeting_files: Callable[[str], None]
    clear_meeting_states: Callable[[str], None]
    invalidate_payload_cache: Callable[[str], None]
    clear_active_meeting: Callable[[], None]
    refresh_history: Callable[[], None]
    refresh_pipeline_ui: Callable[[], None]
    log_delete_preview_error: Callable[[str, Exception], None]
    log_clear_audio_error: Callable[[str, Exception], None]


@dataclass(frozen=True)
class MeetingRenameFlowCallbacks:
    load_meeting: Callable[[str], object]
    meeting_display_title: Callable[[object], str]
    meeting_topic_suggestions: Callable[[str, object], list[str]]
    prompt_new_title: Callable[[str, list[str]], str]
    rename_policy: Callable[[], tuple[str, bool]]
    confirm_source_rename: Callable[[], bool]
    is_active_base: Callable[[str], bool]
    is_last_stage_base: Callable[[str], bool]
    clear_audio_path: Callable[[], None]
    rename_meeting: Callable[[str, str, str, bool], str]
    set_active_meeting_base: Callable[[str], None]
    set_last_stage_base: Callable[[str], None]
    invalidate_payload_cache: Callable[[str], None]
    refresh_history: Callable[[str], None]
    refresh_pipeline_ui: Callable[[], None]
    warn_load_failed: Callable[[Exception], None]
    warn_target_exists: Callable[[Exception], None]
    warn_source_not_allowed: Callable[[Exception], None]
    warn_generic: Callable[[Exception], None]


@dataclass(frozen=True)
class MeetingRerunFlowCallbacks:
    prompt_stage: Callable[[], object]
    runtime_stage_id_for_ui: Callable[[str], str]
    start_pipeline: Callable[[str, str, bool], None]


@dataclass(frozen=True)
class MeetingRerunSelection:
    stage_id: str = ""
    force_replace_downstream: bool = False


@dataclass(frozen=True)
class MeetingExportFlowCallbacks:
    warn_no_targets: Callable[[], None]
    choose_target: Callable[[list[dict[str, object]]], dict[str, object] | None]
    choose_mode: Callable[[], str]
    run_meeting_export: Callable[[str, str, str, str, str], object | None]
    show_info: Callable[[str, str], None]
    show_warning: Callable[[str, str], None]


class MeetingActionFlowController:
    @staticmethod
    def delete_meeting(base_name: str, *, callbacks: MeetingDeleteFlowCallbacks) -> bool:
        base = str(base_name or "").strip()
        if not base:
            return False
        meeting_id = ""
        try:
            meeting_manifest = callbacks.load_meeting(base)
            meeting_id = str(getattr(meeting_manifest, "meeting_id", "") or "").strip()
        except _MEETING_STORAGE_ERRORS as exc:
            callbacks.log_delete_preview_error(base, exc)
            meeting_id = ""
        if callbacks.is_active_base(base):
            try:
                callbacks.clear_audio_path()
            except RuntimeError as exc:
                callbacks.log_clear_audio_error(base, exc)
        if not callbacks.confirm_delete():
            return False
        if meeting_id and not callbacks.cleanup_meeting_for_delete(meeting_id):
            return False
        callbacks.delete_meeting_files(base)
        callbacks.clear_meeting_states(base)
        callbacks.invalidate_payload_cache(base)
        if callbacks.is_active_base(base):
            callbacks.clear_active_meeting()
        callbacks.refresh_history()
        callbacks.refresh_pipeline_ui()
        return True

    @staticmethod
    def rename_meeting(base_name: str, *, callbacks: MeetingRenameFlowCallbacks) -> bool:
        base = str(base_name or "").strip()
        if not base:
            return False
        try:
            meeting = callbacks.load_meeting(base)
        except _MEETING_STORAGE_ERRORS as exc:
            callbacks.warn_load_failed(exc)
            return False

        current_title = callbacks.meeting_display_title(meeting)
        suggestions = callbacks.meeting_topic_suggestions(base, meeting)
        new_title = str(callbacks.prompt_new_title(current_title, suggestions) or "").strip()
        if not new_title:
            return False

        rename_mode, allow_source = callbacks.rename_policy()
        rename_source = False
        if rename_mode == "full_with_source" and allow_source:
            rename_source = callbacks.confirm_source_rename()

        try:
            if callbacks.is_active_base(base):
                callbacks.clear_audio_path()
            new_base = callbacks.rename_meeting(base, new_title, rename_mode, rename_source)
        except FileExistsError as exc:
            callbacks.warn_target_exists(exc)
            return False
        except PermissionError as exc:
            callbacks.warn_source_not_allowed(exc)
            return False
        except _MEETING_STORAGE_ERRORS as exc:
            callbacks.warn_generic(exc)
            return False

        if callbacks.is_active_base(base):
            callbacks.set_active_meeting_base(new_base)
        if callbacks.is_last_stage_base(base):
            callbacks.set_last_stage_base(new_base)
        callbacks.invalidate_payload_cache(base)
        callbacks.invalidate_payload_cache(new_base)
        callbacks.refresh_history(new_base)
        callbacks.refresh_pipeline_ui()
        return True

    @staticmethod
    def rerun_meeting(base_name: str, *, callbacks: MeetingRerunFlowCallbacks) -> bool:
        base = str(base_name or "").strip()
        if not base:
            return False
        selection = callbacks.prompt_stage()
        if isinstance(selection, MeetingRerunSelection):
            stage_id = str(selection.stage_id or "").strip()
            force_replace = bool(selection.force_replace_downstream)
        else:
            stage_id = str(selection or "").strip()
            force_replace = False
        if not stage_id:
            return False
        callbacks.start_pipeline(
            callbacks.runtime_stage_id_for_ui(stage_id),
            base,
            force_replace,
        )
        return True

    @staticmethod
    def export_meeting(
        base_name: str,
        meeting_key: str,
        *,
        targets: list[dict[str, object]] | None,
        callbacks: MeetingExportFlowCallbacks,
    ) -> bool:
        base = str(base_name or "").strip()
        if not base:
            return False
        available_targets = [dict(item) for item in list(targets or []) if isinstance(item, dict)]
        if not available_targets:
            callbacks.warn_no_targets()
            return False
        selected_target = available_targets[0]
        if len(available_targets) > 1:
            picked = callbacks.choose_target(available_targets)
            if not isinstance(picked, dict):
                return False
            selected_target = dict(picked)
        mode = str(callbacks.choose_mode() or "").strip()
        if not mode:
            return False
        plugin_id = str(selected_target.get("plugin_id", "") or "").strip()
        action_id = str(selected_target.get("action_id", "") or "").strip()
        outcome = callbacks.run_meeting_export(
            plugin_id,
            action_id,
            base,
            str(meeting_key or "").strip(),
            mode,
        )
        if outcome is None:
            return False
        level = str(getattr(outcome, "level", "") or "").strip().lower()
        title = str(getattr(outcome, "title", "") or "").strip()
        message = str(getattr(outcome, "message", "") or "").strip()
        if level == "info":
            callbacks.show_info(title, message)
            return True
        callbacks.show_warning(title, message)
        return False
