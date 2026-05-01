from __future__ import annotations

from dataclasses import dataclass

from aimn.core.contracts import (
    KIND_ASR_SEGMENTS_JSON,
    KIND_DETECTED_LANGUAGE,
    KIND_SEGMENTS,
    KIND_TRANSCRIPT,
    PluginOutput,
)
from aimn.core.services.artifact_writer import ArtifactWriter
from aimn.core.services.segments_builder import build_segments_from_asr
from aimn.domain.meeting import ArtifactRef, SegmentIndex


@dataclass(frozen=True)
class TranscriptionArtifactsResult:
    artifacts: list[ArtifactRef]
    transcript_relpath: str | None
    segments_relpath: str | None
    segments_index: list[SegmentIndex] | None
    detected_language: str | None


def _format_transcript_from_segments(records: list[dict[str, object]], *, gap_ms: int = 1500) -> str:
    """
    Improves transcript readability by inserting paragraph breaks from timestamp pauses.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    prev_end_ms: int | None = None
    for rec in records:
        text = str(rec.get("text", "") or "").strip()
        if not text:
            continue
        start_ms = int(rec.get("start_ms", 0) or 0)
        end_ms = int(rec.get("end_ms", 0) or 0)
        if prev_end_ms is not None and (start_ms - prev_end_ms) >= int(gap_ms):
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
        current.append(text)
        prev_end_ms = end_ms if end_ms else start_ms
    if current:
        paragraphs.append(" ".join(current).strip())
    if not paragraphs:
        return ""
    return "\n\n".join(paragraphs).strip() + "\n"


def persist_transcription_outputs(
    *,
    base_name: str,
    alias: str | None,
    outputs: list[PluginOutput],
    writer: ArtifactWriter,
) -> tuple[TranscriptionArtifactsResult | None, tuple[str, str, str] | None]:
    artifacts: list[ArtifactRef] = []
    transcript_relpath: str | None = None
    segments_relpath: str | None = None
    segments_index: list[SegmentIndex] | None = None
    detected_language: str | None = None
    handled_kinds: set[str] = set()

    transcript_fallback = ""
    for candidate in outputs:
        if candidate.kind == KIND_TRANSCRIPT:
            transcript_fallback = candidate.content.strip()
            break

    parsed_segments_index: list[SegmentIndex] | None = None
    parsed_segment_records: list[dict[str, object]] | None = None
    for candidate in outputs:
        if candidate.kind != KIND_ASR_SEGMENTS_JSON:
            continue
        try:
            parsed_segments_index, parsed_segment_records = build_segments_from_asr(
                candidate.content, fallback_transcript=transcript_fallback or None
            )
        except Exception:
            parsed_segments_index, parsed_segment_records = None, None
        break

    for output in outputs:
        if output.kind in handled_kinds:
            continue
        if output.kind == KIND_DETECTED_LANGUAGE:
            detected_language = output.content.strip()
            handled_kinds.add(output.kind)
            continue
        if output.kind == KIND_ASR_SEGMENTS_JSON:
            segments_index = list(parsed_segments_index or [])
            records = list(parsed_segment_records or [])
            artifact, relpath, error = writer.write_json_records(
                base_name,
                alias,
                kind=KIND_SEGMENTS,
                records=records,
                user_visible=False,
            )
            if error:
                return None, (KIND_SEGMENTS, relpath, error)
            segments_relpath = relpath
            if artifact:
                artifacts.append(artifact)
            handled_kinds.add(KIND_SEGMENTS)
            handled_kinds.add(KIND_ASR_SEGMENTS_JSON)
            continue
        if output.kind == KIND_TRANSCRIPT:
            improved = _format_transcript_from_segments(parsed_segment_records) if parsed_segment_records else ""
            transcript_output = output.__class__(
                kind=KIND_TRANSCRIPT,
                content=improved or output.content,
                content_type=output.content_type or "text",
                user_visible=True,
            )
            artifact, relpath, error = writer.write_output(
                base_name,
                alias,
                transcript_output,
                ext="txt",
            )
            if error:
                return None, (KIND_TRANSCRIPT, relpath, error)
            transcript_relpath = relpath
            if artifact:
                artifacts.append(artifact)
            handled_kinds.add(KIND_TRANSCRIPT)
            continue

        # Do not persist raw ASR diagnostics by default; keep the output directory tidy.
        if output.kind == "asr_diagnostics_json":
            handled_kinds.add(output.kind)
            continue

        artifact, relpath, error = writer.write_output(base_name, alias, output)
        if error:
            return None, (output.kind, relpath, error)
        if artifact:
            artifacts.append(artifact)
        handled_kinds.add(output.kind)

    return (
        TranscriptionArtifactsResult(
            artifacts=artifacts,
            transcript_relpath=transcript_relpath,
            segments_relpath=segments_relpath,
            segments_index=segments_index,
            detected_language=detected_language,
        ),
        None,
    )


def purge_asr_debug_artifacts(*, meeting, output_dir) -> int:
    """
    Removes persisted internal Whisper ASR debug artifacts from both:
    - meeting.nodes[*].artifacts
    - the output directory

    This is a backwards-compat clean-up for older runs where these artifacts were written.
    """
    from pathlib import Path

    root = Path(output_dir)
    relpaths: list[str] = []
    for node in (getattr(meeting, "nodes", {}) or {}).values():
        artifacts = list(getattr(node, "artifacts", []) or [])
        if not artifacts:
            continue
        has_segments = any(str(getattr(a, "kind", "") or "") == KIND_SEGMENTS for a in artifacts)
        kept = []
        for art in artifacts:
            kind = str(getattr(art, "kind", "") or "")
            if kind == "asr_diagnostics_json":
                relpaths.append(str(getattr(art, "path", "") or ""))
                continue
            if kind == KIND_ASR_SEGMENTS_JSON and has_segments:
                relpaths.append(str(getattr(art, "path", "") or ""))
                continue
            kept.append(art)
        node.artifacts = kept

    removed_files = 0
    for rel in {rp for rp in relpaths if str(rp).strip()}:
        try:
            (root / rel).unlink(missing_ok=True)  # py311+
            removed_files += 1
        except Exception:
            continue
    return removed_files
