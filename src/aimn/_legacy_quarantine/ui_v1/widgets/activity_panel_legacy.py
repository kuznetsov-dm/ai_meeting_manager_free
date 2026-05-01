from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class ActivityPanel(QWidget):
    """
    Bottom panel that groups operational UI (Logs/Jobs) without creating extra docks.

    Density contract (UI.txt):
    - collapsed: title-only (dock chrome stays, content hidden)
    - mini/full: content visible; the dock height is controlled by the workspace layout service
    """

    def __init__(self, logs_widget: QWidget, jobs_widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._density = "mini"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._title = QLabel("Activity")
        self._title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header.addWidget(self._title, 1)

        self._buttons = QButtonGroup(self)
        self._buttons.setExclusive(True)
        self._btn_logs = QToolButton()
        self._btn_logs.setText("Logs")
        self._btn_logs.setCheckable(True)
        self._btn_jobs = QToolButton()
        self._btn_jobs.setText("Jobs")
        self._btn_jobs.setCheckable(True)
        self._buttons.addButton(self._btn_logs)
        self._buttons.addButton(self._btn_jobs)
        self._btn_logs.setChecked(True)
        header.addWidget(self._btn_logs)
        header.addWidget(self._btn_jobs)
        layout.addLayout(header)

        self._stack = QStackedWidget()
        self._stack.addWidget(logs_widget)
        self._stack.addWidget(jobs_widget)
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._stack, 1)

        self._btn_logs.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._btn_jobs.clicked.connect(lambda: self._stack.setCurrentIndex(1))

        self.set_density("mini")

    def set_density(self, density: str) -> None:
        self._density = density
        collapsed = density == "collapsed"
        self._stack.setVisible(not collapsed)
        self._btn_logs.setVisible(not collapsed)
        self._btn_jobs.setVisible(not collapsed)
        self.setProperty("density", density)
        self.style().unpolish(self)
        self.style().polish(self)

    def get_density(self) -> str:
        return str(self.property("density") or self._density)

