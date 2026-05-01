from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QIcon, QPixmap


def pixmap(name: str, *, size: int | None = None) -> QPixmap:
    try:
        data = resources.files(__package__).joinpath(name).read_bytes()
    except Exception:
        return QPixmap()
    pix = QPixmap()
    if not pix.loadFromData(data):
        return QPixmap()
    if size:
        return pix.scaled(size, size)
    return pix


def icon(name: str = "app_icon.png") -> QIcon:
    pix = pixmap(name)
    return QIcon(pix) if not pix.isNull() else QIcon()
