import sys
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.stages.llm_processing import (  # noqa: E402
    _llm_stage_progress_percent,
    _variant_model_key,
)


class TestLlmProcessingModelKeys(unittest.TestCase):
    def test_variant_model_key_keeps_canonical_model_id(self) -> None:
        self.assertEqual(
            _variant_model_key({"model_id": "Qwen/Qwen3-1.7B-GGUF"}),
            "Qwen/Qwen3-1.7B-GGUF",
        )

    def test_variant_model_key_uses_filename_for_model_path(self) -> None:
        self.assertEqual(
            _variant_model_key({"model_path": "models/llama/Qwen3-1.7B-Q8_0.gguf"}),
            "Qwen3-1.7B-Q8_0.gguf",
        )

    def test_llm_stage_progress_percent_reports_nonzero_while_first_variant_is_running(self) -> None:
        self.assertEqual(
            _llm_stage_progress_percent(completed_steps=0, total_steps=4, active_variant=True),
            3,
        )

    def test_llm_stage_progress_percent_keeps_terminal_completion_at_100(self) -> None:
        self.assertEqual(
            _llm_stage_progress_percent(completed_steps=4, total_steps=4, active_variant=False),
            100,
        )


if __name__ == "__main__":
    unittest.main()
