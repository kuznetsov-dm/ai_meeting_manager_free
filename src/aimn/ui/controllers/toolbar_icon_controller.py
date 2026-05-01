from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


@dataclass(frozen=True)
class ToolbarButtonIconSpec:
    button_name: str
    icon_kind: str
    tooltip_key: str
    tooltip_default: str


class ToolbarIconController:
    @staticmethod
    def command_button_specs() -> tuple[ToolbarButtonIconSpec, ...]:
        return (
            ToolbarButtonIconSpec("_find_btn", "search", "search.button", "Search"),
            ToolbarButtonIconSpec("_prev_btn", "prev", "search.prev", "Prev"),
            ToolbarButtonIconSpec("_next_btn", "next", "search.next", "Next"),
            ToolbarButtonIconSpec("_clear_btn", "clear", "search.clear", "Clear"),
            ToolbarButtonIconSpec("_logs_btn", "logs", "search.logs", "Logs"),
            ToolbarButtonIconSpec("_copy_btn", "copy", "search.copy", "Copy"),
            ToolbarButtonIconSpec("_copy_all_btn", "copy", "search.copy_all", "Copy All"),
            ToolbarButtonIconSpec("_copy_html_btn", "copy", "search.copy_html", "Copy HTML"),
            ToolbarButtonIconSpec("_btn_play", "play", "audio.play", "Play"),
            ToolbarButtonIconSpec("_btn_pause", "pause", "audio.pause", "Pause"),
            ToolbarButtonIconSpec("_btn_stop", "stop", "audio.stop", "Stop"),
        )

    @staticmethod
    def toolbar_icon_color(*, theme_id: str, palette_lightness: int) -> QColor:
        normalized = str(theme_id or "").strip().lower()
        if normalized.startswith("dark"):
            return QColor("#E5EDF8")
        if normalized.startswith("light"):
            return QColor("#334155")
        if int(palette_lightness) < 128:
            return QColor("#E5EDF8")
        return QColor("#334155")

    @staticmethod
    def export_target_glyph(label: str) -> str:
        return next((char for char in str(label or "").upper() if char.isalnum()), "E")

    @staticmethod
    def draw_toolbar_icon(
        kind: str,
        *,
        color: QColor,
        glyph: str = "",
        icon_size: int = 24,
    ) -> QIcon:
        pixmap = QPixmap(int(icon_size), int(icon_size))
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        pen = QPen(color)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        rect = QRectF(1.5, 1.5, float(icon_size) - 3.0, float(icon_size) - 3.0)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            kind_value = str(kind or "").strip().lower()
            if kind_value == "search":
                painter.drawEllipse(QRectF(4.0, 4.0, 10.0, 10.0))
                painter.drawLine(QPointF(12.8, 12.8), QPointF(19.5, 19.5))
            elif kind_value == "prev":
                path = QPainterPath()
                ToolbarIconController._draw_chevron(
                    path, (QPointF(15.0, 5.0), QPointF(9.0, 12.0), QPointF(15.0, 19.0))
                )
                painter.drawPath(path)
            elif kind_value == "next":
                path = QPainterPath()
                ToolbarIconController._draw_chevron(
                    path, (QPointF(9.0, 5.0), QPointF(15.0, 12.0), QPointF(9.0, 19.0))
                )
                painter.drawPath(path)
            elif kind_value == "clear":
                painter.drawLine(QPointF(6.0, 6.0), QPointF(18.0, 18.0))
                painter.drawLine(QPointF(18.0, 6.0), QPointF(6.0, 18.0))
            elif kind_value == "logs":
                painter.drawRoundedRect(QRectF(5.0, 4.0, 14.0, 16.0), 2.0, 2.0)
                painter.drawLine(QPointF(8.0, 9.0), QPointF(16.0, 9.0))
                painter.drawLine(QPointF(8.0, 12.5), QPointF(16.0, 12.5))
                painter.drawLine(QPointF(8.0, 16.0), QPointF(13.0, 16.0))
            elif kind_value == "copy":
                painter.drawRoundedRect(QRectF(7.0, 7.0, 10.0, 11.0), 2.0, 2.0)
                painter.drawRoundedRect(QRectF(10.0, 4.0, 10.0, 11.0), 2.0, 2.0)
            elif kind_value == "play":
                path = QPainterPath()
                path.moveTo(8.0, 5.0)
                path.lineTo(18.5, 12.0)
                path.lineTo(8.0, 19.0)
                path.closeSubpath()
                painter.setBrush(color)
                painter.drawPath(path)
            elif kind_value == "pause":
                painter.fillRect(QRectF(7.0, 5.0, 4.0, 14.0), color)
                painter.fillRect(QRectF(13.0, 5.0, 4.0, 14.0), color)
            elif kind_value == "stop":
                painter.fillRect(QRectF(6.0, 6.0, 12.0, 12.0), color)
            elif kind_value == "export":
                painter.drawRoundedRect(QRectF(5.0, 10.0, 14.0, 9.0), 2.0, 2.0)
                painter.drawLine(QPointF(12.0, 5.0), QPointF(12.0, 13.0))
                painter.drawLine(QPointF(12.0, 5.0), QPointF(8.8, 8.2))
                painter.drawLine(QPointF(12.0, 5.0), QPointF(15.2, 8.2))
            elif kind_value == "target":
                painter.drawRoundedRect(rect.adjusted(2.0, 2.0, -2.0, -2.0), 4.0, 4.0)
                font = painter.font()
                font.setBold(True)
                font.setPointSize(10)
                painter.setFont(font)
                painter.drawText(rect, Qt.AlignCenter, (glyph[:1] or "E").upper())
            else:
                painter.drawRoundedRect(rect.adjusted(2.0, 2.0, -2.0, -2.0), 3.0, 3.0)
        finally:
            painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _draw_chevron(path: QPainterPath, points: tuple[QPointF, QPointF, QPointF]) -> None:
        start, mid, end = points
        path.moveTo(start)
        path.lineTo(mid)
        path.lineTo(end)
