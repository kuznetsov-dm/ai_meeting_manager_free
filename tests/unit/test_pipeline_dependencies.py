import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.pipeline import PipelineEngine, StageContext, StagePolicy, StageResult, StageAdapter  # noqa: E402
from aimn.domain.meeting import MeetingManifest, SCHEMA_VERSION, SourceInfo, StorageInfo  # noqa: E402


class DummyStage(StageAdapter):
    def __init__(self, stage_id: str, policy: StagePolicy, status: str) -> None:
        super().__init__(stage_id=stage_id, policy=policy)
        self._status = status
        self.calls = 0
        self.force_run_values: list[bool] = []

    def run(self, context: StageContext) -> StageResult:
        self.calls += 1
        self.force_run_values.append(bool(context.force_run))
        error = "boom" if self._status == "failed" else None
        return StageResult(stage_id=self.stage_id, status=self._status, error=error)


def _make_meeting() -> MeetingManifest:
    return MeetingManifest(
        schema_version=SCHEMA_VERSION,
        meeting_id="250101-0000_abcd",
        base_name="250101-0000_meeting",
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
        storage=StorageInfo(),
        source=SourceInfo(),
    )


class TestPipelineDependencies(unittest.TestCase):
    def test_optional_stage_blocked_by_failed_dependency(self) -> None:
        stage_a = DummyStage("a", StagePolicy(stage_id="a", required=True), "failed")
        stage_b = DummyStage(
            "b",
            StagePolicy(stage_id="b", required=False, depends_on=["a"]),
            "success",
        )
        engine = PipelineEngine([stage_a, stage_b])
        result = engine.run(StageContext(meeting=_make_meeting()))
        self.assertEqual(result.stage_results[1].status, "skipped")
        self.assertEqual(result.stage_results[1].skip_reason, "dependency_failed:a")

    def test_required_stage_blocked_by_skipped_dependency(self) -> None:
        stage_a = DummyStage("a", StagePolicy(stage_id="a", required=False), "skipped")
        stage_b = DummyStage(
            "b",
            StagePolicy(stage_id="b", required=True, depends_on=["a"], continue_on_error=True),
            "success",
        )
        engine = PipelineEngine([stage_a, stage_b])
        result = engine.run(StageContext(meeting=_make_meeting()))
        self.assertEqual(result.stage_results[1].status, "failed")
        self.assertEqual(result.stage_results[1].error, "dependency_skipped:a")

    def test_missing_dependency_blocks_optional_stage(self) -> None:
        stage_b = DummyStage(
            "b",
            StagePolicy(stage_id="b", required=False, depends_on=["missing"]),
            "success",
        )
        engine = PipelineEngine([stage_b])
        result = engine.run(StageContext(meeting=_make_meeting()))
        self.assertEqual(result.stage_results[0].status, "skipped")
        self.assertEqual(result.stage_results[0].skip_reason, "dependency_missing:missing")

    def test_force_run_from_skips_earlier_stages_without_running_them(self) -> None:
        stage_a = DummyStage("a", StagePolicy(stage_id="a", required=True), "success")
        stage_b = DummyStage("b", StagePolicy(stage_id="b", required=True), "success")
        engine = PipelineEngine([stage_a, stage_b])

        result = engine.run(StageContext(meeting=_make_meeting(), force_run_from="b"))

        self.assertEqual(stage_a.calls, 0)
        self.assertEqual(stage_b.calls, 1)
        self.assertEqual(result.stage_results[0].status, "skipped")
        self.assertEqual(result.stage_results[0].skip_reason, "rerun_from:b")
        self.assertEqual(result.stage_results[1].status, "success")

    def test_force_run_from_does_not_block_dependencies_of_later_stages(self) -> None:
        stage_a = DummyStage("a", StagePolicy(stage_id="a", required=True), "success")
        stage_b = DummyStage("b", StagePolicy(stage_id="b", required=True, depends_on=["a"]), "success")
        stage_c = DummyStage("c", StagePolicy(stage_id="c", required=True, depends_on=["b"]), "success")
        engine = PipelineEngine([stage_a, stage_b, stage_c])

        result = engine.run(StageContext(meeting=_make_meeting(), force_run_from="b"))

        self.assertEqual(stage_a.calls, 0)
        self.assertEqual(stage_b.calls, 1)
        self.assertEqual(stage_c.calls, 1)
        self.assertEqual(result.stage_results[0].skip_reason, "rerun_from:b")
        self.assertEqual(result.stage_results[1].status, "success")
        self.assertEqual(result.stage_results[2].status, "success")

    def test_force_run_from_only_forces_selected_stage(self) -> None:
        stage_a = DummyStage("a", StagePolicy(stage_id="a", required=True), "success")
        stage_b = DummyStage("b", StagePolicy(stage_id="b", required=True), "success")
        stage_c = DummyStage("c", StagePolicy(stage_id="c", required=True, depends_on=["b"]), "success")
        engine = PipelineEngine([stage_a, stage_b, stage_c])

        result = engine.run(StageContext(meeting=_make_meeting(), force_run_from="b"))

        self.assertFalse(result.force_run)
        self.assertEqual(stage_a.calls, 0)
        self.assertEqual(stage_b.force_run_values, [True])
        self.assertEqual(stage_c.force_run_values, [False])

    def test_cancel_requested_returns_cancelled_result_before_next_stage(self) -> None:
        stage_a = DummyStage("a", StagePolicy(stage_id="a", required=True), "success")
        stage_b = DummyStage("b", StagePolicy(stage_id="b", required=True), "success")
        engine = PipelineEngine([stage_a, stage_b])
        events: list[str] = []
        cancelled = {"value": False}

        def _emit(event) -> None:
            events.append(str(event.event_type or ""))
            if str(event.event_type or "") == "stage_finished" and str(event.stage_id or "") == "a":
                cancelled["value"] = True

        result = engine.run(
            StageContext(meeting=_make_meeting(), cancel_requested=lambda: bool(cancelled["value"])),
            emit=_emit,
        )

        self.assertEqual(result.result, "cancelled")
        self.assertEqual(stage_a.calls, 1)
        self.assertEqual(stage_b.calls, 0)
        self.assertIn("pipeline_cancelled", events)


if __name__ == "__main__":
    unittest.main()
