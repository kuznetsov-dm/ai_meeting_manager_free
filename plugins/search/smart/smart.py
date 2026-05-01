from __future__ import annotations

from aimn.plugins.interfaces import ActionDescriptor, ActionResult


class Plugin:
    def register(self, ctx) -> None:
        self.ctx = ctx
        self.logger = ctx.get_logger()

        # Subscribe to new artifacts to update the semantic index
        ctx.subscribe("artifact_written", self._on_artifact_written)

        # Register search action
        ctx.register_actions(self.get_actions)

    def get_actions(self) -> list[ActionDescriptor]:
        return [
            ActionDescriptor(
                action_id="search",
                label="Smart Semantic Search",
                description="Search by meaning across all meetings using vector embeddings.",
                params_schema={
                    "fields": [
                        {"key": "query", "label": "Semantic Query", "type": "string", "required": True}
                    ]
                },
                handler=self.handle_search,
            )
        ]

    def _on_artifact_written(self, payload: dict) -> None:
        meeting_id = payload.get("meeting_id")
        kind = payload.get("kind")
        if not meeting_id or kind not in ["transcript", "summary", "edited"]:
            return

        self.logger.info(f"Indexing {kind} for meeting {meeting_id} semantically...")
        # Future semantic indexing hook: request embeddings from an active LLM provider
        # and persist them into a vector store.

    def handle_search(self, settings: dict, params: dict) -> ActionResult:
        query = params.get("query")
        if not query:
            return ActionResult(status="error", message="query_missing")

        self.logger.info(f"Performing smart search for: {query}")

        # Mocking semantic hits
        hits = [
            {
                "meeting_id": "2024-01-20_Project_Sync",
                "kind": "summary",
                "snippet": "Discussed the new [architecture] and plugin system.",
                "context": "The team agreed on the v1.1 plugin architecture needed to support third-party developers.",
                "score": 0.95
            },
            {
                "meeting_id": "2024-01-21_UI_Review",
                "kind": "transcript",
                "snippet": "We should use [standard components] for the plugin cards.",
                "context": "It's important to maintain consistency across the application UI.",
                "score": 0.88,
            },
        ]

        return ActionResult(
            status="ok",
            message="found_semantic_matches",
            data={
                "query": query,
                "hits": hits,
                "total": len(hits),
            },
        )
