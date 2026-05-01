from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QWidget,
)


def repolish(widget: QWidget) -> None:
    try:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
    except Exception:
        return


def is_dark_palette(widget: QWidget | None = None) -> bool:
    try:
        if widget is not None:
            return int(widget.palette().color(QPalette.Window).lightness()) < 128
    except Exception:
        pass
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return int(app.palette().color(QPalette.Window).lightness()) < 128
    except Exception:
        return False


def _tone_from_colors(bg: str, fg: str) -> str:
    bg_key = str(bg or "").strip().lower()
    fg_key = str(fg or "").strip().lower()
    joined = f"{bg_key} {fg_key}"
    if any(token in joined for token in ("fee2e2", "fecaca", "b91c1c", "ef4444", "dc2626")):
        return "danger"
    if any(token in joined for token in ("fef3c7", "ffedd5", "f59e0b", "92400e", "9a3412")):
        return "warning"
    if any(token in joined for token in ("dcfce7", "d1fae5", "22c55e", "16a34a", "166534", "14532d")):
        return "success"
    if any(token in joined for token in ("dbeafe", "eef2ff", "e0e7ff", "3b82f6", "2563eb", "1d4ed8", "1e3a8a")):
        return "focus"

    probe = QColor(fg_key if fg_key else bg_key)
    if not probe.isValid():
        return "neutral"
    hue = float(probe.hueF())
    sat = float(probe.saturationF())
    if sat < 0.14:
        return "neutral"
    if hue < 0.05 or hue > 0.94:
        return "danger"
    if 0.08 <= hue <= 0.17:
        return "warning"
    if 0.22 <= hue <= 0.45:
        return "success"
    if 0.50 <= hue <= 0.75:
        return "focus"
    return "neutral"


def normalize_badge_colors(bg: str, fg: str, *, dark: bool) -> tuple[str, str]:
    tone = _tone_from_colors(bg, fg)
    if dark:
        palette = {
            "neutral": ("#1F2937", "#CBD5E1"),
            "focus": ("#1E3A8A", "#BFDBFE"),
            "success": ("#14532D", "#BBF7D0"),
            "warning": ("#78350F", "#FDE68A"),
            "danger": ("#7F1D1D", "#FECACA"),
        }
        return palette.get(tone, palette["neutral"])
    palette = {
        "neutral": ("#EEF2F7", "#334155"),
        "focus": ("#DBEAFE", "#1E40AF"),
        "success": ("#DCFCE7", "#166534"),
        "warning": ("#FEF3C7", "#92400E"),
        "danger": ("#FEE2E2", "#991B1B"),
    }
    return palette.get(tone, palette["neutral"])


class StandardPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stdPanel")
        self.setFrameShape(QFrame.NoFrame)


class StandardCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stdCard")
        self.setFrameShape(QFrame.NoFrame)
        self.set_variant("default")

    def set_variant(self, variant: str) -> None:
        value = str(variant or "default").strip().lower() or "default"
        if value not in {"default", "focus", "related"}:
            value = "default"
        self.setProperty("variant", value)
        repolish(self)


class StandardBadge(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(str(text or ""), parent)
        self.setObjectName("stdBadge")
        self.set_kind("neutral")

    def set_kind(self, kind: str) -> None:
        value = str(kind or "neutral").strip().lower() or "neutral"
        if value not in {"neutral", "focus", "related", "success", "warning", "danger"}:
            value = "neutral"
        self.setProperty("kind", value)
        repolish(self)


class StandardStatusBadge(StandardBadge):
    _STATE_TO_KIND = {
        "idle": "neutral",
        "ready": "focus",
        "running": "focus",
        "completed": "success",
        "skipped": "warning",
        "failed": "danger",
        "disabled": "neutral",
        "processing": "focus",
        "cancelled": "warning",
        "raw": "neutral",
        "pending": "neutral",
        "queued": "neutral",
    }

    def set_state(self, state: str) -> None:
        value = str(state or "").strip().lower()
        self.setProperty("state", value)
        self.set_kind(self._STATE_TO_KIND.get(value, "neutral"))


class StandardSelectableChip(QPushButton):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(str(text or ""), parent)
        self.setObjectName("stdSelectableChip")
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setFocusPolicy(Qt.NoFocus)
        self._visual_signature: tuple[bool, bool, str] | None = None
        self._compact_max_chars: int | None = None

    def set_compact_mode(self, enabled: bool = True, *, max_chars: int = 30) -> None:
        self._compact_max_chars = max(1, int(max_chars)) if enabled else None
        self.setProperty("chipCompact", bool(enabled))
        repolish(self)
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        size = super().sizeHint()
        if not self._compact_max_chars:
            return size
        metrics = self.fontMetrics()
        cap_width = metrics.horizontalAdvance("M" * int(self._compact_max_chars))
        padded = cap_width + 18
        return QSize(min(size.width(), padded), size.height())

    def apply_state(
        self,
        *,
        selected: bool,
        active: bool,
        tone: str = "neutral",
        checked: bool | None = None,
    ) -> None:
        if checked is not None and bool(self.isChecked()) != bool(checked):
            self.blockSignals(True)
            self.setChecked(bool(checked))
            self.blockSignals(False)
        tone_value = str(tone or "neutral").strip().lower() or "neutral"
        if tone_value not in {"neutral", "focus", "success", "warning", "danger"}:
            tone_value = "neutral"
        signature = (bool(selected), bool(active), tone_value)
        if self._visual_signature == signature:
            return
        self._visual_signature = signature
        self.setProperty("chipSelected", bool(selected))
        self.setProperty("chipActive", bool(active))
        self.setProperty("chipTone", tone_value)
        repolish(self)


class StandardActionButton(QToolButton):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stdActionButton")
        self.setText(str(text or ""))
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setAutoRaise(False)


class StandardTextSourceView(QTextBrowser):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stdTextSourceView")
        self.setOpenExternalLinks(False)
