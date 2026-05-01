import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.pipeline_worker import _should_emit_stage_progress_status


class TestPipelineWorker(unittest.TestCase):
    def test_should_emit_stage_progress_status_skips_blank_llm_progress(self) -> None:
        event = SimpleNamespace(stage_id="llm_processing", message="", progress=10)

        self.assertFalse(_should_emit_stage_progress_status(event))

    def test_should_emit_stage_progress_status_keeps_named_llm_progress(self) -> None:
        event = SimpleNamespace(stage_id="llm_processing", message="llm.llama_cli:Qwen3 (1/6)", progress=10)

        self.assertTrue(_should_emit_stage_progress_status(event))

    def test_should_emit_stage_progress_status_keeps_other_stage_progress(self) -> None:
        event = SimpleNamespace(stage_id="transcription", message="", progress=10)

        self.assertTrue(_should_emit_stage_progress_status(event))


if __name__ == "__main__":
    unittest.main()
