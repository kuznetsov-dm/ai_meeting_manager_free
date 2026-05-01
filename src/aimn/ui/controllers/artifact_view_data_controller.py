from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass


_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptArtifactData:
    transcript_text: str
    records: list[dict]
    ranges: list[tuple[int, int] | None]
    suggestion_spans: list[object]


class ArtifactViewDataController:
    @staticmethod
    def resolve_segments_relpath(
        *,
        stage_id: str,
        alias: str,
        segments_relpaths: dict[str, str] | None,
    ) -> str:
        mapping = dict(segments_relpaths or {})
        return str(mapping.get(f"{stage_id}:{alias}") or mapping.get(str(alias or "")) or "").strip()

    @staticmethod
    def build_transcript_artifact_data(
        *,
        stage_id: str,
        alias: str,
        relpath: str,
        segments_relpaths: dict[str, str] | None,
        load_segments_records: Callable[[str], list[dict]],
        load_artifact_text: Callable[[str], str],
        transcript_suggestions_for_alias: Callable[[str], list[dict]],
        build_segment_text_ranges: Callable[[str, list[dict]], list[tuple[int, int] | None]],
        build_transcript_suggestion_spans: Callable[[list[dict], list[tuple[int, int] | None], list[dict]], list[object]],
    ) -> TranscriptArtifactData | None:
        segments_relpath = ArtifactViewDataController.resolve_segments_relpath(
            stage_id=str(stage_id or "").strip(),
            alias=str(alias or "").strip(),
            segments_relpaths=segments_relpaths,
        )
        records: list[dict] = []
        if segments_relpath:
            records = list(load_segments_records(segments_relpath) or [])
        if not records:
            return None
        transcript_text = ""
        try:
            transcript_text = str(load_artifact_text(str(relpath or "")) or "")
        except Exception as exc:
            _LOG.warning("transcript_artifact_text_load_failed relpath=%s error=%s", relpath, exc)
            transcript_text = ""
        ranges = list(build_segment_text_ranges(transcript_text, records) or [])
        suggestions = list(transcript_suggestions_for_alias(str(alias or "").strip()) or [])
        suggestion_spans = list(build_transcript_suggestion_spans(records, ranges, suggestions) or [])
        return TranscriptArtifactData(
            transcript_text=transcript_text,
            records=records,
            ranges=ranges,
            suggestion_spans=suggestion_spans,
        )
