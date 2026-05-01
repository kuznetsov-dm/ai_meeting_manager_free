import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.services.embeddings_availability import embeddings_available  # noqa: E402


class TestEmbeddingsAvailability(unittest.TestCase):
    def test_model_path_relative_to_app_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path = root / "models" / "embeddings" / "custom.bin"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_text("x", encoding="utf-8")
            self.assertTrue(
                embeddings_available(
                    model_id=None,
                    model_path="models/embeddings/custom.bin",
                    app_root=root,
                )
            )

    def test_model_id_detected_in_embeddings_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models_dir = root / "models" / "embeddings" / "sentence-transformers" / "all-MiniLM-L6-v2"
            models_dir.mkdir(parents=True, exist_ok=True)
            (models_dir / "config.json").write_text("{}", encoding="utf-8")
            (models_dir / "modules.json").write_text("[]", encoding="utf-8")
            (models_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
            (models_dir / "pytorch_model.bin").write_bytes(b"x")
            self.assertTrue(
                embeddings_available(
                    model_id="sentence-transformers/all-MiniLM-L6-v2",
                    model_path=None,
                    app_root=root,
                )
            )

    def test_models_dir_any(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models_dir = root / "models" / "embeddings"
            models_dir.mkdir(parents=True, exist_ok=True)
            (models_dir / "some.bin").write_text("x", encoding="utf-8")
            self.assertTrue(
                embeddings_available(
                    model_id=None,
                    model_path=None,
                    app_root=root,
                )
            )

    def test_missing_models_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertFalse(
                embeddings_available(
                    model_id="missing/model",
                    model_path=None,
                    app_root=root,
                )
            )


if __name__ == "__main__":
    unittest.main()
