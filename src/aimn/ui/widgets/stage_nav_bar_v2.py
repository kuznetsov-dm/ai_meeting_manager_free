from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from aimn.ui.widgets.tiles import measure_compact_tile_size

STAGE_NAV_ORDER: list[str] = [
    "input",
    "media_convert",
    "transcription",
    "llm_processing",
    "management",
    "service",
    "other",
]


def _stage_label(stage_id: str, label_provider: Callable[[str], str] | None = None) -> str:
    if callable(label_provider):
        value = str(label_provider(stage_id) or "").strip()
        if value:
            return value
    names = {
        "input": "Input",
        "media_convert": "Convert",
        "transcription": "Transcription",
        "text_processing": "Semantic Processing",
        "llm_processing": "AI Processing",
        "management": "Management",
        "service": "Service",
        "other": "Other",
    }
    return names.get(stage_id, stage_id)


class StageNavTileV2(QFrame):
    clicked = Signal(str)

    def __init__(
        self,
        stage_id: str,
        subtitle: str = "",
        parent: QWidget | None = None,
        *,
        label_provider: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.stage_id = stage_id
        self._label_provider = label_provider
        self._pressed = False
        self._selected = False

        # Reuse the pipeline tile styling for consistency.
        self.setObjectName("pipelineTileV2")
        self.setFrameShape(QFrame.Box)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setProperty("selected", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self._name = QLabel(_stage_label(stage_id, self._label_provider))
        self._name.setObjectName("pipelineTileName")
        self._name.setWordWrap(False)
        layout.addWidget(self._name)

        self._subtitle = QLabel(str(subtitle or ""))
        self._subtitle.setObjectName("pipelineTileStatus")
        self._subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._subtitle.setVisible(bool(str(subtitle or "").strip()))
        layout.addWidget(self._subtitle)

        self._update_compact_size()
        self._apply_selected(False)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(str(subtitle or ""))
        self._subtitle.setVisible(bool(str(subtitle or "").strip()))
        self._update_compact_size()

    def set_label_provider(self, label_provider: Callable[[str], str] | None) -> None:
        self._label_provider = label_provider
        self._name.setText(_stage_label(self.stage_id, self._label_provider))
        self._update_compact_size()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_selected(self._selected)

    def _apply_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        try:
            style = self.style()
            style.unpolish(self)
            style.polish(self)
            self.update()
        except Exception:
            return

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            was_pressed = self._pressed
            self._pressed = False
            if was_pressed and self.rect().contains(event.pos()):
                self.clicked.emit(self.stage_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            # Keep stage interaction single-click driven and prevent double-click propagation.
            self._pressed = False
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _update_compact_size(self) -> None:
        size = measure_compact_tile_size(
            self.font(),
            title=self._name.text(),
            subtitle=self._subtitle.text(),
            min_width=108,
            min_height=52,
            width_scale=1.1,
        )
        self.setFixedSize(size)


class StageNavBarV2(QWidget):
    stageSelected = Signal(str)

    def __init__(
        self,
        stages: Iterable[str] | None = None,
        *,
        subtitle: str = "",
        label_provider: Callable[[str], str] | None = None,
        allow_clear_selection: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tiles: dict[str, StageNavTileV2] = {}
        self._selected: str = ""
        self._subtitle = str(subtitle or "")
        self._label_provider = label_provider
        self._allow_clear_selection = bool(allow_clear_selection)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        for sid in list(stages) if stages is not None else list(STAGE_NAV_ORDER):
            tile = StageNavTileV2(sid, subtitle=self._subtitle, label_provider=self._label_provider)
            tile.clicked.connect(self._on_clicked)
            self._tiles[sid] = tile
            layout.addWidget(tile, 0, Qt.AlignLeft)

        layout.addStretch(1)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = str(subtitle or "")
        for tile in self._tiles.values():
            tile.set_subtitle(self._subtitle)

    def set_label_provider(self, label_provider: Callable[[str], str] | None) -> None:
        self._label_provider = label_provider
        for tile in self._tiles.values():
            tile.set_label_provider(self._label_provider)

    def set_selected(self, stage_id: str) -> None:
        sid = str(stage_id or "")
        self._selected = sid
        for tid, tile in self._tiles.items():
            tile.set_selected(tid == sid)

    def _on_clicked(self, stage_id: str) -> None:
        sid = str(stage_id or "")
        if not sid:
            return
        if self._allow_clear_selection and sid == self._selected:
            self.set_selected("")
            self.stageSelected.emit("")
            return
        self.set_selected(sid)
        self.stageSelected.emit(sid)
