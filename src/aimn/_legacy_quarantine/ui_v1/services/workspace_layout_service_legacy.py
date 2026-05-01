from __future__ import annotations

import base64
import logging
from typing import Dict, Iterable

from PySide6.QtCore import QObject, QTimer, QEvent, Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow


class WorkspaceLayoutService(QObject):
    def __init__(
        self,
        main_window: QMainWindow,
        settings_store,
        pipeline_chain,
        dock_panels: Dict[str, QDockWidget],
        *,
        autosave_ms: int = 500,
    ) -> None:
        super().__init__(main_window)
        self._main_window = main_window
        self._settings_store = settings_store
        self._pipeline_chain = pipeline_chain
        self._dock_panels = dock_panels
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(200, autosave_ms))
        self._timer.timeout.connect(self.save_current_layout)

    def restore_on_startup(self) -> None:
        raw = self._settings_store.get("ui.workspace.v1")
        if not isinstance(raw, dict):
            self.apply_preset("default_balanced")
            return
        if int(raw.get("version", 0) or 0) < 2:
            # Dock set changed; keep startup stable by resetting to a known-good layout.
            self.apply_preset("default_balanced")
            return
        try:
            self.apply_layout(raw)
        except Exception as exc:
            logging.getLogger("aimn.ui").warning("workspace_restore_failed error=%s", exc)
            self.apply_preset("default_balanced")

    def connect_autosave_signals(self) -> None:
        for dock in self._dock_panels.values():
            dock.topLevelChanged.connect(self._schedule_save)
            dock.visibilityChanged.connect(self._schedule_save)
            dock.dockLocationChanged.connect(self._schedule_save)
        self._pipeline_chain.presentation_changed.connect(self._schedule_save)
        self._main_window.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._main_window:
            if event.type() in {QEvent.Resize, QEvent.Move}:
                self._schedule_save()
        return super().eventFilter(obj, event)

    def capture_layout(self) -> dict:
        geometry = base64.b64encode(self._main_window.saveGeometry()).decode("ascii")
        state = base64.b64encode(self._main_window.saveState()).decode("ascii")
        panels = {}
        for panel_id, dock in self._dock_panels.items():
            widget = dock.widget()
            density = getattr(widget, "get_density", lambda: "full")()
            panels[panel_id] = {
                "visible": dock.isVisible(),
                "size_state": density,
            }
        stage_states = self._pipeline_chain.capture_presentation()
        orientation = "horizontal"
        getter = getattr(self._pipeline_chain, "orientation", None)
        if callable(getter):
            orientation = getter() or "horizontal"
        return {
            "version": 2,
            "window": {"geometry_b64": geometry},
            "docks": {"state_b64": state, "panels": panels},
            "pipeline_chain": {"orientation": orientation, "stages": stage_states},
        }

    def apply_layout(self, layout: dict) -> None:
        window = layout.get("window", {})
        geometry_b64 = window.get("geometry_b64", "")
        if isinstance(geometry_b64, str) and geometry_b64:
            self._main_window.restoreGeometry(base64.b64decode(geometry_b64))
        docks = layout.get("docks", {})
        state_b64 = docks.get("state_b64", "")
        if isinstance(state_b64, str) and state_b64:
            self._main_window.restoreState(base64.b64decode(state_b64))
        panels = docks.get("panels", {})
        if isinstance(panels, dict):
            for panel_id, state in panels.items():
                dock = self._dock_panels.get(panel_id)
                if not dock or not isinstance(state, dict):
                    continue
                visible = bool(state.get("visible", True))
                dock.setVisible(visible)
                density = str(state.get("size_state", "full"))
                widget = dock.widget()
                setter = getattr(widget, "set_density", None)
                if callable(setter):
                    setter(density)
        chain = layout.get("pipeline_chain", {})
        orientation = chain.get("orientation")
        setter = getattr(self._pipeline_chain, "set_orientation", None)
        if isinstance(orientation, str) and callable(setter):
            setter(orientation)
        stages = chain.get("stages", {})
        if isinstance(stages, dict):
            self._pipeline_chain.apply_presentation(stages)

    def save_current_layout(self) -> None:
        try:
            layout = self.capture_layout()
            self._settings_store.set("ui.workspace.v1", layout)
        except Exception as exc:
            logging.getLogger("aimn.ui").warning("workspace_save_failed error=%s", exc)

    def apply_preset(self, preset_id: str) -> None:
        presets = {
            "default_balanced": {
                "artifacts": "mini",
                "activity": "mini",
            },
            "editing_review": {
                "artifacts": "full",
                "activity": "collapsed",
            },
            "debug_ops": {
                "artifacts": "mini",
                "activity": "full",
            },
        }
        panel_states = presets.get(preset_id, presets["default_balanced"])
        for panel_id, density in panel_states.items():
            dock = self._dock_panels.get(panel_id)
            if not dock:
                continue
            dock.setVisible(True)
            widget = dock.widget()
            setter = getattr(widget, "set_density", None)
            if callable(setter):
                setter(density)
        # Recommended default dock sizes for 1200x700 (UI.txt).
        artifacts = self._dock_panels.get("artifacts")
        if artifacts:
            self._main_window.resizeDocks([artifacts], [440], Qt.Horizontal)
        activity = self._dock_panels.get("activity")
        if activity:
            target_height = 220 if panel_states.get("activity") != "full" else 320
            self._main_window.resizeDocks([activity], [target_height], Qt.Vertical)
        self._pipeline_chain.reset_presentation()
        self.save_current_layout()

    def reset_layout_to_default(self) -> None:
        self.apply_preset("default_balanced")

    def show_all_panels(self) -> None:
        for dock in self._dock_panels.values():
            dock.setVisible(True)
        self.save_current_layout()

    def show_all_stages(self) -> None:
        self._pipeline_chain.show_all_stages()
        self.save_current_layout()

    def reset_stage_presentation(self) -> None:
        self._pipeline_chain.reset_presentation()
        self.save_current_layout()

    def set_panel_density(self, panel_id: str, density: str) -> None:
        dock = self._dock_panels.get(panel_id)
        if not dock:
            return
        widget = dock.widget()
        setter = getattr(widget, "set_density", None)
        if callable(setter):
            setter(density)
        self._schedule_save()

    def set_stage_presentation(self, stage_id: str, visible: bool, density: str) -> None:
        self._pipeline_chain.set_stage_presentation(stage_id, visible, density)
        self._schedule_save()

    def _schedule_save(self) -> None:
        self._timer.start()
