import sys
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.stages.llm_processing import (  # noqa: E402
    _classify_summary_artifact,
    _describe_llm_variant_failure,
    _extract_markdown_section,
    _filter_management_entities_by_projects,
    _looks_invalid_summary_artifact,
)


class TestLlmProcessingSections(unittest.TestCase):
    def test_extracts_actions_and_decisions_sections(self) -> None:
        text = "\n".join(
            [
                "# Meeting Summary",
                "",
                "## Decisions",
                "- Approve budget",
                "- Move deadline",
                "",
                "## Action Items",
                "- [ ] Prepare deck",
                "",
                "## Notes",
                "- Something else",
            ]
        )
        decisions = _extract_markdown_section(text, titles=["decisions"])
        self.assertIn("Approve budget", decisions)
        self.assertNotIn("Prepare deck", decisions)
        actions = _extract_markdown_section(text, titles=["action items"])
        self.assertIn("Prepare deck", actions)
        self.assertNotIn("Approve budget", actions)

    def test_filters_management_entities_by_selected_project_ids(self) -> None:
        projects = [
            {"project_id": "p1", "name": "Alpha"},
            {"project_id": "p2", "name": "Beta"},
        ]
        tasks = [
            {"task_id": "t1", "title": "Task 1", "project_id": "p1", "project_ids": ["p1"]},
            {"task_id": "t2", "title": "Task 2", "project_id": "p2", "project_ids": ["p2"]},
            {"task_id": "t3", "title": "Task 3", "project_id": "", "project_ids": ["p2", "p3"]},
        ]

        filtered_projects, filtered_tasks = _filter_management_entities_by_projects(
            projects,
            tasks,
            selected_project_ids=["p2"],
        )

        self.assertEqual([item.get("project_id") for item in filtered_projects], ["p2"])
        self.assertEqual([item.get("task_id") for item in filtered_tasks], ["t2", "t3"])

    def test_describes_variant_failure_from_first_real_warning(self) -> None:
        failure = _describe_llm_variant_failure(
            "llm.llama_cli:Qwen/Qwen3-4B-GGUF",
            ["mock_fallback", "llama_cli_output_corrupted", "llama_cli_reasoning_stripped"],
        )
        self.assertEqual(
            failure,
            "llm.llama_cli:Qwen/Qwen3-4B-GGUF:llama_cli_output_corrupted",
        )

    def test_rejects_incomplete_summary_artifact(self) -> None:
        self.assertTrue(_looks_invalid_summary_artifact("### Тема встречи\nВн"))
        self.assertTrue(_looks_invalid_summary_artifact("<think>\nReasoning only"))
        self.assertFalse(
            _looks_invalid_summary_artifact(
                "### Тема встречи\nВнедрение портала\n\n### Краткое резюме встречи\nОбсудили запуск."
            )
        )

    def test_classifies_stub_summary_as_degraded(self) -> None:
        quality, issue = _classify_summary_artifact("# Summary\n\n(Model llama3.2 not available)")
        self.assertEqual(quality, "degraded")
        self.assertEqual(issue, "llm_degraded_summary_artifact")


if __name__ == "__main__":
    unittest.main()
