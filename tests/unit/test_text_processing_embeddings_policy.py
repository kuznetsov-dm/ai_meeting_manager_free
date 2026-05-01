import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


from aimn.core.plugins_config import PluginsConfig  # noqa: E402
from aimn.core.stages.text_processing import TextProcessingAdapter  # noqa: E402
from plugins.text_processing.minutes_heuristic_v2.minutes_heuristic_v2 import MinutesHeuristicV2Plugin  # noqa: E402
from plugins.text_processing.semantic_refiner.semantic_refiner import SemanticRefiner  # noqa: E402


class TestTextProcessingEmbeddingsPolicy(unittest.TestCase):
    def _adapter(self) -> TextProcessingAdapter:
        return TextProcessingAdapter(
            policy=SimpleNamespace(stage_id="text_processing"),
            config=PluginsConfig({}),
        )

    def test_minutes_plugin_keeps_embeddings_enabled_and_allows_download(self) -> None:
        adapter = self._adapter()
        emitted: list[str] = []
        context = SimpleNamespace(
            event_callback=lambda event: emitted.append(str(getattr(event, "message", "") or ""))
        )
        public_params = {
            "models": [
                {"model_id": "intfloat/multilingual-e5-base", "favorite": True},
                {"model_id": "intfloat/multilingual-e5-small"},
            ]
        }

        with patch("aimn.core.stages.text_processing.embeddings_available", return_value=False):
            updated_public, updated_run = adapter._apply_embeddings_fallback(
                context,
                "text_processing.minutes_heuristic_v2",
                public_params,
                {},
            )

        self.assertEqual(updated_public["embeddings_model_id"], "intfloat/multilingual-e5-base")
        self.assertEqual(updated_run["embeddings_model_id"], "intfloat/multilingual-e5-base")
        self.assertTrue(updated_public["embeddings_enabled"])
        self.assertTrue(updated_run["embeddings_enabled"])
        self.assertTrue(updated_public["embeddings_allow_download"])
        self.assertTrue(updated_run["embeddings_allow_download"])
        self.assertTrue(updated_public["allow_download"])
        self.assertTrue(updated_run["allow_download"])
        self.assertIn(
            "embeddings_required_download:text_processing.minutes_heuristic_v2:intfloat/multilingual-e5-base",
            emitted,
        )

    def test_plugin_without_embeddings_catalog_is_left_untouched(self) -> None:
        adapter = self._adapter()
        emitted: list[str] = []
        context = SimpleNamespace(
            event_callback=lambda event: emitted.append(str(getattr(event, "message", "") or ""))
        )

        with patch("aimn.core.stages.text_processing.embeddings_available") as available_mock:
            updated_public, updated_run = adapter._apply_embeddings_fallback(
                context,
                "text_processing.semantic_refiner",
                {},
                {},
            )

        self.assertEqual(updated_public, {})
        self.assertEqual(updated_run, {})
        self.assertEqual(emitted, [])
        available_mock.assert_not_called()

    def test_minutes_plugin_defaults_to_allow_download_when_embeddings_enabled(self) -> None:
        plugin = MinutesHeuristicV2Plugin(
            embeddings_enabled=True,
            embeddings_model_id="intfloat/multilingual-e5-base",
        )

        self.assertTrue(plugin.embeddings_enabled)
        self.assertTrue(plugin.allow_download)

    def test_minutes_plugin_ignores_disable_flags_for_embeddings(self) -> None:
        plugin = MinutesHeuristicV2Plugin(
            embeddings_enabled=False,
            embeddings_allow_download=False,
            allow_download=False,
            embeddings_model_id="intfloat/multilingual-e5-base",
        )

        self.assertTrue(plugin.embeddings_enabled)
        self.assertTrue(plugin.allow_download)

    def test_semantic_refiner_ignores_disable_flags_for_embeddings(self) -> None:
        plugin = SemanticRefiner(
            extract_keywords=True,
            min_block_length=100,
            keyword_limit=10,
            similarity_threshold=0.72,
            model_id="intfloat/multilingual-e5-base",
            model_path="",
            allow_download=False,
            embeddings_enabled=False,
        )

        self.assertTrue(plugin.embeddings_enabled)
        self.assertTrue(plugin.allow_download)


if __name__ == "__main__":
    unittest.main()
