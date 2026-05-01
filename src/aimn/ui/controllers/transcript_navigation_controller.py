from __future__ import annotations

from collections.abc import Sequence

from aimn.ui.controllers.transcript_evidence_controller import safe_int


class TranscriptNavigationController:
    @staticmethod
    def payload_range(payload: dict) -> tuple[int, int] | None:
        if not isinstance(payload, dict):
            return None
        left = safe_int(payload.get("left"), -1)
        right = safe_int(payload.get("right"), -1)
        if left < 0 or right < left:
            return None
        return left, right

    @staticmethod
    def row_for_position(blocks: Sequence[tuple[int, int, dict, int]], position: int) -> int:
        pos = int(position)
        for left, right, _payload, row in blocks:
            if int(left) <= pos <= int(right):
                return int(row)
        return -1

    @staticmethod
    def row_for_transcript_target(
        payloads: Sequence[dict],
        *,
        segment_index: int = -1,
        start_ms: int = -1,
    ) -> int:
        want_index = int(segment_index)
        want_start = int(start_ms)
        if want_index < 0 and want_start < 0:
            return -1

        if want_index >= 0:
            for row, payload in enumerate(payloads):
                if not isinstance(payload, dict):
                    continue
                idx = payload.get("segment_index")
                if idx is None:
                    continue
                if safe_int(idx, -1) == want_index:
                    return row

        if want_start >= 0:
            for row, payload in enumerate(payloads):
                if not isinstance(payload, dict):
                    continue
                st = payload.get("start_ms")
                if st is None:
                    continue
                if safe_int(st, -1) == want_start:
                    return row

        if want_start >= 0:
            for row, payload in enumerate(payloads):
                if not isinstance(payload, dict):
                    continue
                st = payload.get("start_ms")
                if st is None:
                    continue
                left = safe_int(st, -1)
                right = safe_int(payload.get("end_ms"), left)
                if left <= want_start <= max(left, right):
                    return row

        return -1
