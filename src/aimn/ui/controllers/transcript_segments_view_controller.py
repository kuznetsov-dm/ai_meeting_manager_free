from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QAbstractItemView, QTextEdit, QWidget

from aimn.ui.controllers.document_view_factory_controller import DocumentViewFactoryController
from aimn.ui.controllers.transcript_evidence_controller import TranscriptSuggestionSpan
from aimn.ui.controllers.transcript_menu_controller import TranscriptMenuController
from aimn.ui.controllers.transcript_sync_controller import TranscriptSyncController
from aimn.ui.controllers.transcript_view_model_controller import TranscriptViewModelController


@dataclass(frozen=True)
class TranscriptSegmentsViewCallbacks:
    editor_factory: Callable[[], QWidget]
    format_ms: Callable[[int], str]
    highlight_transcript_range: Callable[[QWidget, int, int], None]
    seek_ms: Callable[[int], None]
    play: Callable[[], None]
    current_artifact_identity: Callable[[], tuple[str, str, str]]
    selection_evidence_payload: Callable[
        [QTextCursor, list[tuple[int, int] | None], list[dict]],
        dict[str, object],
    ]
    suggestion_span_at_position: Callable[
        [Sequence[TranscriptSuggestionSpan], int],
        TranscriptSuggestionSpan | None,
    ]
    label_text: Callable[[str, str], str]
    emit_create_requested: Callable[[str, dict[str, object]], None]
    emit_suggestion_action_requested: Callable[[str, dict[str, object]], None]
    set_editor_layer_selections: Callable[
        [QWidget, str, Sequence[QTextEdit.ExtraSelection] | None],
        None,
    ]
    management_overlay_selections: Callable[
        [QWidget, Sequence[TranscriptSuggestionSpan]],
        list[QTextEdit.ExtraSelection],
    ]
    find_segment_row_for_cursor: Callable[[int, list[tuple[int, int] | None]], int]
    find_segment_row_by_timestamp: Callable[[list[dict], float], int]
    build_segment_text_ranges: Callable[[str, list[dict]], list[tuple[int, int] | None]]


