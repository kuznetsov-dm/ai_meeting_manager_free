from __future__ import annotations

from collections.abc import Sequence


class SearchModeController:
    @staticmethod
    def normalized_mode(value: object) -> str:
        mode = str(value or "local").strip().lower() or "local"
        if mode in {"simple", "smart"}:
            return "global"
        return mode

    @staticmethod
    def normalize_modes(modes: Sequence[object]) -> list[str]:
        desired: list[str] = []
        for raw in modes or []:
            mode = SearchModeController.normalized_mode(raw)
            if not mode:
                continue
            if mode not in desired:
                desired.append(mode)
        if "local" not in desired:
            desired.insert(0, "local")
        return desired

    @staticmethod
    def ui_state(*, mode: str, has_matches: bool, global_results_visible: bool) -> dict[str, object]:
        normalized = SearchModeController.normalized_mode(mode)
        is_local = normalized == "local"
        return {
            "mode": normalized,
            "is_local": is_local,
            "show_match_nav": is_local,
            "match_nav_enabled": bool(is_local and has_matches),
            "placeholder_key": (
                "search.placeholder.local" if is_local else "search.placeholder.global"
            ),
            "placeholder_default": (
                "Search in text..." if is_local else "Search across meetings..."
            ),
            "reset_local_search": not is_local,
            "clear_global_results": bool(is_local and global_results_visible),
        }
