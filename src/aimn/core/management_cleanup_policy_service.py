from __future__ import annotations


class ManagementCleanupPolicyService:
    @staticmethod
    def empty_meeting_preview() -> dict[str, int]:
        return {
            "suggestions": 0,
            "task_mentions": 0,
            "project_mentions": 0,
            "agenda_mentions": 0,
            "meeting_links": 0,
            "orphan_tasks": 0,
            "orphan_projects": 0,
            "orphan_agendas": 0,
        }

    @staticmethod
    def empty_artifact_preview() -> dict[str, int]:
        return {
            "suggestions": 0,
            "task_mentions": 0,
            "project_mentions": 0,
            "agenda_mentions": 0,
            "orphan_tasks": 0,
            "orphan_projects": 0,
            "orphan_agendas": 0,
        }

    @staticmethod
    def artifact_alias_source_kinds(artifact_kind: str) -> list[str]:
        kind = str(artifact_kind or "").strip().lower()
        if not kind:
            return []
        source_kinds = [kind]
        if kind == "transcript":
            source_kinds.append("transcript_selection")
        return source_kinds

    @staticmethod
    def build_cleanup_policy(
        preview: dict[str, int] | None,
        *,
        touched_keys: tuple[str, ...],
    ) -> dict[str, object]:
        counts = {str(key): int((preview or {}).get(key, 0) or 0) for key in (
            "suggestions",
            "task_mentions",
            "project_mentions",
            "agenda_mentions",
            "meeting_links",
            "orphan_tasks",
            "orphan_projects",
            "orphan_agendas",
        )}
        touched_total = sum(int(counts.get(key, 0) or 0) for key in touched_keys)
        orphan_total = sum(
            int(counts.get(key, 0) or 0)
            for key in ("orphan_tasks", "orphan_projects", "orphan_agendas")
        )
        policy: dict[str, object] = dict(counts)
        policy["touched_total"] = touched_total
        policy["orphan_total"] = orphan_total
        policy["has_changes"] = bool(touched_total > 0)
        policy["has_orphans"] = bool(orphan_total > 0)
        return policy
