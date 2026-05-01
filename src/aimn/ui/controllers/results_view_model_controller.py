from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aimn.ui.controllers.global_search_results_controller import (
    GlobalSearchResultsController,
    truncate_result_text,
)


@dataclass(frozen=True)
class ResultsViewItem:
    title: str
    item_text: str
    tooltip: str
    payload: dict
    left: int
    right: int


class ResultsViewModelController:
    @staticmethod
    def build(
        *,
        query: str,
        rows: Sequence[dict],
    ) -> dict[str, object]:
        query_terms = GlobalSearchResultsController.search_terms_from_query(query)
        global_terms = GlobalSearchResultsController.dedupe_terms(list(query_terms), min_len=1, max_terms=96)
        active_blocks: list[tuple[int, int, dict, int]] = []
        items: list[ResultsViewItem] = []
        all_terms: list[str] = []
        offset = 0
        text_parts: list[str] = []

        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            payload = dict(row.get("payload", {}) or {})
            excerpt = str(row.get("text", "") or "").strip()
            if not excerpt:
                continue
            title = str(row.get("title", "") or "").strip() or f"Result {idx}"
            preview = str(row.get("preview", "") or "").strip() or truncate_result_text(
                excerpt.replace("\n", " "),
                limit=96,
            )
            item_text = f"{title}\n{preview}".strip()
            block = f"{excerpt}\n\n"
            left = int(offset)
            right = int(offset + len(block))
            offset = right
            terms = list(row.get("terms", []) or [])
            all_terms.extend(terms)
            active_blocks.append((left, right, payload, len(items)))
            text_parts.append(block)
            items.append(
                ResultsViewItem(
                    title=title,
                    item_text=item_text,
                    tooltip=title,
                    payload=payload,
                    left=left,
                    right=right,
                )
            )

        highlight_terms = GlobalSearchResultsController.dedupe_terms(
            list(global_terms) + list(all_terms),
            min_len=1,
            max_terms=128,
        )
        return {
            "items": items,
            "active_blocks": active_blocks,
            "text": "".join(text_parts),
            "highlight_terms": highlight_terms,
        }
