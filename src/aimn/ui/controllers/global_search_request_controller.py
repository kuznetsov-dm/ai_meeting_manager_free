from __future__ import annotations


class GlobalSearchRequestController:
    @staticmethod
    def normalize_request(*, query: str, mode: str, normalized_mode: str) -> dict[str, object]:
        q = str(query or "").strip()
        mode_value = str(mode or "").strip()
        mode_normalized = str(normalized_mode or "").strip()
        should_clear = not q or mode_normalized not in {"global"}
        return {
            "query": q,
            "mode": mode_value,
            "normalized_mode": mode_normalized,
            "should_clear": should_clear,
        }

    @staticmethod
    def next_request_id(current_request_id: int) -> int:
        return int(current_request_id) + 1

    @staticmethod
    def is_stale(*, done_request_id: int, current_request_id: int) -> bool:
        return int(done_request_id) != int(current_request_id)
