from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from aimn.ui.controllers.artifact_kind_bar_controller import ArtifactKindBarController


class ArtifactKindBarViewController:
    @staticmethod
    def rebuild_rows(
        *,
        kinds: Sequence[str],
        current_active_kind: str,
        kind_titles: Mapping[str, str] | None,
        artifacts_by_kind: Mapping[str, Sequence[object]] | None,
        pinned_aliases: Mapping[str, str] | None,
        create_row: Callable[[], object],
        add_row: Callable[[object], None],
        connect_row_signals: Callable[[object], None],
    ) -> tuple[dict[str, object], str, bool]:
        kind_rows: dict[str, object] = {}
        available_kinds = ArtifactKindBarController.ordered_kinds(kinds)
        if not available_kinds:
            return kind_rows, "", False

        row_specs = ArtifactKindBarController.build_row_specs(
            available_kinds,
            kind_titles=kind_titles,
            artifacts_by_kind=artifacts_by_kind,
        )
        for spec in row_specs:
            row = create_row()
            row.set_row(
                kind=spec.kind,
                title=spec.title,
                versions=list(spec.versions),
                pinned_aliases=dict(pinned_aliases or {}),
            )
            connect_row_signals(row)
            add_row(row)
            kind_rows[spec.kind] = row

        active_kind = ArtifactKindBarController.resolve_active_kind(available_kinds, current_active_kind)
        return kind_rows, active_kind, True
