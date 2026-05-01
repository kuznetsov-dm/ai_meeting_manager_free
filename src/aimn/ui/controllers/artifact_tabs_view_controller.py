from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtWidgets import QTabWidget, QWidget

from aimn.ui.controllers.artifact_tabs_controller import ArtifactTabsController


class ArtifactTabsViewController:
    @staticmethod
    def rebuild_tabs(
        tab_widget: QTabWidget,
        *,
        versions: Sequence[object],
        global_results_visible: bool,
        results_title: str,
        text_title: str,
        pinned_aliases: Mapping[str, str] | None,
        active_aliases: Mapping[str, str] | None,
        previous_title: str,
        prefer_results: bool,
        make_results_view: Callable[[], QWidget],
        make_text_view: Callable[[], QWidget],
        make_artifact_view: Callable[[object], QWidget],
        set_tab_tooltip: Callable[[int, str], None] | None = None,
    ) -> int:
        specs = ArtifactTabsController.build_specs(
            versions,
            global_results_visible=global_results_visible,
            results_title=results_title,
            text_title=text_title,
            pinned_aliases=pinned_aliases,
        )
        tab_widget.clear()
        version_list = list(versions or [])
        for spec in specs:
            if spec.kind == "results":
                tab_widget.addTab(make_results_view(), spec.title)
                continue
            if spec.kind == "text":
                tab_widget.addTab(make_text_view(), spec.title)
                continue
            version_index = int(spec.version_index) if spec.version_index is not None else -1
            if version_index < 0 or version_index >= len(version_list):
                continue
            tab_widget.addTab(make_artifact_view(version_list[version_index]), spec.title)
            if spec.tooltip and callable(set_tab_tooltip):
                set_tab_tooltip(tab_widget.count() - 1, spec.tooltip)
        target = ArtifactTabsController.selected_index(
            specs,
            version_list,
            global_results_visible=global_results_visible,
            results_title=results_title,
            prev_title=previous_title,
            prefer_results=prefer_results,
            active_aliases=active_aliases,
        )
        if 0 <= int(target) < tab_widget.count():
            tab_widget.setCurrentIndex(int(target))
        return int(target)
