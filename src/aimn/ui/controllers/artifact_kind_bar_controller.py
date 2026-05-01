from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactKindRowSpec:
    kind: str
    title: str
    versions: tuple[object, ...]


class ArtifactKindBarController:
    _PREFERRED_ORDER = ("transcript", "summary")

    @classmethod
    def ordered_kinds(cls, kinds: Sequence[str]) -> list[str]:
        normalized = [str(kind or "").strip() for kind in (kinds or []) if str(kind or "").strip()]
        ordered = [kind for kind in cls._PREFERRED_ORDER if kind in normalized]
        ordered.extend([kind for kind in normalized if kind not in set(cls._PREFERRED_ORDER)])
        return ordered

    @classmethod
    def build_row_specs(
        cls,
        kinds: Sequence[str],
        *,
        kind_titles: Mapping[str, str] | None = None,
        artifacts_by_kind: Mapping[str, Sequence[object]] | None = None,
    ) -> list[ArtifactKindRowSpec]:
        titles = {str(k): str(v) for k, v in dict(kind_titles or {}).items()}
        artifacts = dict(artifacts_by_kind or {})
        specs: list[ArtifactKindRowSpec] = []
        for kind in cls.ordered_kinds(kinds):
            specs.append(
                ArtifactKindRowSpec(
                    kind=kind,
                    title=titles.get(kind, kind),
                    versions=tuple(artifacts.get(kind, []) or ()),
                )
            )
        return specs

    @staticmethod
    def resolve_active_kind(kinds: Sequence[str], active_kind: str) -> str:
        available = [str(kind or "").strip() for kind in (kinds or []) if str(kind or "").strip()]
        selected = str(active_kind or "").strip()
        if selected and selected in available:
            return selected
        if available:
            return available[0]
        return ""

    @staticmethod
    def selected_version_index(*, row_kind: str, active_kind: str, version_index: int | None) -> int | None:
        if str(row_kind or "").strip() != str(active_kind or "").strip():
            return None
        if version_index is None:
            return None
        return int(version_index)
