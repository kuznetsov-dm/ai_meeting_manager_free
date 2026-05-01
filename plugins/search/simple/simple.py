from __future__ import annotations

from aimn.plugins.interfaces import ActionDescriptor, ActionResult

from ..search_index import SqliteFtsSearchIndex, resolve_app_root

_PLUGIN_ID = "search.simple"
_INDEX_RELPATH = "search/simple_index.sqlite"
_EMPTY_RESULT_REBUILD_ONCE_KEYS: set[str] = set()


def _open_index() -> SqliteFtsSearchIndex:
    return SqliteFtsSearchIndex(app_root=resolve_app_root(), index_relpath=_INDEX_RELPATH)


class Plugin:
    def register(self, ctx) -> None:
        ctx.subscribe("artifact_written", _on_artifact_written)
        ctx.register_actions(_actions)


def _on_artifact_written(payload: dict) -> None:
    try:
        meeting_id = str(payload.get("meeting_id", "") or "").strip()
        stage_id = str(payload.get("stage_id", "") or "").strip()
        alias = str(payload.get("alias", "") or "")
        kind = str(payload.get("kind", "") or "").strip()
        relpath = str(payload.get("relpath", "") or payload.get("event_message", "") or "").strip()
        if not meeting_id or not kind or not relpath:
            return
        index = _open_index()
        index.on_artifact_written(meeting_id, stage_id, alias, kind, relpath)
    except Exception:
        return


def _actions() -> list[ActionDescriptor]:
    return [
        ActionDescriptor(
            action_id="search",
            label="Search (FTS)",
            description="Global keyword search across meeting artifacts (sqlite FTS5).",
            params_schema={
                "fields": [
                    {"key": "query", "label": "Query", "type": "string", "required": True},
                    {"key": "meeting_id", "label": "Meeting ID", "type": "string"},
                    {"key": "kind", "label": "Artifact kind", "type": "string"},
                    {"key": "stage_id", "label": "Stage ID", "type": "string"},
                    {"key": "alias", "label": "Alias", "type": "string"},
                    {"key": "limit", "label": "Limit", "type": "number"},
                ]
            },
            handler=_action_search,
        ),
        ActionDescriptor(
            action_id="rebuild",
            label="Rebuild search index",
            description="Rebuild the global keyword index from all meetings in output/.",
            params_schema={"fields": [{"key": "meeting_id", "label": "Meeting ID", "type": "string"}]},
            handler=_action_rebuild,
        ),
    ]


def _action_search(_settings: dict, params: dict) -> ActionResult:
    query = str(params.get("query", "") or "").strip()
    meeting_id = str(params.get("meeting_id", "") or "").strip()
    kind = str(params.get("kind", "") or "").strip()
    stage_id = str(params.get("stage_id", "") or "").strip()
    alias = str(params.get("alias", "") or "").strip()
    limit = params.get("limit", 50)
    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 50
    limit_int = max(1, min(limit_int, 200))

    if not query:
        return ActionResult(status="ok", message="empty_query", data={"query": "", "hits": [], "total": 0})

    index = _open_index()
    try:
        hits = index.search(query, meeting_id=meeting_id, kind=kind, stage_id=stage_id, alias=alias, limit=limit_int)
        if not hits and index.document_count() == 0:
            index.rebuild(meeting_id=meeting_id)
            hits = index.search(
                query, meeting_id=meeting_id, kind=kind, stage_id=stage_id, alias=alias, limit=limit_int
            )
        # If the index exists but misses a freshly added meeting, do one lazy rebuild once per scope.
        if not hits:
            rebuild_key = str(meeting_id or "*")
            if rebuild_key not in _EMPTY_RESULT_REBUILD_ONCE_KEYS:
                _EMPTY_RESULT_REBUILD_ONCE_KEYS.add(rebuild_key)
                try:
                    index.rebuild(meeting_id=meeting_id)
                except Exception:
                    # Keep degraded behavior: do not fail the search on opportunistic rebuild.
                    pass
                hits = index.search(
                    query, meeting_id=meeting_id, kind=kind, stage_id=stage_id, alias=alias, limit=limit_int
                )
    except Exception:
        # Index might be missing/corrupt on first run; rebuild once and retry.
        try:
            index.rebuild(meeting_id=meeting_id)
            hits = index.search(
                query, meeting_id=meeting_id, kind=kind, stage_id=stage_id, alias=alias, limit=limit_int
            )
        except Exception as exc:
            return ActionResult(status="error", message=str(exc))

    payload = {
        "query": query,
        "total": len(hits),
        "hits": [
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
            for hit in hits
        ],
    }
    return ActionResult(status="ok", message="ok", data=payload)


def _action_rebuild(_settings: dict, params: dict) -> ActionResult:
    meeting_id = str(params.get("meeting_id", "") or "").strip()
    index = _open_index()
    try:
        index.rebuild(meeting_id=meeting_id)
    except Exception as exc:
        return ActionResult(status="error", message=str(exc))
    return ActionResult(status="ok", message="ok", data={"meeting_id": meeting_id or None})
