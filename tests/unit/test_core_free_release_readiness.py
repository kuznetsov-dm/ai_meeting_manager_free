import json
import sys
import unittest
from pathlib import Path
from unittest import mock

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from aimn.plugins.interfaces import Artifact, ArtifactMeta, HookContext, KIND_ASR_SEGMENTS_JSON, KIND_EDITED
from plugins.text_processing.minutes_heuristic_v2.minutes_heuristic_v2 import MinutesHeuristicV2Plugin
from plugins.text_processing.semantic_refiner.semantic_refiner import Plugin as SemanticRefinerPlugin


class TestCoreFreeReleaseReadiness(unittest.TestCase):
    def test_minutes_heuristic_produces_summary_without_llm_model(self) -> None:
        plugin = MinutesHeuristicV2Plugin(
            summary_mode="hybrid",
            actions_mode="hybrid",
            model_id="intfloat/multilingual-e5-base",
            allow_download=False,
        )
        segments = [
            {"start": 0.0, "end": 3.0, "text": "Today we reviewed the local release plan for the base version."},
            {"start": 4.0, "end": 8.0, "text": "We need smoke tests and package delivery checks before Friday."},
            {"start": 9.0, "end": 12.0, "text": "The team decided to keep management empty in the free version."},
        ]
        ctx = HookContext(
            plugin_id="text_processing.minutes_heuristic_v2",
            meeting_id="meeting-core-free",
            alias=None,
            input_text=" ".join(item["text"] for item in segments),
            plugin_config={},
            _get_artifact=lambda kind: Artifact(
                meta=ArtifactMeta(
                    kind=KIND_ASR_SEGMENTS_JSON,
                    path="segments.json",
                    content_type="application/json",
                ),
                content=json.dumps(segments, ensure_ascii=False),
            )
            if kind == KIND_ASR_SEGMENTS_JSON
            else None,
        )

        with mock.patch.object(plugin, "_load_model", return_value=None):
            with mock.patch(
                "plugins.text_processing.minutes_heuristic_v2.minutes_heuristic_v2.utils.get_last_sentence_transformer_status",
                return_value="runtime_missing",
            ):
                result = plugin.run(ctx)

        self.assertTrue(any(item.startswith("minutes_heuristic_v2_model_missing:") for item in result.warnings))
        self.assertTrue(any(item.startswith("minutes_heuristic_v2_runtime_missing:") for item in result.warnings))
        self.assertIn("<!-- heuristic_fallback -->", result.outputs[0].content)
        self.assertIn("# ", result.outputs[0].content)
        self.assertIn("## Summary", result.outputs[0].content)
        self.assertIn("## Action Items", result.outputs[0].content)
        self.assertIn("## Decisions", result.outputs[0].content)
        self.assertEqual(result.outputs[0].kind, KIND_EDITED)

    def test_semantic_refiner_produces_structured_transcript_without_external_services(self) -> None:
        plugin = SemanticRefinerPlugin()
        ctx = HookContext(
            plugin_id="text_processing.semantic_refiner",
            meeting_id="meeting-core-free",
            alias=None,
            input_text=(
                "Today the Apogee team discussed the Core Free release. "
                "We need to verify model onboarding and prepare release notes for Windows users."
            ),
            plugin_config={"extract_keywords": True, "min_block_length": 40},
        )

        result = plugin.hook_postprocess(ctx)
        by_kind = {item.kind: item for item in result.outputs}

        self.assertIn(KIND_EDITED, by_kind)
        self.assertIn("semantic_blocks", by_kind)
        self.assertIn("important_keywords", by_kind)
        self.assertIn("# Structured Transcript", by_kind[KIND_EDITED].content)
        self.assertIn("## Block 1.", by_kind[KIND_EDITED].content)
        self.assertIn("Apogee", by_kind["important_keywords"].content)

    def test_semantic_refiner_uses_embeddings_when_model_is_available(self) -> None:
        plugin = SemanticRefinerPlugin()
        ctx = HookContext(
            plugin_id="text_processing.semantic_refiner",
            meeting_id="meeting-semantic-embeddings",
            alias=None,
            input_text=(
                "Apogee platform release planning started today. "
                "The team discussed onboarding flow and semantic search quality. "
                "Next we aligned the rollout checklist for Windows users."
            ),
            plugin_config={
                "extract_keywords": True,
                "min_block_length": 40,
                "embeddings_enabled": True,
                "embeddings_model_id": "intfloat/multilingual-e5-base",
            },
        )

        class FakeModel:
            def encode(self, rows):
                vectors = []
                for row in rows:
                    text = str(row).lower()
                    vectors.append(
                        [
                            1.0 if "apogee" in text or "platform" in text else 0.1,
                            1.0 if "search" in text or "semantic" in text else 0.1,
                            1.0 if "windows" in text or "rollout" in text else 0.1,
                        ]
                    )
                return vectors

        with mock.patch(
            "plugins.text_processing.semantic_refiner.semantic_refiner.utils.try_sentence_transformer",
            return_value=FakeModel(),
        ) as load_mock:
            result = plugin.hook_postprocess(ctx)

        by_kind = {item.kind: item for item in result.outputs}
        self.assertTrue(load_mock.called)
        self.assertIn("semantic_blocks", by_kind)
        self.assertIn("important_keywords", by_kind)
        self.assertEqual(result.warnings, [])
        self.assertIn("# Structured Transcript", by_kind[KIND_EDITED].content)
        self.assertIn("Apogee", by_kind["important_keywords"].content)

    def test_semantic_refiner_enables_download_by_default_for_embeddings_model(self) -> None:
        plugin = SemanticRefinerPlugin()
        ctx = HookContext(
            plugin_id="text_processing.semantic_refiner",
            meeting_id="meeting-semantic-bootstrap",
            alias=None,
            input_text="Semantic search quality depends on stable embeddings for this run.",
            plugin_config={
                "embeddings_enabled": True,
                "embeddings_model_id": "intfloat/multilingual-e5-base",
            },
        )

        with mock.patch(
            "plugins.text_processing.semantic_refiner.semantic_refiner.utils.try_sentence_transformer",
            return_value=None,
        ) as load_mock, mock.patch(
            "plugins.text_processing.semantic_refiner.semantic_refiner.utils.get_last_sentence_transformer_status",
            return_value="model_missing",
        ), mock.patch(
            "plugins.text_processing.semantic_refiner.semantic_refiner.utils.get_last_sentence_transformer_error_detail",
            return_value="",
        ):
            result = plugin.hook_postprocess(ctx)

        self.assertTrue(load_mock.called)
        self.assertTrue(load_mock.call_args.kwargs["allow_download"])
        self.assertEqual(
            result.warnings.count("semantic_refiner_model_missing:intfloat/multilingual-e5-base"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
