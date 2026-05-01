from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aimn.ui.widgets.standard_components import StandardStatusBadge


def measure_compact_tile_size(
    font: QFont,
    *,
    title: str,
    subtitle: str = "",
    has_checkbox: bool = False,
    min_width: int = 0,
    min_height: int = 0,
    h_padding: int = 10,
    v_padding: int = 8,
    row_spacing: int = 4,
    checkbox_width: int = 18,
    checkbox_gap: int = 8,
    frame_allowance: int = 8,
    width_scale: float = 1.0,
) -> QSize:
    title_font = QFont(font)
    title_font.setBold(True)
    title_metrics = QFontMetrics(title_font)
    subtitle_metrics = QFontMetrics(font)

    title_text = str(title or "").strip() or " "
    subtitle_text = str(subtitle or "").strip()
    title_width = title_metrics.horizontalAdvance(title_text)
    title_height = title_metrics.height()

    top_row_width = title_width
    top_row_height = title_height
    if has_checkbox:
        top_row_width += checkbox_gap + checkbox_width
        top_row_height = max(top_row_height, checkbox_width)

    content_width = top_row_width
    total_height = top_row_height
    if subtitle_text:
        content_width = max(content_width, subtitle_metrics.horizontalAdvance(subtitle_text))
        total_height += row_spacing + subtitle_metrics.height()

    raw_width = int((2 * h_padding) + content_width + frame_allowance)
    width = max(int(min_width), int(raw_width * max(1.0, float(width_scale))))
    height = max(int(min_height), int((2 * v_padding) + total_height + 4))
    return QSize(width, height)


def _badge_kind_from_colors(bg: str, fg: str) -> str:
    joined = f"{str(bg or '').lower()} {str(fg or '').lower()}"
    if any(token in joined for token in ("fee2e2", "fecaca", "b91c1c", "ef4444", "dc2626")):
        return "danger"
    if any(token in joined for token in ("fef3c7", "ffedd5", "f59e0b", "92400e", "9a3412")):
        return "warning"
    if any(token in joined for token in ("dcfce7", "d1fae5", "22c55e", "16a34a", "166534", "14532d")):
        return "success"
    if any(token in joined for token in ("dbeafe", "eef2ff", "e0e7ff", "3b82f6", "2563eb", "1d4ed8", "1e3a8a")):
        return "focus"
    return "neutral"


@dataclass(frozen=True)
class TileModel:
    tile_id: str
    title: str
    subtitle: str = ""
    tooltip: str = ""
    selected: bool = False
    disabled: bool = False
    checked: bool | None = None  # None means no checkbox


@dataclass(frozen=True)
class ListTileModel:
    tile_id: str
    title: str
    subtitle: str = ""
    meta_lines: list[str] = field(default_factory=list)
    status_label: str = ""
    status_bg: str = "rgba(148, 163, 184, 28)"
    status_fg: str = "#374151"
    tooltip: str = ""
    selected: bool = False
    disabled: bool = False
    checked: bool | None = None  # None means no checkbox


