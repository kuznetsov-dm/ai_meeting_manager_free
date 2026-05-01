import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.management_store import ManagementStore  # noqa: E402


class TestManagementStore(unittest.TestCase):
    def test_task_dedupe_and_mentions_across_meetings(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                task_id_1 = store.upsert_task_with_mention(
                    title="Prepare budget proposal",
                    normalized="prepare budget proposal",
                    meeting_id="m1",
                    source_kind="summary",
                    source_alias="A01",
                    dedupe_similarity=0.9,
                )
                task_id_2 = store.upsert_task_with_mention(
                    title="prepare budget proposal",
                    normalized="prepare budget proposal",
                    meeting_id="m2",
                    source_kind="summary",
                    source_alias="A02",
                    dedupe_similarity=0.9,
                )
                self.assertEqual(task_id_1, task_id_2)
                tasks = store.list_tasks()
                row = next(t for t in tasks if t["id"] == task_id_1)
                self.assertIn("m1", row["meetings"])
                self.assertIn("m2", row["meetings"])
            finally:
                store.close()

    def test_project_dedupe_and_mentions(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                project_id_1 = store.upsert_project_with_mention(
                    name="Mobile App Redesign",
                    normalized="mobile app redesign",
                    meeting_id="m1",
                    source_kind="edited",
                    source_alias="A10",
                    dedupe_similarity=0.88,
                )
                project_id_2 = store.upsert_project_with_mention(
                    name="mobile app redesign",
                    normalized="mobile app redesign",
                    meeting_id="m1",
                    source_kind="edited",
                    source_alias="A10",
                    dedupe_similarity=0.88,
                )
                self.assertEqual(project_id_1, project_id_2)
                projects = store.list_projects_for_meeting("m1")
                self.assertTrue(any(p["id"] == project_id_1 for p in projects))
            finally:
                store.close()

    def test_agenda_meeting_and_project_task_links(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                project_id = store.create_project(name="Website Revamp", description="")
                second_project_id = store.create_project(name="Marketing Site", description="")
                task_id = store.create_task(title="Prepare rollout plan")
                meeting_id = "m42"
                agenda_id = store.create_agenda(title="Sprint Planning", text="1. Scope\n2. Owners")

                store.link_entities(
                    left_type="meeting",
                    left_id=meeting_id,
                    right_type="agenda",
                    right_id=agenda_id,
                )
                store.link_entities(
                    left_type="meeting",
                    left_id=meeting_id,
                    right_type="project",
                    right_id=project_id,
                )
                store.link_entities(
                    left_type="meeting",
                    left_id=meeting_id,
                    right_type="task",
                    right_id=task_id,
                )
                store.link_entities(
                    left_type="agenda",
                    left_id=agenda_id,
                    right_type="task",
                    right_id=task_id,
                )

                self.assertTrue(
                    store.link_entities(
                        left_type="project",
                        left_id=project_id,
                        right_type="task",
                        right_id=task_id,
                    )
                )
                self.assertTrue(
                    store.link_entities(
                        left_type="project",
                        left_id=second_project_id,
                        right_type="task",
                        right_id=task_id,
                    )
                )

                agendas_for_meeting = store.list_agendas_for_meeting(meeting_id)
                self.assertTrue(any(a["id"] == agenda_id for a in agendas_for_meeting))

                projects_for_meeting = store.list_projects_for_meeting(meeting_id)
                self.assertTrue(any(p["id"] == project_id for p in projects_for_meeting))

                tasks_for_meeting = store.list_tasks_for_meeting(meeting_id)
                self.assertTrue(any(t["id"] == task_id for t in tasks_for_meeting))

                tasks = store.list_tasks()
                row = next(t for t in tasks if t["id"] == task_id)
                self.assertIn(project_id, row["project_ids"])
                self.assertIn(second_project_id, row["project_ids"])

                self.assertTrue(
                    store.unlink_entities(
                        left_type="agenda",
                        left_id=agenda_id,
                        right_type="task",
                        right_id=task_id,
                    )
                )
                links = store.list_links_for(entity_type="agenda", entity_id=agenda_id)
                self.assertFalse(
                    any(link["related_type"] == "task" and link["related_id"] == task_id for link in links)
                )

                self.assertTrue(
                    store.unlink_entities(
                        left_type="project",
                        left_id=project_id,
                        right_type="task",
                        right_id=task_id,
                    )
                )
                tasks_after = store.list_tasks()
                row_after = next(t for t in tasks_after if t["id"] == task_id)
                self.assertNotIn(project_id, row_after["project_ids"])
                self.assertIn(second_project_id, row_after["project_ids"])
            finally:
                store.close()

    def test_suggestion_approval_creates_approved_entity_without_direct_auto_create(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                suggestion_id = store.upsert_suggestion(
                    kind="task",
                    title="Prepare launch memo",
                    normalized_key="prepare launch memo",
                    source_meeting_id="m100",
                    source_kind="summary",
                    source_alias="A10",
                    confidence=0.84,
                    reasoning_short="Explicit action item",
                    evidence=[{"text": "Prepare launch memo by Friday"}],
                )
                self.assertEqual(store.list_tasks(), [])
                approved = store.approve_suggestion(suggestion_id)
                self.assertIsNotNone(approved)
                tasks = store.list_tasks_for_meeting("m100")
                self.assertEqual(len(tasks), 1)
                suggestions = store.list_suggestions(state=None, meeting_id="m100")
                row = next(item for item in suggestions if item["id"] == suggestion_id)
                self.assertEqual(row["state"], "approved")
                self.assertEqual(row["approved_entity_type"], "task")
                self.assertTrue(row["approved_entity_id"])
            finally:
                store.close()

    def test_cleanup_meeting_removes_suggestions_and_keeps_orphans_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                suggestion_id = store.upsert_suggestion(
                    kind="project",
                    title="Website refresh",
                    normalized_key="website refresh",
                    source_meeting_id="m200",
                    source_kind="edited",
                    source_alias="A20",
                    confidence=0.75,
                    reasoning_short="Explicit project section",
                    evidence=[{"text": "Project: Website refresh"}],
                )
                approved = store.approve_suggestion(suggestion_id)
                self.assertIsNotNone(approved)
                preview = store.preview_meeting_cleanup("m200")
                self.assertEqual(preview["suggestions"], 1)
                self.assertEqual(preview["orphan_projects"], 1)
                result = store.cleanup_meeting("m200", delete_orphan_entities=False)
                self.assertEqual(result["suggestions"], 1)
                self.assertEqual(store.list_suggestions(meeting_id="m200"), [])
                self.assertEqual(len(store.list_projects()), 1)
            finally:
                store.close()

    def test_prepare_meeting_cleanup_adds_policy_flags_and_totals(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                suggestion_id = store.upsert_suggestion(
                    kind="project",
                    title="Website refresh",
                    normalized_key="website refresh",
                    source_meeting_id="m200b",
                    source_kind="edited",
                    source_alias="A20",
                    confidence=0.75,
                    reasoning_short="Explicit project section",
                    evidence=[{"text": "Project: Website refresh"}],
                )
                approved = store.approve_suggestion(suggestion_id)
                self.assertIsNotNone(approved)
                policy = store.prepare_meeting_cleanup("m200b")
                self.assertTrue(bool(policy["has_changes"]))
                self.assertTrue(bool(policy["has_orphans"]))
                self.assertEqual(int(policy["touched_total"]), 2)
                self.assertEqual(int(policy["orphan_total"]), 1)
            finally:
                store.close()

    def test_cleanup_meeting_can_delete_orphan_ai_entities(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                suggestion_id = store.upsert_suggestion(
                    kind="agenda",
                    title="Planned agenda",
                    description="1. Budget\n2. Risks",
                    normalized_key="planned agenda",
                    source_meeting_id="m300",
                    source_kind="summary",
                    source_alias="A30",
                    confidence=0.91,
                    reasoning_short="Explicit agenda block",
                    evidence=[{"text": "## Planned Agenda"}],
                )
                approved = store.approve_suggestion(suggestion_id)
                self.assertIsNotNone(approved)
                result = store.cleanup_meeting("m300", delete_orphan_entities=True)
                self.assertEqual(result["deleted_orphan_agendas"], 1)
                self.assertEqual(store.list_agendas(), [])
            finally:
                store.close()

    def test_suggestion_can_merge_into_existing_entity(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                existing_id = store.create_project(name="Website refresh", description="", meeting_id="m1")
                suggestion_id = store.upsert_suggestion(
                    kind="project",
                    title="Website refresh",
                    normalized_key="website refresh",
                    source_meeting_id="m2",
                    source_kind="edited",
                    source_alias="A77",
                    confidence=0.82,
                    reasoning_short="Similar project suggestion",
                    evidence=[{"text": "Project: Website refresh"}],
                )
                approved = store.approve_suggestion_into_existing(suggestion_id, entity_id=existing_id)
                self.assertIsNotNone(approved)
                self.assertEqual(approved["entity_id"], existing_id)
                projects_for_m2 = store.list_projects_for_meeting("m2")
                self.assertTrue(any(row["id"] == existing_id for row in projects_for_m2))
                suggestions = store.list_suggestions(state=None, meeting_id="m2")
                row = next(item for item in suggestions if item["id"] == suggestion_id)
                self.assertEqual(row["state"], "approved")
                self.assertEqual(row["approved_entity_id"], existing_id)
            finally:
                store.close()

    def test_manual_transcript_source_can_be_cleaned_by_artifact_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                task_id = store.create_task(
                    title="Send recap",
                    meeting_id="m400",
                    source_kind="transcript_selection",
                    source_alias="tx01",
                    original_text="Please send the recap after the call",
                )
                tasks = store.list_tasks_for_meeting("m400")
                self.assertTrue(any(row["id"] == task_id for row in tasks))
                result = store.cleanup_artifact_source(
                    meeting_id="m400",
                    source_kind="transcript_selection",
                    source_alias="tx01",
                    delete_orphan_entities=False,
                )
                self.assertEqual(result["task_mentions"], 1)
                tasks_after = store.list_tasks_for_meeting("m400")
                self.assertFalse(any(row["id"] == task_id for row in tasks_after))
                self.assertEqual(len(store.list_tasks()), 1)
            finally:
                store.close()

    def test_preview_artifact_alias_cleanup_includes_transcript_selection_and_orphans(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                store.upsert_suggestion(
                    kind="task",
                    title="Send recap",
                    normalized_key="send recap",
                    source_meeting_id="m410",
                    source_kind="transcript",
                    source_alias="tx02",
                    confidence=0.73,
                    reasoning_short="Action phrase in transcript",
                    evidence=[{"text": "Please send the recap after the call"}],
                )
                task_id = store.create_task(
                    title="Send recap",
                    meeting_id="m410",
                    source_kind="transcript_selection",
                    source_alias="tx02",
                    original_text="Please send the recap after the call",
                )
                preview = store.preview_artifact_alias_cleanup(
                    meeting_id="m410",
                    artifact_kind="transcript",
                    source_alias="tx02",
                )
                self.assertEqual(preview["suggestions"], 1)
                self.assertEqual(preview["task_mentions"], 1)
                self.assertEqual(preview["orphan_tasks"], 1)
                self.assertTrue(any(row["id"] == task_id for row in store.list_tasks_for_meeting("m410")))
            finally:
                store.close()

    def test_cleanup_artifact_alias_deletes_only_orphans_affected_by_that_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                affected_task_id = store.create_task(
                    title="Task from summary",
                    meeting_id="m420",
                    source_kind="summary",
                    source_alias="A10",
                    original_text="Do the summary task",
                )
                unrelated_orphan_id = store.create_task(title="Old unrelated orphan")
                result = store.cleanup_artifact_alias(
                    meeting_id="m420",
                    artifact_kind="summary",
                    source_alias="A10",
                    delete_orphan_entities=True,
                )
                self.assertEqual(result["task_mentions"], 1)
                self.assertEqual(result["deleted_orphan_tasks"], 1)
                task_ids = {row["id"] for row in store.list_tasks()}
                self.assertNotIn(affected_task_id, task_ids)
                self.assertIn(unrelated_orphan_id, task_ids)
            finally:
                store.close()

    def test_preview_artifact_source_cleanup_counts_exact_source(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                store.upsert_suggestion(
                    kind="project",
                    title="Website refresh",
                    normalized_key="website refresh",
                    source_meeting_id="m430",
                    source_kind="edited",
                    source_alias="A30",
                    confidence=0.81,
                    reasoning_short="Explicit project mention",
                    evidence=[{"text": "Project: Website refresh"}],
                )
                store.create_project(
                    name="Website refresh",
                    meeting_id="m430",
                    source_kind="edited",
                    source_alias="A30",
                    original_text="Project: Website refresh",
                )
                preview = store.preview_artifact_source_cleanup(
                    meeting_id="m430",
                    source_kind="edited",
                    source_alias="A30",
                )
                self.assertEqual(preview["suggestions"], 1)
                self.assertEqual(preview["project_mentions"], 1)
                self.assertEqual(preview["orphan_projects"], 1)
            finally:
                store.close()

    def test_prepare_artifact_source_cleanup_adds_policy_flags_and_totals(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                store.upsert_suggestion(
                    kind="project",
                    title="Website refresh",
                    normalized_key="website refresh",
                    source_meeting_id="m430b",
                    source_kind="edited",
                    source_alias="A30",
                    confidence=0.81,
                    reasoning_short="Explicit project mention",
                    evidence=[{"text": "Project: Website refresh"}],
                )
                store.create_project(
                    name="Website refresh",
                    meeting_id="m430b",
                    source_kind="edited",
                    source_alias="A30",
                    original_text="Project: Website refresh",
                )
                policy = store.prepare_artifact_source_cleanup(
                    meeting_id="m430b",
                    source_kind="edited",
                    source_alias="A30",
                )
                self.assertTrue(bool(policy["has_changes"]))
                self.assertTrue(bool(policy["has_orphans"]))
                self.assertEqual(int(policy["touched_total"]), 2)
                self.assertEqual(int(policy["orphan_total"]), 1)
            finally:
                store.close()

    def test_list_rows_include_provenance_stats(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            store = ManagementStore(app_root)
            try:
                task_id = store.create_task(
                    title="Send recap",
                    meeting_id="m440",
                    source_kind="manual",
                    source_alias="manual-ui",
                    original_text="Send recap",
                )
                suggestion_id = store.upsert_suggestion(
                    kind="task",
                    title="Send recap",
                    normalized_key="send recap",
                    source_meeting_id="m441",
                    source_kind="summary",
                    source_alias="A12",
                    confidence=0.88,
                    reasoning_short="Explicit task",
                    evidence=[{"text": "Send recap"}],
                )
                approved = store.approve_suggestion_into_existing(suggestion_id, entity_id=task_id)
                self.assertIsNotNone(approved)
                row = next(item for item in store.list_tasks() if item["id"] == task_id)
                self.assertEqual(row["manual_mentions"], 1)
                self.assertEqual(row["ai_mentions"], 1)
                self.assertEqual(row["mention_count"], 2)
                self.assertEqual(set(row["source_kinds"]), {"manual", "summary"})
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
