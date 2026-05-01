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

from aimn.ui.widgets import model_cards as model_cards_mod  # noqa: E402


class TestModelCardsGatedLinks(unittest.TestCase):
    def test_preferred_model_link_uses_direct_resolve_url_when_file_known(self) -> None:
        meta = {
            "source_url": "https://huggingface.co/meta-llama/Llama-4-1.5B-Instruct-GGUF",
            "file": "llama-4-1.5b-instruct-q4_k_m.gguf",
        }

        link = model_cards_mod._preferred_model_link(meta, "meta-llama/Llama-4-1.5B-Instruct-GGUF")

        self.assertEqual(
            link,
            (
                "https://huggingface.co/meta-llama/Llama-4-1.5B-Instruct-GGUF/resolve/main/"
                "llama-4-1.5b-instruct-q4_k_m.gguf"
            ),
        )

    def test_is_gated_model_detects_explicit_and_known_hf_prefixes(self) -> None:
        self.assertTrue(
            model_cards_mod._is_gated_model(
                {"source_url": "https://huggingface.co/meta-llama/Llama-4-1.5B-Instruct-GGUF"},
                "meta-llama/Llama-4-1.5B-Instruct-GGUF",
            )
        )
        self.assertTrue(model_cards_mod._is_gated_model({"gated": True}, "org/model"))
        self.assertFalse(
            model_cards_mod._is_gated_model(
                {"source_url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF"},
                "Qwen/Qwen3-4B-GGUF",
            )
        )

    def test_gated_tooltip_contains_credentials_instructions_and_links(self) -> None:
        labels = {
            "models.tooltip.gated_title": "This model is gated on Hugging Face.",
            "models.tooltip.gated_step_1": "1. Open the model page and request or accept access.",
            "models.tooltip.gated_step_2": "2. Create a User Access Token in Hugging Face settings.",
            "models.tooltip.gated_step_3": "3. Set HUGGINGFACE_HUB_TOKEN, HF_TOKEN, or AIMN_HF_TOKEN before downloading.",
            "models.tooltip.links": "Links:",
            "models.links.model_page": "Model page",
            "models.links.get_token": "Get token",
            "models.links.token_docs": "Token docs",
        }

        tooltip = model_cards_mod._gated_tooltip(
            labels,
            "https://huggingface.co/meta-llama/Llama-4-1.5B-Instruct-GGUF",
        )

        self.assertIn("HUGGINGFACE_HUB_TOKEN", tooltip)
        self.assertIn("https://huggingface.co/settings/tokens", tooltip)
        self.assertIn("https://huggingface.co/docs/hub/security-tokens", tooltip)
        self.assertIn("https://huggingface.co/meta-llama/Llama-4-1.5B-Instruct-GGUF", tooltip)


if __name__ == "__main__":
    unittest.main()
