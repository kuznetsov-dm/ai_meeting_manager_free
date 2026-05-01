from __future__ import annotations


class SearchActionController:
    @staticmethod
    def submit_decision(*, mode: str, query: str) -> tuple[str, str]:
        normalized_mode = str(mode or "").strip().lower() or "local"
        text = str(query or "").strip()
        if normalized_mode == "local":
            return "run_local", text
        if not text:
            return "clear_global", ""
        return "emit_global", text

    @staticmethod
    def clear_decision(*, mode: str, query: str) -> tuple[str, bool]:
        normalized_mode = str(mode or "").strip().lower() or "local"
        has_query = bool(str(query or "").strip())
        if normalized_mode == "local":
            return "reset_local", has_query
        return "clear_global", has_query

    @staticmethod
    def highlight_decision(query: str) -> tuple[bool, str]:
        text = str(query or "").strip()
        return bool(text), text
