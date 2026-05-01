from __future__ import annotations

from collections.abc import Callable

from aimn.core.api import BuiltinSearchService
from aimn.core.search_query import normalize_search_query


class GlobalSearchController:
    def __init__(
        self,
        *,
        catalog_service,
        action_service,
        text_panel,
        history_panel,
        all_meetings_provider: Callable[[], list[object]],
        refresh_history: Callable[[str], None],
        active_meeting_base_name_provider: Callable[[], str],
    ) -> None:
        self._catalog_service = catalog_service
        self._action_service = action_service
        self._text_panel = text_panel
        self._history_panel = history_panel
        self._all_meetings_provider = all_meetings_provider
        self._refresh_history = refresh_history
        self._active_meeting_base_name_provider = active_meeting_base_name_provider
        self._builtin_search = BuiltinSearchService()
        self._query: str = ""
        self._meeting_ids: set[str] = set()
        self._registry_stamp: str = ""

    @property
    def query(self) -> str:
        return self._query

    @property
    def meeting_ids(self) -> set[str]:
        return set(self._meeting_ids)

    def refresh_global_search_ui(self) -> None:
        self._text_panel.set_search_modes(["local", "global"])

    def poll_registry(self) -> None:
        snapshot = self._catalog_service.load()
        stamp = snapshot.stamp
        if stamp == self._registry_stamp:
            return
        self._registry_stamp = stamp
        self.refresh_global_search_ui()

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        return self._catalog_service.is_plugin_enabled(plugin_id)

    def semantic_search_provider(self) -> str:
        catalog = self._catalog_service.load().catalog
        for plugin in catalog.enabled_plugins():
            caps = plugin.capabilities if isinstance(getattr(plugin, "capabilities", None), dict) else {}
            gs = caps.get("global_search") if isinstance(caps, dict) else None
            if not isinstance(gs, dict):
                continue
            mode = str(gs.get("mode", "") or "").strip().lower()
            if mode in {"semantic", "global_semantic"} and plugin.plugin_id:
                return str(plugin.plugin_id)
        return ""

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        wanted_mode = str(mode or "global").strip().lower()
        if wanted_mode in {"simple", "smart"}:
            wanted_mode = "global"
        return wanted_mode

    def normalize_mode(self, mode: str) -> str:
        return self._normalize_mode(mode)

    def build_global_search_payload(
        self,
        query: str,
        mode: str,
        *,
        all_meetings: list[object] | None = None,
    ) -> dict[str, object]:
        q = normalize_search_query(query)
        wanted_mode = self._normalize_mode(mode)
        if not q:
            return {"clear": True}
        if wanted_mode not in {"global"}:
            return {"clear": True}

        payload: dict = {"query": q, "kind": "transcript"}
        plugin_id = self.semantic_search_provider()
        hits: list[dict] = []
        answer = ""
        meetings = list(all_meetings) if isinstance(all_meetings, list) else self._all_meetings_provider()
        mid_to_label = {
            str(getattr(meeting, "meeting_id", "") or ""): str(getattr(meeting, "base_name", "") or "")
            for meeting in meetings
        }
        if plugin_id and self.is_plugin_enabled(plugin_id):
            result = self._action_service.invoke_action(plugin_id, "search", payload)
            if result.status != "ok" or not isinstance(result.data, dict):
                raise RuntimeError(str(result.message or "search_failed"))
            raw_hits = result.data.get("hits", [])
            if isinstance(raw_hits, list):
                hits = [item for item in raw_hits if isinstance(item, dict)]
            try:
                answer = str(result.data.get("answer", "") or "")
            except Exception:
                answer = ""
            hits = self._enrich_transcript_hits(hits=hits, mid_to_label=mid_to_label)
            if not hits:
                answer = ""
        if not hits:
            raw_hits = self._builtin_search.search_transcripts(q, limit=80)
            hits = [
                {
                    "meeting_id": hit.meeting_id,
                    "alias": hit.alias,
                    "stage_id": hit.stage_id,
                    "kind": hit.kind,
                    "relpath": hit.relpath,
                    "snippet": hit.snippet,
                    "score": hit.score,
                    "segment_index": hit.segment_index if hit.segment_index is not None else -1,
                    "start_ms": hit.start_ms if hit.start_ms is not None else -1,
                    "end_ms": hit.end_ms if hit.end_ms is not None else -1,
                    "content": hit.content,
                    "context": str(getattr(hit, "context", "") or ""),
                }
                for hit in raw_hits
            ]
        enriched_hits = self._enrich_transcript_hits(hits=hits, mid_to_label=mid_to_label)

        meeting_ids = {
            str(hit.get("meeting_id", "") or "")
            for hit in enriched_hits
            if isinstance(hit, dict) and str(hit.get("meeting_id", "") or "")
        }
        filtered = [
            meeting
            for meeting in meetings
            if str(getattr(meeting, "meeting_id", "") or "") in set(meeting_ids)
        ]
        selected_base = ""
        if filtered:
            selected_base = str(getattr(filtered[0], "base_name", "") or "")

        return {
            "clear": False,
            "query": q,
            "hits": list(enriched_hits),
            "answer": answer,
            "meeting_ids": set(meeting_ids),
            "filtered_meetings": list(filtered),
            "selected_base": selected_base,
            "status_text": f"{len(enriched_hits)} matches",
        }

    @staticmethod
    def _enrich_transcript_hits(*, mid_to_label: dict[str, str], hits: list[dict]) -> list[dict]:
        enriched_hits: list[dict] = []
        for raw in hits:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("kind", "") or "").strip().lower() != "transcript":
                continue
            mid = str(raw.get("meeting_id", "") or "")
            if not mid or mid not in mid_to_label:
                continue
            item = dict(raw)
            label = mid_to_label.get(mid, "")
            if label:
                item["meeting_label"] = label
            enriched_hits.append(item)
        return enriched_hits

    def apply_global_search_payload(self, payload: dict[str, object]) -> None:
        if bool((payload or {}).get("clear", False)):
            self.clear_global_search()
            return

        query = str((payload or {}).get("query", "") or "").strip()
        hits = [item for item in list((payload or {}).get("hits", []) or []) if isinstance(item, dict)]
        answer = str((payload or {}).get("answer", "") or "")
        meeting_ids = {
            str(mid or "")
            for mid in set((payload or {}).get("meeting_ids", set()) or set())
            if str(mid or "").strip()
        }
        filtered = list((payload or {}).get("filtered_meetings", []) or [])
        selected_base = str((payload or {}).get("selected_base", "") or "").strip()
        status_text = str((payload or {}).get("status_text", "") or "").strip()

        self._query = query
        self._meeting_ids = set(meeting_ids)
        self._text_panel.set_global_search_status(status_text)
        self._text_panel.set_global_search_results(query, hits, answer=answer)

        self._history_panel.set_meetings(filtered)
        if filtered and selected_base:
            self._history_panel.select_by_base_name(selected_base)

    def on_global_search_requested(self, query: str, mode: str) -> None:
        try:
            payload = self.build_global_search_payload(query, mode)
        except Exception as exc:
            self._text_panel.set_global_search_status(f"Search failed: {exc}")
            return
        self.apply_global_search_payload(payload)

    def clear_global_search(self) -> None:
        self._query = ""
        self._meeting_ids = set()
        self._text_panel.set_global_search_status("")
        self._text_panel.clear_global_search_results()
        self._refresh_history(str(self._active_meeting_base_name_provider() or ""))

    def on_global_search_open(
        self,
        meeting_id: str,
        stage_id: str,
        alias: str,
        kind: str,
        segment_index: int,
        start_ms: int,
    ) -> None:
        mid = str(meeting_id or "").strip()
        sid = str(stage_id or "").strip()
        k = str(kind or "").strip()
        if not mid or not k:
            return
        all_meetings = self._all_meetings_provider()
        meeting = next((m for m in all_meetings if str(getattr(m, "meeting_id", "") or "") == mid), None)
        if not meeting:
            return
        base_name = str(getattr(meeting, "base_name", "") or "").strip()
        if not base_name:
            return
        self._history_panel.select_by_base_name(base_name)
        self._text_panel.select_artifact_kind(k)
        if hasattr(self._text_panel, "select_version"):
            self._text_panel.select_version(stage_id=sid, alias=str(alias or ""), kind=k)
        else:
            self._text_panel.select_version_alias(str(alias or ""))
        if self._query:
            self._text_panel.highlight_query(self._query)
        if int(segment_index) >= 0 or int(start_ms) >= 0:
            self._text_panel.jump_to_transcript_segment(
                segment_index=int(segment_index),
                start_ms=int(start_ms),
                stage_id=sid,
                alias=str(alias or ""),
                kind=k,
            )
