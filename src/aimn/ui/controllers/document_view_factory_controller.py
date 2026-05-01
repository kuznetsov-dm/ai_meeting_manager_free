from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class ResultsViewWidgets:
    root: QWidget
    list_widget: QListWidget | None
    editor: QWidget


@dataclass(frozen=True)
class TranscriptViewWidgets:
    root: QWidget
    list_widget: QListWidget
    editor: QWidget


class DocumentViewFactoryController:
    @staticmethod
    def build_results_view(
        *,
        answer_text: str,
        has_rows: bool,
        editor_factory: Callable[[], QWidget],
        empty_text: str = "No matches.",
        list_width: int = 380,
    ) -> ResultsViewWidgets:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if str(answer_text or "").strip():
            answer = QLabel(str(answer_text or "").strip())
            answer.setObjectName("pipelineMetaLabel")
            answer.setWordWrap(True)
            layout.addWidget(answer, 0)

        if not bool(has_rows):
            empty = QPlainTextEdit()
            empty.setReadOnly(True)
            empty.setPlainText(str(empty_text or ""))
            layout.addWidget(empty, 1)
            return ResultsViewWidgets(root=root, list_widget=None, editor=empty)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        lst = QListWidget()
        lst.setObjectName("globalSearchSegmentsList")
        lst.setSelectionMode(QAbstractItemView.SingleSelection)
        lst.setFixedWidth(int(list_width))
        body_layout.addWidget(lst, 0)

        editor = editor_factory()
        body_layout.addWidget(editor, 1)
        layout.addWidget(body, 1)
        return ResultsViewWidgets(root=root, list_widget=lst, editor=editor)

    @staticmethod
    def populate_results_list_widget(list_widget: QListWidget, item_models: Sequence[object]) -> None:
        for item_model in list(item_models or []):
            item = QListWidgetItem(str(getattr(item_model, "item_text", "") or ""))
            item.setToolTip(str(getattr(item_model, "tooltip", "") or ""))
            item.setData(
                Qt.UserRole,
                {
                    "payload": dict(getattr(item_model, "payload", {}) or {}),
                    "left": int(getattr(item_model, "left", -1)),
                    "right": int(getattr(item_model, "right", -1)),
                },
            )
            item.setSizeHint(QSize(360, max(56, int(item.sizeHint().height()))))
            list_widget.addItem(item)

    @staticmethod
    def build_transcript_view(
        *,
        editor_factory: Callable[[], QWidget],
        list_width: int = 320,
    ) -> TranscriptViewWidgets:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lst = QListWidget()
        lst.setObjectName("transcriptSegmentsList")
        lst.setSelectionMode(QAbstractItemView.SingleSelection)
        lst.setFixedWidth(int(list_width))
        layout.addWidget(lst, 0)

        editor = editor_factory()
        layout.addWidget(editor, 1)
        return TranscriptViewWidgets(root=root, list_widget=lst, editor=editor)

    @staticmethod
    def populate_transcript_list_widget(list_widget: QListWidget, item_models: Sequence[object]) -> None:
        for item_model in list(item_models or []):
            item = QListWidgetItem(str(getattr(item_model, "label", "") or ""))
            item.setData(Qt.UserRole, dict(getattr(item_model, "payload", {}) or {}))
            list_widget.addItem(item)
