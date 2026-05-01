import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.core.stages.llm_processing import _load_agendas_catalog, _resolve_agenda_context


class TestLlmProcessingManagementContext(unittest.TestCase):
    def test_load_agendas_catalog_reads_management_store(self) -> None:
        rows = [
            {"id": "a-1", "title": "Roadmap", "text": "Discuss roadmap"},
            {"id": "", "title": "Skip", "text": "ignored"},
        ]

        class _StoreStub:
            def __init__(self, _app_root: Path) -> None:
                self.closed = False

            def list_agendas(self) -> list[dict]:
                return list(rows)

            def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            with patch("aimn.core.stages.llm_processing.ManagementStore", _StoreStub):
                items = _load_agendas_catalog(Path(tmp))

        self.assertEqual(items, [{"id": "a-1", "title": "Roadmap", "text": "Discuss roadmap"}])

    def test_resolve_agenda_context_uses_management_store_when_id_selected(self) -> None:
        rows = [
            {"id": "agenda-1", "title": "Launch", "text": "Finalize launch plan"},
            {"id": "agenda-2", "title": "Retro", "text": "Inspect failures"},
        ]

        class _StoreStub:
            def __init__(self, _app_root: Path) -> None:
                pass

            def list_agendas(self) -> list[dict]:
                return list(rows)

            def close(self) -> None:
                return

        with tempfile.TemporaryDirectory() as tmp:
            with patch("aimn.core.stages.llm_processing.ManagementStore", _StoreStub):
                text, title = _resolve_agenda_context(
                    Path(tmp),
                    {"prompt_agenda_id": "agenda-1"},
                )

        self.assertEqual(title, "Launch")
        self.assertEqual(text, "Finalize launch plan")


if __name__ == "__main__":
    unittest.main()
