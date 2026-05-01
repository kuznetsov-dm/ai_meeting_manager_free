import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)

from aimn.ui.widgets.meetings_workspace_v2 import MainTextPanelV2  # noqa: E402


class TestMainTextPanelCommandBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_copy_button_copies_current_artifact_text(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "Summary text")
        panel.set_artifacts(
            [SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing", relpath="summary.txt")],
            preferred_kind="summary",
        )

        self.assertTrue(panel._copy_btn.isEnabled())
        QApplication.clipboard().setText("")
        panel._copy_btn.click()
        self.assertEqual(QApplication.clipboard().text(), "Summary text")

    def test_export_targets_render_as_separate_buttons(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "Summary text")
        panel.set_artifacts(
            [SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing", relpath="summary.txt")],
            preferred_kind="summary",
        )
        panel.set_artifact_export_targets(
            [
                {"plugin_id": "integration.export_alpha", "action_id": "export_text", "label": "Alpha"},
                {"plugin_id": "integration.export_beta", "action_id": "export_text", "label": "Beta"},
            ]
        )

        emitted: list[tuple[str, str, str, str, str, str]] = []
        panel.artifactTextExportRequested.connect(
            lambda pid, aid, sid, alias, kind, text: emitted.append((pid, aid, sid, alias, kind, text))
        )

        self.assertEqual(len(panel._artifact_export_buttons), 2)
        panel._artifact_export_buttons[0].click()
        panel._artifact_export_buttons[1].click()

        self.assertEqual(len(emitted), 2)
        self.assertEqual(emitted[0][0], "integration.export_alpha")
        self.assertEqual(emitted[1][0], "integration.export_beta")
        self.assertEqual(emitted[0][2], "llm_processing")
        self.assertEqual(emitted[0][3], "v1")
        self.assertEqual(emitted[0][4], "summary")
        self.assertEqual(emitted[0][5], "Summary text")

    def test_selection_evidence_payload_maps_selection_to_segment_range(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "")
        editor = panel._make_editor("Alpha line\nBeta line\nGamma line")
        cursor = editor.textCursor()
        start = editor.toPlainText().index("Beta")
        end = start + len("Beta line")
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        ranges = [(0, 10), (11, 20), (21, 31)]
        records = [
            {"index": 0, "start_ms": 0, "end_ms": 1000, "speaker": "A"},
            {"index": 1, "start_ms": 1000, "end_ms": 2000, "speaker": "B"},
            {"index": 2, "start_ms": 2000, "end_ms": 3000, "speaker": "C"},
        ]
        payload = MainTextPanelV2._selection_evidence_payload(cursor, ranges, records)
        self.assertEqual(payload["segment_index_start"], 1)
        self.assertEqual(payload["segment_index_end"], 1)
        self.assertEqual(payload["start_ms"], 1000)
        self.assertEqual(payload["end_ms"], 2000)
        self.assertEqual(payload["speaker"], "B")

    def test_transcript_suggestion_spans_cover_segment_window(self) -> None:
        records = [
            {"index": 7, "start_ms": 210000, "end_ms": 216000, "text": "Let's have Ivan prepare the"},
            {"index": 8, "start_ms": 216001, "end_ms": 225000, "text": "launch memo by Friday and send it around"},
        ]
        transcript = "Let's have Ivan prepare the launch memo by Friday and send it around"
        ranges = MainTextPanelV2._build_segment_text_ranges(transcript, records)
        spans = MainTextPanelV2._build_transcript_suggestion_spans(
            records,
            ranges,
            [
                {
                    "id": "s-1",
                    "kind": "task",
                    "title": "Prepare launch memo by Friday",
                    "confidence": 0.86,
                    "evidence": [],
                    "transcript_evidence": [
                        {
                            "source": "transcript",
                            "alias": "T05",
                            "text": "prepare the launch memo by Friday",
                            "segment_index": 7,
                            "segment_index_start": 7,
                            "segment_index_end": 8,
                            "start_ms": 210000,
                            "end_ms": 225000,
                        }
                    ],
                }
            ],
        )
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].left, 0)
        self.assertEqual(spans[0].right, len(transcript))

    def test_meeting_context_applies_transcript_management_overlay(self) -> None:
        payloads = {
            "transcript.txt": "Let's have Ivan prepare the launch memo by Friday and send it around",
            "segments.json": """
            [
              {"index": 7, "start_ms": 210000, "end_ms": 216000, "text": "Let's have Ivan prepare the", "speaker": "Ivan"},
              {"index": 8, "start_ms": 216001, "end_ms": 225000, "text": "launch memo by Friday and send it around", "speaker": "Ivan"}
            ]
            """,
        }
        panel = MainTextPanelV2(lambda relpath: payloads[str(relpath)])
        panel.set_meeting_context(
            artifacts=[SimpleNamespace(kind="transcript", alias="T05", stage_id="transcription", relpath="transcript.txt")],
            segments_relpaths={"transcription:T05": "segments.json"},
            management_suggestions=[
                {
                    "id": "s-1",
                    "kind": "task",
                    "title": "Prepare launch memo by Friday",
                    "confidence": 0.86,
                    "evidence": [
                        {
                            "source": "transcript",
                            "alias": "T05",
                            "text": "prepare the launch memo by Friday",
                            "segment_index": 7,
                            "segment_index_start": 7,
                            "segment_index_end": 8,
                            "start_ms": 210000,
                            "end_ms": 225000,
                        }
                    ],
                }
            ],
            preferred_kind="transcript",
        )
        editor = panel._current_editor()
        self.assertIsNotNone(editor)
        overlay = panel._editor_layer_selections(editor, "overlay")
        self.assertEqual(len(overlay), 1)

    def test_local_search_updates_match_counter_and_navigation(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "Alpha beta gamma beta")
        panel.set_artifacts(
            [SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing", relpath="summary.txt")],
            preferred_kind="summary",
        )

        panel._search.setText("beta")
        panel._run_search()

        self.assertEqual(panel._matches.text(), "1/2")
        self.assertTrue(panel._prev_btn.isEnabled())
        self.assertTrue(panel._next_btn.isEnabled())

        panel._step_match(1)
        self.assertEqual(panel._matches.text(), "2/2")

    def test_global_search_results_toggle_visibility_and_clear(self) -> None:
        panel = MainTextPanelV2(lambda _relpath: "Summary text")
        panel.set_artifacts(
            [SimpleNamespace(kind="summary", alias="v1", stage_id="llm_processing", relpath="summary.txt")],
            preferred_kind="summary",
        )

        panel.set_global_search_results("roadmap", [{"meeting_id": "m1", "kind": "summary"}], answer="Answer")
        self.assertTrue(panel._global_results_visible)
        self.assertEqual(panel._global_results_query, "roadmap")
        self.assertGreaterEqual(panel._tabs.count(), 1)

        panel.clear_global_search_results()
        self.assertFalse(panel._global_results_visible)
        self.assertEqual(panel._global_results_query, "")


if __name__ == "__main__":
    unittest.main()
