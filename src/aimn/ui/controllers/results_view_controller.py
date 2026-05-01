from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QListWidgetItem, QWidget

from aimn.ui.controllers.document_view_factory_controller import DocumentViewFactoryController
from aimn.ui.controllers.results_interaction_controller import ResultsInteractionController
from aimn.ui.controllers.results_view_model_controller import ResultsViewModelController


@dataclass(frozen=True)
class ResultsViewCallbacks:
    editor_factory: Callable[[], QWidget]
    apply_editor_term_highlights: Callable[[QWidget, Sequence[str]], None]
    highlight_range: Callable[[QWidget, int, int, Sequence[str] | None], None]
    emit_open: Callable[[tuple[str, str, str, str, int, int]], None]


class ResultsViewController:
    @staticmethod
    def build_view(
        *,
        query: str,
        rows: list[dict],
        answer_text: str,
        callbacks: ResultsViewCallbacks,
    ) -> QWidget:
        widgets = DocumentViewFactoryController.build_results_view(
            answer_text=str(answer_text or "").strip(),
            has_rows=bool(rows),
            editor_factory=callbacks.editor_factory,
        )
        root = widgets.root
        lst = widgets.list_widget
        editor = widgets.editor

        view_model = ResultsViewModelController.build(
            query=query,
            rows=list(rows or []),
        )
        if lst is None or not ResultsViewController._supports_results_editor(editor):
            return root
        active_blocks: list[tuple[int, int, dict, int]] = list(view_model.get("active_blocks", []) or [])
        DocumentViewFactoryController.populate_results_list_widget(
            lst,
            list(view_model.get("items", []) or []),
        )

        editor.setPlainText(str(view_model.get("text", "") or ""))
        highlight_terms = list(view_model.get("highlight_terms", []) or [])
        callbacks.apply_editor_term_highlights(editor, highlight_terms)

        def activate_item(item: QListWidgetItem, *, set_row: bool = True) -> None:
            bundle = ResultsInteractionController.item_activation_bundle(
                item_payload=item.data(Qt.UserRole),
                row=int(lst.row(item)),
                current_row=int(lst.currentRow()),
            )
            if bundle is None:
                return
            _active_payload, left, right, row, needs_selection = bundle
            callbacks.highlight_range(editor, int(left), int(right), highlight_terms)
            if set_row and needs_selection and row >= 0:
                lst.setCurrentRow(row)

        sync_state = {"from_text_scroll": False, "from_list_scroll": False}

        def on_select() -> None:
            items = lst.selectedItems()
            if not items:
                return
            activate_item(items[0], set_row=False)

        def on_item_activated(item: QListWidgetItem) -> None:
            bundle = ResultsInteractionController.item_open_bundle(
                item_payload=item.data(Qt.UserRole),
                row=int(lst.row(item)),
                current_row=int(lst.currentRow()),
            )
            if bundle is None:
                return
            _active_payload, left, right, _row, _needs_selection, open_args = bundle
            callbacks.highlight_range(editor, int(left), int(right), highlight_terms)
            if open_args:
                callbacks.emit_open(open_args)

        def on_text_click(position: int) -> None:
            bundle = ResultsInteractionController.text_click_bundle(
                active_blocks=active_blocks,
                position=int(position),
                current_row=int(lst.currentRow()),
            )
            if bundle is None:
                return
            _current_payload, left, right, row, needs_selection = bundle
            callbacks.highlight_range(editor, int(left), int(right), highlight_terms)
            if needs_selection and int(row) >= 0:
                lst.setCurrentRow(int(row))

        def on_text_double_click(position: int) -> None:
            bundle = ResultsInteractionController.text_open_bundle(
                active_blocks=active_blocks,
                position=int(position),
                current_row=int(lst.currentRow()),
            )
            if bundle is None:
                return
            _active_payload, left, right, row, needs_selection, open_args = bundle
            callbacks.highlight_range(editor, int(left), int(right), highlight_terms)
            if needs_selection and int(row) >= 0:
                lst.setCurrentRow(int(row))
            if open_args:
                callbacks.emit_open(open_args)

        def on_text_scroll(_value: int) -> None:
            if sync_state["from_list_scroll"]:
                return
            row = ResultsInteractionController.text_scroll_target_row(
                editor=editor,
                active_blocks=active_blocks,
                current_row=int(lst.currentRow()),
            )
            if row < 0:
                return
            sync_state["from_text_scroll"] = True
            try:
                lst.setCurrentRow(int(row))
                item = lst.item(int(row))
                if item is not None:
                    lst.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            finally:
                sync_state["from_text_scroll"] = False

        def on_list_scroll(_value: int) -> None:
            if sync_state["from_text_scroll"]:
                return
            bundle = ResultsInteractionController.list_scroll_target_bundle(
                list_widget=lst,
                current_row=int(lst.currentRow()),
            )
            if bundle is None:
                return
            row, left, right, should_select = bundle
            sync_state["from_list_scroll"] = True
            try:
                if should_select:
                    lst.setCurrentRow(row)
                callbacks.highlight_range(editor, int(left), int(right), highlight_terms)
            finally:
                sync_state["from_list_scroll"] = False

        lst.itemSelectionChanged.connect(on_select)
        lst.itemDoubleClicked.connect(on_item_activated)
        lst.itemActivated.connect(on_item_activated)
        editor.clickedAt.connect(on_text_click)
        editor.doubleClickedAt.connect(on_text_double_click)
        editor.verticalScrollBar().valueChanged.connect(on_text_scroll)
        lst.verticalScrollBar().valueChanged.connect(on_list_scroll)

        if lst.count() > 0:
            lst.setCurrentRow(0)
        return root

    @staticmethod
    def _supports_results_editor(editor: object) -> bool:
        return all(
            hasattr(editor, attr)
            for attr in (
                "setPlainText",
                "clickedAt",
                "doubleClickedAt",
                "verticalScrollBar",
            )
        )
