from __future__ import annotations

from collections.abc import Sequence


class ArtifactTabNavigationController:
    @staticmethod
    def tab_to_version_index(tab_index: int, *, global_results_visible: bool, versions_count: int) -> int | None:
        base = 1 if bool(global_results_visible) else 0
        idx = int(tab_index) - base
        if idx < 0 or idx >= int(versions_count):
            return None
        return idx

    @staticmethod
    def select_version_tab_index(
        versions: Sequence[object],
        *,
        global_results_visible: bool,
        stage_id: str = "",
        alias: str = "",
        kind: str = "",
    ) -> int | None:
        want_stage = str(stage_id or "").strip()
        want_alias = str(alias or "").strip()
        want_kind = str(kind or "").strip()
        base = 1 if bool(global_results_visible) else 0
        fallback_kind_idx = -1
        fallback_alias_idx = -1
        for i, art in enumerate(versions):
            current_stage = str(getattr(art, "stage_id", "") or "").strip()
            current_alias = str(getattr(art, "alias", "") or "").strip()
            current_kind = str(getattr(art, "kind", "") or "").strip()
            if fallback_kind_idx < 0 and (not want_kind or current_kind == want_kind):
                fallback_kind_idx = i
            if (
                fallback_alias_idx < 0
                and (not want_kind or current_kind == want_kind)
                and want_alias
                and current_alias == want_alias
            ):
                fallback_alias_idx = i
            if want_kind and current_kind != want_kind:
                continue
            if want_stage and current_stage != want_stage:
                continue
            if want_alias and current_alias != want_alias:
                continue
            return base + i
        if fallback_alias_idx >= 0:
            return base + fallback_alias_idx
        if fallback_kind_idx >= 0:
            return base + fallback_kind_idx
        return None

    @staticmethod
    def select_alias_tab_index(
        versions: Sequence[object],
        *,
        global_results_visible: bool,
        alias: str,
    ) -> int | None:
        want = str(alias or "").strip()
        if not want:
            return None
        base = 1 if bool(global_results_visible) else 0
        for i, art in enumerate(versions):
            if str(getattr(art, "alias", "") or "").strip() == want:
                return base + i
        return None
