from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactExportButtonSpec:
    plugin_id: str
    action_id: str
    label: str
    icon_hint: str
    tooltip: str


class ArtifactExportButtonsController:
    @staticmethod
    def normalize_targets(
        targets: Sequence[dict] | Sequence[tuple[str, str, str]] | None,
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for entry in targets or []:
            if isinstance(entry, dict):
                plugin_id = str(entry.get("plugin_id", "") or "").strip()
                action_id = str(entry.get("action_id", "") or "").strip()
                label = str(entry.get("label", "") or "").strip() or plugin_id
                icon_hint = str(entry.get("icon", "") or "").strip()
            elif isinstance(entry, tuple) and len(entry) >= 3:
                plugin_id = str(entry[0] or "").strip()
                action_id = str(entry[1] or "").strip()
                label = str(entry[2] or "").strip() or plugin_id
                icon_hint = ""
            else:
                continue
            if not plugin_id or not action_id:
                continue
            normalized.append(
                {
                    "plugin_id": plugin_id,
                    "action_id": action_id,
                    "label": label,
                    "icon": icon_hint,
                }
            )
        return normalized

    @staticmethod
    def build_specs(
        targets: Sequence[dict[str, str]] | None,
        *,
        export_label: str,
    ) -> list[ArtifactExportButtonSpec]:
        specs: list[ArtifactExportButtonSpec] = []
        for target in list(targets or []):
            if not isinstance(target, dict):
                continue
            plugin_id = str(target.get("plugin_id", "") or "").strip()
            action_id = str(target.get("action_id", "") or "").strip()
            label = str(target.get("label", "") or "").strip() or plugin_id
            icon_hint = str(target.get("icon", "") or "").strip()
            if not plugin_id or not action_id:
                continue
            specs.append(
                ArtifactExportButtonSpec(
                    plugin_id=plugin_id,
                    action_id=action_id,
                    label=label,
                    icon_hint=icon_hint,
                    tooltip=f"{str(export_label or '').strip()}: {label}",
                )
            )
        return specs
