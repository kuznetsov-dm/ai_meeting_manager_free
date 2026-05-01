import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from plugins.service.meeting_topic_suggester.meeting_topic_suggester import (  # noqa: E402
    _extract_topics_from_text,
    action_suggest_topics,
)


def _manifest(base_name: str, summary_relpath: str) -> dict:
    return {
        "schema_version": "1.0",
        "meeting_id": "260214-1200_deadbeef",
        "base_name": base_name,
        "created_at": "2026-02-14T12:00:00Z",
        "updated_at": "2026-02-14T12:00:00Z",
        "storage": {"backend": "files", "output_dir_rel": "."},
        "source": {"items": []},
        "naming_mode": "single",
        "nodes": {
            "A01": {
                "stage_id": "llm_processing",
                "tool": {"plugin_id": "llm.openrouter", "version": "1.0.0"},
                "params": {},
                "inputs": {"source_ids": [], "parent_nodes": []},
                "fingerprint": "fp-A01",
                "cacheable": True,
                "artifacts": [
                    {
                        "kind": "summary",
                        "path": summary_relpath,
                        "content_type": "text/markdown",
                        "user_visible": True,
                        "meta": {},
                    }
                ],
                "created_at": "2026-02-14T12:00:00Z",
            }
        },
        "segments_index": [],
    }


class TestMeetingTopicSuggesterPlugin(unittest.TestCase):
    def test_extract_topics_from_text(self) -> None:
        text = "\n".join(
            [
                "ТЕМА: Release planning for Q2",
                "",
                "## Topics",
                "- API hardening",
                "- API hardening",
                "- Budget alignment",
            ]
        )
        topics = _extract_topics_from_text(text)
        self.assertIn("Release planning for Q2", topics)
        self.assertIn("API hardening", topics)
        self.assertIn("Budget alignment", topics)
        self.assertEqual(len(topics), 3)

    def test_action_suggest_topics_reads_llm_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            app_root = Path(tmp)
            output = app_root / "output"
            output.mkdir(parents=True, exist_ok=True)

            base = "260214-1200_demo_meeting"
            summary_rel = f"{base}__A01.summary.md"
            summary_text = "\n".join(
                [
                    "# Summary",
                    "ТЕМА: Platform migration and reliability",
                    "## Topics",
                    "- Error budget policy",
                ]
            )
            (output / summary_rel).write_text(summary_text, encoding="utf-8")
            (output / f"{base}__MEETING.json").write_text(
                json.dumps(_manifest(base, summary_rel), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"AIMN_HOME": str(app_root)}):
                result = action_suggest_topics({}, {"base_name": base})

            self.assertEqual(result.status, "ok")
            self.assertIsInstance(result.data, dict)
            suggestions = result.data.get("suggestions", [])
            self.assertTrue(isinstance(suggestions, list) and suggestions)
            titles = [str(item.get("title", "")) for item in suggestions if isinstance(item, dict)]
            self.assertIn("Platform migration and reliability", titles)
            self.assertIn("Error budget policy", titles)


if __name__ == "__main__":
    unittest.main()

