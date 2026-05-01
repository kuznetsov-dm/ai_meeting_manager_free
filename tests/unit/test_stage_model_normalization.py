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

from aimn.ui.controllers.stage_model_normalization import (  # noqa: E402
    parse_variant_selection_state,
    selection_key,
)


class TestStageModelNormalization(unittest.TestCase):
    def test_selection_key_prefers_model_path(self) -> None:
        self.assertEqual(
            selection_key(model_id="remote-id", model_path="models/local.gguf"),
            "path:models/local.gguf",
        )

    def test_parse_variant_selection_state_collects_models_and_per_selection_params(self) -> None:
        state = parse_variant_selection_state(
            [
                {"plugin_id": "llm.local", "params": {"model_id": "missing"}},
                {"plugin_id": "llm.local", "params": {"model_id": "installed"}},
                {"plugin_id": "llm.remote", "params": {"model_path": "models/cloud.gguf"}},
            ]
        )

        self.assertEqual(state.plugin_ids, ["llm.local", "llm.local", "llm.remote"])
        self.assertEqual(state.params_by_plugin["llm.local"], {"model_id": "missing"})
        self.assertEqual(state.model_ids_by_plugin["llm.local"], ["missing", "installed"])
        self.assertEqual(
            state.selection_keys_by_plugin["llm.local"],
            ["id:missing", "id:installed"],
        )
        self.assertEqual(
            state.selection_params_by_plugin["llm.local"],
            [{"model_id": "missing"}, {"model_id": "installed"}],
        )


if __name__ == "__main__":
    unittest.main()
