import sys
import unittest
from pathlib import Path
from unittest.mock import patch


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


from plugins.text_processing import utils  # noqa: E402


class TestTextProcessingUtils(unittest.TestCase):
    def test_ensure_embeddings_runtime_skips_bootstrap_when_download_disallowed(self) -> None:
        with patch("plugins.text_processing.utils._embeddings_runtime_ready", return_value=False), patch(
            "plugins.text_processing.utils.subprocess.run"
        ) as run_mock:
            ready, status = utils._ensure_embeddings_runtime(allow_download=False)

        self.assertFalse(ready)
        self.assertEqual(status, "runtime_missing")
        run_mock.assert_not_called()

    def test_ensure_embeddings_runtime_bootstraps_when_download_allowed(self) -> None:
        readiness = iter([False, False])

        with patch(
            "plugins.text_processing.utils._embeddings_runtime_ready",
            side_effect=lambda: next(readiness),
        ), patch("plugins.text_processing.utils.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            ready, status = utils._ensure_embeddings_runtime(allow_download=True)

        self.assertFalse(ready)
        self.assertEqual(status, "runtime_install_failed")
        run_mock.assert_called_once()
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:4], [sys.executable, "-m", "pip", "install"])
        self.assertEqual(command[4], "sentence-transformers")

    def test_try_sentence_transformer_keeps_last_probe_error_detail(self) -> None:
        with patch(
            "plugins.text_processing.utils._ensure_embeddings_runtime",
            return_value=(True, "ready"),
        ), patch(
            "plugins.text_processing.utils.os.name",
            "nt",
        ), patch(
            "plugins.text_processing.utils._SubprocessSentenceTransformerProxy.encode",
            side_effect=RuntimeError("403 Client Error: Forbidden for url"),
        ):
            model = utils.try_sentence_transformer(
                "intfloat/multilingual-e5-base",
                allow_download=True,
            )

        self.assertIsNone(model)
        self.assertEqual(utils.get_last_sentence_transformer_status(), "model_load_failed")
        self.assertTrue(utils.get_last_sentence_transformer_error_detail())

if __name__ == "__main__":
    unittest.main()
