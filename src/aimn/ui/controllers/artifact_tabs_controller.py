from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactTabSpec:
    kind: str
    title: str
    tooltip: str = ""
    version_index: int | None = None


class ArtifactTabsController:
    @staticmethod
    def build_specs(
        versions: Sequence[object],
        *,
        global_results_visible: bool,
        results_title: str,
        text_title: str,
        pinned_aliases: Mapping[str, str] | None = None,
    ) -> list[ArtifactTabSpec]:
        specs: list[ArtifactTabSpec] = []
        pinned = {str(k): str(v) for k, v in dict(pinned_aliases or {}).items()}
        if bool(global_results_visible):
            specs.append(ArtifactTabSpec(kind="results", title=str(results_title or "")))
        if not list(versions or []):
            specs.append(ArtifactTabSpec(kind="text", title=str(text_title or "")))
            return specs
        for idx, art in enumerate(versions):
            stage_id = str(getattr(art, "stage_id", "") or "").strip()
            alias = str(getattr(art, "alias", "") or "").strip()
            relpath = str(getattr(art, "relpath", "") or "").strip()
            title = alias or stage_id or f"v{idx + 1}"
            if alias and stage_id and pinned.get(stage_id) == alias:
                title = f"📌 {title}"
            tooltip = f"{stage_id}:{alias}\n{relpath}"
            specs.append(
                ArtifactTabSpec(
                    kind="artifact",
                    title=title,
                    tooltip=tooltip,
                    version_index=int(idx),
                )
            )
        return specs

    @staticmethod
    def previous_title(tab_titles: Sequence[str], current_index: int) -> str:
        idx = int(current_index)
        if idx < 0 or idx >= len(list(tab_titles or [])):
            return ""
        return str(tab_titles[idx] or "")

    @staticmethod
    def selected_index(
        specs: Sequence[ArtifactTabSpec],
        versions: Sequence[object],
        *,
        global_results_visible: bool,
        results_title: str,
        prev_title: str = "",
        prefer_results: bool = False,
        active_aliases: Mapping[str, str] | None = None,
    ) -> int:
        if not list(specs or []):
            return 0
        if bool(prefer_results) and bool(global_results_visible):
            return 0

        previous = str(prev_title or "")
        if bool(global_results_visible) and previous == str(results_title or ""):
            return 0

        if previous:
            for idx, spec in enumerate(specs):
                if spec.title == previous:
                    return int(idx)

        selected = 0
        versions_list = list(versions or [])
        if not versions_list:
            return selected

        stage_id = str(getattr(versions_list[0], "stage_id", "") or "").strip()
        want = str(dict(active_aliases or {}).get(stage_id, "") or "").strip()
        if not stage_id or not want:
            return selected

        base = 1 if bool(global_results_visible) else 0
        for idx, art in enumerate(versions_list):
            if (
                str(getattr(art, "stage_id", "") or "").strip() == stage_id
                and str(getattr(art, "alias", "") or "").strip() == want
            ):
                return base + idx
        return selected
