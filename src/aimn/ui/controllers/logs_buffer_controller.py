from __future__ import annotations

from collections.abc import Sequence


class LogsBufferController:
    @staticmethod
    def update_buffer(
        entries: Sequence[object],
        *,
        current_text: str,
        current_count: int,
    ) -> tuple[str, int]:
        items = list(entries or [])
        count = len(items)
        if count == int(current_count):
            return str(current_text or ""), int(current_count)
        if count > int(current_count) and str(current_text or "").strip():
            appended = "\n".join(str(getattr(entry, "message", "") or "") for entry in items[int(current_count) :])
            if appended:
                return f"{current_text}\n{appended}", count
            return str(current_text or ""), count
        text = "\n".join(str(getattr(entry, "message", "") or "") for entry in items)
        return text, count
