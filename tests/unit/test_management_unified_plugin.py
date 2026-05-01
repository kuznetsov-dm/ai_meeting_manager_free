import json
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
from aimn.plugins.interfaces import Artifact, ArtifactMeta, HookContext  # noqa: E402
from plugins.management.unified.unified import hook_unified_management  # noqa: E402


class TestManagementUnifiedPlugin(unittest.TestCase):
    def test_hook_prefers_summary_over_edited_when_both_are_available(self) -> None:
        edited_text = "\n".join(
            [
                "## Action Items",
                "- [ ] Prepare launch memo",
            ]
        )
        summary_text = "\n".join(
            [
                "## Action Items",
                "- [ ] Send executive recap",
            ]
        )
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            ctx = HookContext(
                plugin_id="management.unified",
                meeting_id="m-summary-priority",
                alias="mg00",
                plugin_config={},
                _output_dir=str(output_dir),
                _schema_resolver=lambda kind: (
                    __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                        content_type="json",
                        user_visible=True,
                    )
                    if str(kind) == "management_suggestions"
                    else None
                ),
                _get_artifact=lambda kind: (
                    Artifact(
                        meta=ArtifactMeta(kind="summary", path="m__L01.summary.md", content_type="text/markdown"),
                        content=summary_text,
                    )
                    if str(kind) == "summary"
                    else Artifact(
                        meta=ArtifactMeta(kind="edited", path="m__E01.edited.md", content_type="text/markdown"),
                        content=edited_text,
                    )
                    if str(kind) == "edited"
                    else None
                ),
            )

            hook_unified_management(ctx)
            built = ctx.build_result()
            payload = json.loads(built.outputs[0].content)

        self.assertEqual([item["title"] for item in payload], ["Send executive recap"])
        self.assertEqual(payload[0]["source_kind"], "summary")
        self.assertEqual(payload[0]["source_alias"], "L01")

    def test_hook_extracts_russian_summary_sections_without_checkboxes(self) -> None:
        summary_text = "\n".join(
            [
                "### Тема встречи",
                "Портал поставщиков",
                "",
                "### Задачи, поручения, активности",
                "- Подготовить инструкцию для пользователей",
                "- Назначить роли руководителям",
                "",
                "### Названия проектов",
                "- Портал поставщиков",
                "- Витрина Фреш",
            ]
        )
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            ctx = HookContext(
                plugin_id="management.unified",
                meeting_id="m-ru-summary",
                alias="mg-ru",
                plugin_config={},
                _output_dir=str(output_dir),
                _schema_resolver=lambda kind: (
                    __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                        content_type="json",
                        user_visible=True,
                    )
                    if str(kind) == "management_suggestions"
                    else None
                ),
                _get_artifact=lambda kind: (
                    Artifact(
                        meta=ArtifactMeta(kind="summary", path="m__RU01.summary.md", content_type="text/markdown"),
                        content=summary_text,
                    )
                    if str(kind) == "summary"
                    else None
                ),
            )

            hook_unified_management(ctx)
            built = ctx.build_result()
            payload = json.loads(built.outputs[0].content)

        titles = {item["title"] for item in payload}
        kinds = {item["kind"] for item in payload}
        self.assertIn("Подготовить инструкцию для пользователей", titles)
        self.assertIn("Назначить роли руководителям", titles)
        self.assertIn("Портал поставщиков", titles)
        self.assertIn("Витрина Фреш", titles)
        self.assertEqual(kinds, {"task", "project"})

    def test_hook_writes_suggestions_artifact_and_does_not_create_approved_entities(self) -> None:
        text = "\n".join(
            [
                "## Projects Discussed",
                "- Website refresh",
                "",
                "## Action Items",
                "- [ ] Prepare launch memo",
                "",
                "## Planned Agenda",
                "1. Budget review",
                "2. Risks",
            ]
        )
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            ctx = HookContext(
                plugin_id="management.unified",
                meeting_id="m-unified",
                alias="mg01",
                plugin_config={},
                _output_dir=str(output_dir),
                _schema_resolver=lambda kind: (
                    __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                        content_type="json",
                        user_visible=True,
                    )
                    if str(kind) == "management_suggestions"
                    else None
                ),
                _get_artifact=lambda kind: (
                    Artifact(
                        meta=ArtifactMeta(kind="edited", path="m__A01.edited.md", content_type="text/markdown"),
                        content=text,
                    )
                    if str(kind) == "edited"
                    else None
                ),
            )
            result = hook_unified_management(ctx)
            self.assertIsNone(result)
            built = ctx.build_result()
            self.assertEqual(len(built.outputs), 1)
            payload = json.loads(built.outputs[0].content)
            kinds = {str(item.get("kind", "") or "") for item in payload}
            self.assertEqual(kinds, {"task", "project", "agenda"})

            store = ManagementStore(output_dir.parent)
            try:
                self.assertEqual(store.list_tasks(), [])
                self.assertEqual(store.list_projects(), [])
                self.assertEqual(store.list_agendas(), [])
                suggestions = store.list_suggestions(meeting_id="m-unified")
                self.assertEqual(len(suggestions), 3)
            finally:
                store.close()

    def test_hook_rejects_generic_candidates_and_writes_only_validated_batch(self) -> None:
        text = "\n".join(
            [
                "## Projects Discussed",
                "- Projects",
                "- Website refresh",
                "",
                "## Action Items",
                "- [ ] Follow up",
                "- [ ] Prepare launch memo",
            ]
        )
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            ctx = HookContext(
                plugin_id="management.unified",
                meeting_id="m-validated",
                alias="mg02",
                plugin_config={},
                _output_dir=str(output_dir),
                _schema_resolver=lambda kind: (
                    __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                        content_type="json",
                        user_visible=True,
                    )
                    if str(kind) == "management_suggestions"
                    else None
                ),
                _get_artifact=lambda kind: (
                    Artifact(
                        meta=ArtifactMeta(kind="edited", path="m__A02.edited.md", content_type="text/markdown"),
                        content=text,
                    )
                    if str(kind) == "edited"
                    else None
                ),
            )
            hook_unified_management(ctx)
            built = ctx.build_result()
            payload = json.loads(built.outputs[0].content)
            self.assertEqual(len(payload), 2)
            self.assertEqual({item["kind"] for item in payload}, {"task", "project"})
            self.assertEqual({item["title"] for item in payload}, {"Prepare launch memo", "Website refresh"})

    def test_hook_hides_stale_suggestions_for_same_source_on_rerun(self) -> None:
        first_text = "\n".join(
            [
                "## Action Items",
                "- [ ] Prepare launch memo",
            ]
        )
        second_text = "\n".join(
            [
                "## Action Items",
                "- [ ] Send recap",
            ]
        )

        def _make_ctx(output_dir: Path, text: str) -> HookContext:
            return HookContext(
                plugin_id="management.unified",
                meeting_id="m-rerun",
                alias="mg03",
                plugin_config={},
                _output_dir=str(output_dir),
                _schema_resolver=lambda kind: (
                    __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                        content_type="json",
                        user_visible=True,
                    )
                    if str(kind) == "management_suggestions"
                    else None
                ),
                _get_artifact=lambda kind: (
                    Artifact(
                        meta=ArtifactMeta(kind="edited", path="m__A03.edited.md", content_type="text/markdown"),
                        content=text,
                    )
                    if str(kind) == "edited"
                    else None
                ),
            )

        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            hook_unified_management(_make_ctx(output_dir, first_text))
            hook_unified_management(_make_ctx(output_dir, second_text))

            store = ManagementStore(output_dir.parent)
            try:
                all_rows = store.list_suggestions(state=None, meeting_id="m-rerun")
                states = {str(item["title"]): str(item["state"]) for item in all_rows}
                self.assertEqual(states["Prepare launch memo"], "hidden")
                self.assertEqual(states["Send recap"], "suggested")
                shown = store.list_suggestions(meeting_id="m-rerun")
                self.assertEqual([item["title"] for item in shown], ["Send recap"])
            finally:
                store.close()

    def test_hook_prefers_transcript_segment_evidence_when_segments_are_available(self) -> None:
        text = "\n".join(
            [
                "## Action Items",
                "- [ ] Prepare launch memo",
            ]
        )
        segments = json.dumps(
            [
                {
                    "index": 3,
                    "start_ms": 125000,
                    "end_ms": 138000,
                    "text": "Please prepare launch memo by Friday",
                    "speaker": "Ivan",
                    "confidence": 0.91,
                }
            ]
        )
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            ctx = HookContext(
                plugin_id="management.unified",
                meeting_id="m-transcript-evidence",
                alias="mg04",
                plugin_config={},
                _output_dir=str(output_dir),
                _schema_resolver=lambda kind: (
                    __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                        content_type="json",
                        user_visible=True,
                    )
                    if str(kind) == "management_suggestions"
                    else None
                ),
                _get_artifact=lambda kind: (
                    Artifact(
                        meta=ArtifactMeta(kind="edited", path="m__A04.edited.md", content_type="text/markdown"),
                        content=text,
                    )
                    if str(kind) == "edited"
                    else Artifact(
                        meta=ArtifactMeta(kind="segments", path="m__T04.segments.json", content_type="application/json"),
                        content=segments,
                    )
                    if str(kind) == "segments"
                    else None
                ),
            )
            hook_unified_management(ctx)
            built = ctx.build_result()
            payload = json.loads(built.outputs[0].content)
            self.assertEqual(len(payload), 1)
            evidence = payload[0]["evidence"][0]
            self.assertEqual(evidence["source"], "transcript")
            self.assertEqual(evidence["alias"], "T04")
            self.assertEqual(evidence["segment_index"], 3)
            self.assertEqual(evidence["segment_index_start"], 3)
            self.assertEqual(evidence["segment_index_end"], 3)
            self.assertEqual(evidence["start_ms"], 125000)
            self.assertEqual(evidence["speaker"], "Ivan")

    def test_hook_matches_transcript_window_across_neighbor_segments(self) -> None:
        text = "\n".join(
            [
                "## Action Items",
                "- [ ] Prepare launch memo by Friday",
            ]
        )
        segments = json.dumps(
            [
                {
                    "index": 7,
                    "start_ms": 210000,
                    "end_ms": 216000,
                    "text": "Let's have Ivan prepare the",
                    "speaker": "Ivan",
                    "confidence": 0.9,
                },
                {
                    "index": 8,
                    "start_ms": 216001,
                    "end_ms": 225000,
                    "text": "launch memo by Friday and send it around",
                    "speaker": "Ivan",
                    "confidence": 0.92,
                },
            ]
        )
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            ctx = HookContext(
                plugin_id="management.unified",
                meeting_id="m-transcript-window",
                alias="mg05",
                plugin_config={},
                _output_dir=str(output_dir),
                _schema_resolver=lambda kind: (
                    __import__("aimn.plugins.api", fromlist=["ArtifactSchema"]).ArtifactSchema(
                        content_type="json",
                        user_visible=True,
                    )
                    if str(kind) == "management_suggestions"
                    else None
                ),
                _get_artifact=lambda kind: (
                    Artifact(
                        meta=ArtifactMeta(kind="edited", path="m__A05.edited.md", content_type="text/markdown"),
                        content=text,
                    )
                    if str(kind) == "edited"
                    else Artifact(
                        meta=ArtifactMeta(kind="segments", path="m__T05.segments.json", content_type="application/json"),
                        content=segments,
                    )
                    if str(kind) == "segments"
                    else None
                ),
            )
            hook_unified_management(ctx)
            built = ctx.build_result()
            payload = json.loads(built.outputs[0].content)
            self.assertEqual(len(payload), 1)
            evidence = payload[0]["evidence"][0]
            self.assertEqual(evidence["source"], "transcript")
            self.assertEqual(evidence["alias"], "T05")
            self.assertEqual(evidence["segment_index"], 7)
            self.assertEqual(evidence["segment_index_start"], 7)
            self.assertEqual(evidence["segment_index_end"], 8)
            self.assertEqual(evidence["start_ms"], 210000)
            self.assertEqual(evidence["end_ms"], 225000)
            self.assertEqual(evidence["speaker"], "Ivan")


if __name__ == "__main__":
    unittest.main()