class TranscriptSegmentsViewController:
    @staticmethod
    def build_view(
        records: list[dict],
        *,
        transcript_text: str = "",
        suggestion_spans: Sequence[TranscriptSuggestionSpan] | None = None,
        callbacks: TranscriptSegmentsViewCallbacks,
    ) -> QWidget:
        widgets = DocumentViewFactoryController.build_transcript_view(
            editor_factory=callbacks.editor_factory,
        )
        root = widgets.root
        lst = widgets.list_widget
        editor = widgets.editor
        if not TranscriptSegmentsViewController._supports_transcript_editor(editor):
            return root

        plain_text = str(transcript_text or "")
        editor.setPlainText(plain_text)
        ranges = callbacks.build_segment_text_ranges(plain_text, records)
        spans = list(suggestion_spans or [])
        editor._aimn_management_suggestion_spans = spans
        callbacks.set_editor_layer_selections(
            editor,
            "overlay",
            callbacks.management_overlay_selections(editor, spans),
        )

        DocumentViewFactoryController.populate_transcript_list_widget(
            lst,
            TranscriptViewModelController.build_segment_items(
                records,
                ranges,
                format_ms=callbacks.format_ms,
            ),
        )

        sync_state = {"from_text_scroll": False, "from_segments_scroll": False}

        def apply_payload(payload: dict, *, play: bool = False, seek: bool = True) -> None:
            start_ms, text_range = TranscriptSyncController.payload_focus_data(payload)
            if text_range is not None:
                callbacks.highlight_transcript_range(editor, int(text_range[0]), int(text_range[1]))
            if seek:
                callbacks.seek_ms(start_ms)
            if play:
                callbacks.play()

        def activate_row(row: int, *, play: bool = False, seek: bool = True) -> None:
            bundle = TranscriptSyncController.row_activation_payload(
                list_widget=lst,
                row=int(row),
                current_row=lst.currentRow(),
            )
            if bundle is None:
                return
            target, needs_selection, payload = bundle
            item = lst.item(target)
            lst.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            if needs_selection:
                lst.setProperty("play_on_select", bool(play))
                lst.setProperty("seek_on_select", bool(seek))
                lst.setCurrentRow(target)
                return
            if isinstance(payload, dict):
                apply_payload(payload, play=play, seek=seek)

        def on_select() -> None:
            items = lst.selectedItems()
            if not items:
                return
            bundle = TranscriptSyncController.selection_apply_bundle(
                selected_payload=items[0].data(Qt.UserRole),
                play_on_select=lst.property("play_on_select"),
                seek_on_select=lst.property("seek_on_select"),
            )
            lst.setProperty("play_on_select", False)
            lst.setProperty("seek_on_select", True)
            if bundle is None:
                return
            payload, play, seek = bundle
            apply_payload(payload, play=play, seek=seek)

        def on_transcript_click(position: int) -> None:
            row = TranscriptSyncController.clicked_row(
                position=int(position),
                ranges=ranges,
                records=records,
                find_segment_row_for_cursor=callbacks.find_segment_row_for_cursor,
                find_segment_row_by_timestamp=callbacks.find_segment_row_by_timestamp,
                line_text=TranscriptSyncController.line_text_at_position(editor, int(position)),
            )
            if row >= 0:
                activate_row(row, play=False, seek=True)

        def on_transcript_double_click(position: int) -> None:
            row = TranscriptSyncController.clicked_row(
                position=int(position),
                ranges=ranges,
                records=records,
                find_segment_row_for_cursor=callbacks.find_segment_row_for_cursor,
                find_segment_row_by_timestamp=callbacks.find_segment_row_by_timestamp,
                line_text=TranscriptSyncController.line_text_at_position(editor, int(position)),
            )
            if row >= 0:
                activate_row(row, play=True, seek=True)

        def on_transcript_scroll(_value: int) -> None:
            if sync_state["from_segments_scroll"]:
                return
            row = TranscriptSyncController.text_scroll_target_row(
                editor=editor,
                ranges=ranges,
                current_row=lst.currentRow(),
                find_segment_row_for_cursor=callbacks.find_segment_row_for_cursor,
            )
            if row < 0:
                return
            sync_state["from_text_scroll"] = True
            try:
                activate_row(row, play=False, seek=False)
            finally:
                sync_state["from_text_scroll"] = False

        def on_segments_scroll(_value: int) -> None:
            if sync_state["from_text_scroll"]:
                return
            row = TranscriptSyncController.segments_scroll_target_row(
                list_widget=lst,
                current_row=lst.currentRow(),
            )
            if row < 0:
                return
            sync_state["from_segments_scroll"] = True
            try:
                activate_row(row, play=False, seek=False)
            finally:
                sync_state["from_segments_scroll"] = False

        def on_transcript_context_menu(pos: QPoint) -> None:
            cursor = editor.textCursor()
            selected_text = str(cursor.selectedText() or "").replace("\u2029", "\n").strip()
            clicked_cursor = editor.cursorForPosition(pos)
            clicked_position = int(clicked_cursor.position()) if isinstance(clicked_cursor, QTextCursor) else -1
            active_span = callbacks.suggestion_span_at_position(spans, clicked_position)
            menu = editor.createStandardContextMenu()
            stage_id, alias, kind = callbacks.current_artifact_identity()
            if selected_text:
                bundle = TranscriptMenuController.selection_menu_bundle(
                    stage_id=stage_id,
                    alias=alias,
                    kind=kind,
                    selected_text=selected_text,
                    evidence=callbacks.selection_evidence_payload(cursor, ranges, records),
                )
                if bundle is None:
                    menu.exec(editor.mapToGlobal(pos))
                    return
                menu.addSeparator()
                for spec in bundle.action_specs:
                    action = menu.addAction(callbacks.label_text(spec.label_key, spec.default_label))
                    action.triggered.connect(
                        lambda *_a, data=dict(bundle.payload), entity_type=spec.action_name: callbacks.emit_create_requested(
                            entity_type,
                            data,
                        )
                    )
            elif active_span is not None:
                bundle = TranscriptMenuController.suggestion_menu_bundle(
                    suggestion_id=active_span.suggestion_id,
                    suggestion_kind=active_span.kind,
                    selected_text=active_span.selected_text,
                    stage_id=stage_id,
                    alias=alias,
                    kind=kind,
                    evidence=dict(active_span.evidence),
                )
                if bundle is None:
                    menu.exec(editor.mapToGlobal(pos))
                    return
                menu.addSeparator()
                for index, spec in enumerate(bundle.action_specs):
                    if index in bundle.separator_indexes:
                        menu.addSeparator()
                    action = menu.addAction(callbacks.label_text(spec.label_key, spec.default_label))
                    action.triggered.connect(
                        lambda *_a, data=dict(bundle.payload), action_name=spec.action_name: callbacks.emit_suggestion_action_requested(
                            action_name,
                            data,
                        )
                    )
            menu.exec(editor.mapToGlobal(pos))

        lst.itemSelectionChanged.connect(on_select)
        lst.verticalScrollBar().valueChanged.connect(on_segments_scroll)
        editor.clickedAt.connect(on_transcript_click)
        if hasattr(editor, "doubleClickedAt"):
            editor.doubleClickedAt.connect(on_transcript_double_click)
        editor.verticalScrollBar().valueChanged.connect(on_transcript_scroll)
        editor.setContextMenuPolicy(Qt.CustomContextMenu)
        editor.customContextMenuRequested.connect(on_transcript_context_menu)
        if lst.count() > 0:
            activate_row(0, play=False, seek=False)
        return root

    @staticmethod
    def _supports_transcript_editor(editor: object) -> bool:
        return all(
            hasattr(editor, attr)
            for attr in (
                "setPlainText",
                "clickedAt",
                "verticalScrollBar",
                "setContextMenuPolicy",
                "customContextMenuRequested",
                "createStandardContextMenu",
                "cursorForPosition",
                "textCursor",
                "mapToGlobal",
            )
        )
