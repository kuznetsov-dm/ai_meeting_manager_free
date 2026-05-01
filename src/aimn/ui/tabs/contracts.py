from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Protocol


class StageInspectorTab(Protocol):
    def set_stage(self, stage: "StageViewModel") -> None:
        ...

    def on_activated(self) -> None:
        ...

    def on_deactivated(self) -> None:
        ...

    def on_pipeline_event(self, event: "PipelineEvent") -> None:
        ...


@dataclass(frozen=True)
class SettingOption:
    label: str
    value: str


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    value: object
    options: List[SettingOption] = field(default_factory=list)
    editable: bool = False
    multi_select: bool = False


@dataclass(frozen=True)
class StageViewModel:
    stage_id: str
    display_name: str
    short_name: str
    status: str
    progress: Optional[int]
    is_enabled: bool
    is_dirty: bool
    is_blocked: bool
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    plugin_id: str = ""
    plugin_options: List[SettingOption] = field(default_factory=list)
    inline_settings_keys: List[str] = field(default_factory=list)
    settings_schema: List[SettingField] = field(default_factory=list)
    current_settings: dict = field(default_factory=dict)
    effective_settings: dict = field(default_factory=dict)
    ui_metadata: dict = field(default_factory=dict)
    artifacts: List[dict] = field(default_factory=list)
    can_run: bool = True
    can_rerun: bool = True
    last_run_at: Optional[str] = None


@dataclass(frozen=True)
class PipelineViewModel:
    stages: List[StageViewModel]
    active_stage_id: str
    status: str
    current_stage_id: Optional[str] = None
    progress: Optional[int] = None
    last_error: Optional[str] = None


@dataclass(frozen=True)
class PipelineEvent:
    event_type: str
    stage_id: Optional[str] = None
    message: Optional[str] = None
    progress: Optional[int] = None
    timestamp: Optional[str] = None
    base_name: Optional[str] = None
    meeting_id: Optional[str] = None


def inline_fields_from_schema(
    schema: Iterable[SettingField],
    inline_keys: Iterable[str],
) -> List[SettingField]:
    inline_set = {key for key in inline_keys}
    if not inline_set:
        return []
    return [field for field in schema if field.key in inline_set]