class SelectableTile(QFrame):
    clicked = Signal(str)
    toggled = Signal(str, bool)

    def __init__(self, model: TileModel, *, size: QSize | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tile_id = model.tile_id
        self._pressed = False
        self._selected = False
        self._fixed_size_override = QSize(size) if isinstance(size, QSize) else None

        self.setObjectName("pipelineTileV2")
        self.setFrameShape(QFrame.Box)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setProperty("selected", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        self._title = QLabel("")
        self._title.setObjectName("pipelineTileName")
        self._title.setWordWrap(False)
        top.addWidget(self._title, 1)

        self._checkbox: QCheckBox | None = None
        if model.checked is not None:
            self._checkbox = QCheckBox()
            self._checkbox.setChecked(bool(model.checked))
            self._checkbox.stateChanged.connect(self._on_checkbox_changed)
            top.addWidget(self._checkbox, 0, Qt.AlignRight)

        layout.addLayout(top)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("pipelineTileStatus")
        self._subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self._subtitle)

        self.apply(model)

    def apply(self, model: TileModel) -> None:
        self.tile_id = model.tile_id
        self._title.setText(str(model.title or ""))
        subtitle_text = str(model.subtitle or "")
        self._subtitle.setText(subtitle_text)
        self._subtitle.setVisible(bool(subtitle_text.strip()))
        if model.tooltip:
            self.setToolTip(str(model.tooltip))
        if self._checkbox is not None and model.checked is not None:
            self._checkbox.blockSignals(True)
            self._checkbox.setChecked(bool(model.checked))
            self._checkbox.blockSignals(False)
        self.setEnabled(not bool(model.disabled))
        self._update_compact_size(model)
        self.set_selected(bool(model.selected))

    def _update_compact_size(self, model: TileModel) -> None:
        if self._fixed_size_override is not None:
            self.setFixedSize(self._fixed_size_override)
            return
        size = measure_compact_tile_size(
            self.font(),
            title=str(model.title or ""),
            subtitle=str(model.subtitle or ""),
            has_checkbox=self._checkbox is not None,
            min_width=100,
            min_height=40,
            width_scale=1.1,
        )
        self.setFixedSize(size)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        try:
            style = self.style()
            style.unpolish(self)
            style.polish(self)
            self.update()
        except Exception:
            return

    def _on_checkbox_changed(self, _state: int) -> None:
        if not self._checkbox:
            return
        self.toggled.emit(self.tile_id, bool(self._checkbox.isChecked()))

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
                self.clicked.emit(self.tile_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            # Keep tile interaction single-click driven and prevent double-click propagation.
            self._pressed = False
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class SelectableListTile(QFrame):
    clicked = Signal(str)
    doubleClicked = Signal(str)
    toggled = Signal(str, bool)

    def __init__(self, model: ListTileModel, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tile_id = model.tile_id
        self._pressed = False
        self._selected = False

        self.setObjectName("listTileCard")
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(110)
        self.setProperty("selected", False)
        self.setProperty("pressed", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        self._title = QLabel("")
        self._title.setObjectName("listTileTitle")
        self._title.setWordWrap(False)
        top.addWidget(self._title, 1)

        self._checkbox: QCheckBox | None = None
        if model.checked is not None:
            self._checkbox = QCheckBox()
            self._checkbox.setChecked(bool(model.checked))
            self._checkbox.stateChanged.connect(self._on_checkbox_changed)
            top.addWidget(self._checkbox, 0, Qt.AlignRight)

        layout.addLayout(top)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("listTileSubtitle")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._status = StandardStatusBadge("")
        layout.addWidget(self._status, 0, Qt.AlignLeft)

        self._meta_box = QWidget()
        self._meta_layout = QVBoxLayout(self._meta_box)
        self._meta_layout.setContentsMargins(0, 0, 0, 0)
        self._meta_layout.setSpacing(2)
        layout.addWidget(self._meta_box)

        self.apply(model)

    def apply(self, model: ListTileModel) -> None:
        self.tile_id = model.tile_id
        self._title.setText(str(model.title or ""))
        self._subtitle.setText(str(model.subtitle or ""))
        if model.tooltip:
            self.setToolTip(str(model.tooltip))
        if self._checkbox is not None and model.checked is not None:
            self._checkbox.blockSignals(True)
            self._checkbox.setChecked(bool(model.checked))
            self._checkbox.blockSignals(False)
        self.setEnabled(not bool(model.disabled))
        self._set_status_badge(model.status_label, model.status_bg, model.status_fg)
        self._set_meta_lines(model.meta_lines)
        self.set_selected(bool(model.selected))

    def _set_status_badge(self, label: str, bg: str, fg: str) -> None:
        text = str(label or "")
        if not text:
            self._status.setVisible(False)
            return
        self._status.setVisible(True)
        self._status.setText(text)
        self._status.set_kind(_badge_kind_from_colors(bg, fg))

    def _set_meta_lines(self, lines: list[str]) -> None:
        for i in reversed(range(self._meta_layout.count())):
            item = self._meta_layout.takeAt(i)
            if item and item.widget():
                item.widget().setParent(None)
        for idx, line in enumerate(lines or []):
            label = QLabel(str(line or ""))
            label.setObjectName("listTileMetaPrimary" if idx == 0 else "listTileMeta")
            label.setWordWrap(True)
            self._meta_layout.addWidget(label)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        self._repolish()

    def _on_checkbox_changed(self, _state: int) -> None:
        if not self._checkbox:
            return
        self.toggled.emit(self.tile_id, bool(self._checkbox.isChecked()))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.setProperty("pressed", True)
            self._repolish()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            was_pressed = self._pressed
            self._pressed = False
            self.setProperty("pressed", False)
            self._repolish()
            if was_pressed and self.rect().contains(event.pos()):
                self.clicked.emit(self.tile_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            # Keep tile interaction explicit and expose double-click as a dedicated action.
            self._pressed = False
            self.setProperty("pressed", False)
            self._repolish()
            self.doubleClicked.emit(self.tile_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _repolish(self) -> None:
        # Allow theme.py to style via dynamic properties (selected/pressed/hover).
        try:
            self.style().unpolish(self)
            self.style().polish(self)
        except Exception:
            pass
        self.update()
