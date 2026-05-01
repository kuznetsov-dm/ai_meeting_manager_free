from __future__ import annotations

import sys
from pathlib import Path

# Allow running the script without installing the package (PYTHONPATH not required).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
for _p in (str(_SRC), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from aimn.core.fingerprinting import compute_fingerprint, compute_source_fingerprint
from aimn.core.lineage import find_node_by_fingerprint
from aimn.core.meeting_ids import utc_now_iso
from aimn.core.meeting_store import FileMeetingStore
from aimn.core.pipeline import StageContext, StagePolicy
from aimn.core.plugin_manager import PluginManager
from aimn.core.plugins_config import PluginsConfig
from aimn.core.plugins_registry import ensure_plugins_enabled, load_registry_payload
from aimn.core.services.artifact_reader import ArtifactReader
from aimn.core.stages.text_processing import TextProcessingAdapter
from aimn.core.stages.transcription import TranscriptionAdapter
from aimn.domain.meeting import MeetingManifest, SCHEMA_VERSION, SourceInfo, SourceItem, StorageInfo


TRANSCRIPT_EXTS = (
    ".transcript.txt",
    ".transcript.json",
    ".transcript.md",
    ".transcript.vtt",
    ".transcript.srt",
)


@dataclass(frozen=True)
class VariantSpec:
    plugin_id: str
    model_id: str | None
    params: dict

    @property
    def key(self) -> str:
        suffix = self.model_id or "default"
        return f"{self.plugin_id}::{suffix}"


def _parse_transcript_base(name: str) -> str | None:
    for ext in TRANSCRIPT_EXTS:
        if name.endswith(ext):
            return name[: -len(ext)]
    if ".transcript." in name:
        return name.split(".transcript.", 1)[0]
    return None


def _parse_audio_base(name: str) -> str | None:
    if ".audio." in name:
        return name.split(".audio.", 1)[0]
    return None


def _meeting_prefix(base_name: str, fallback_path: Path) -> str:
    match = re.match(r"^(\d{6}-\d{4})", base_name)
    if match:
        return match.group(1)
    stamp = datetime.fromtimestamp(fallback_path.stat().st_mtime, timezone.utc)
    return stamp.strftime("%y%m%d-%H%M")


def _meeting_id_for(base_name: str, source_path: Path) -> str:
    prefix = _meeting_prefix(base_name, source_path)
    fingerprint = compute_source_fingerprint(str(source_path))
    key_source = fingerprint.split(":", 1)[-1]
    key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{key}"


def _discover_text_processing_plugins(repo_root: Path, *, include_mock: bool) -> list[str]:
    plugin_ids: list[str] = []
    for plugin_json in repo_root.glob("plugins/**/plugin.json"):
        try:
            payload = json.loads(plugin_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        plugin_id = str(payload.get("id", "") or "").strip()
        if not plugin_id.startswith("text_processing."):
            continue
        if not include_mock and (".mock" in plugin_id or ".fake" in plugin_id):
            continue
        plugin_ids.append(plugin_id)
    return sorted(set(plugin_ids))


def _load_models_from_settings(repo_root: Path, plugin_id: str) -> list[str]:
    settings_path = repo_root / "config" / "settings" / "plugins" / f"{plugin_id}.json"
    if not settings_path.exists():
        return []
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    models = payload.get("models", [])
    if not isinstance(models, list):
        return []
    out: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("model_id", "") or "").strip()
        if model_id:
            out.append(model_id)
    return list(dict.fromkeys(out))


def _load_models_from_plugin_json(repo_root: Path, plugin_id: str) -> list[str]:
    plugin_json = repo_root / "plugins" / plugin_id / "plugin.json"
    if not plugin_json.exists():
        for candidate in repo_root.glob("plugins/**/plugin.json"):
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(payload.get("id", "") or "").strip() == plugin_id:
                plugin_json = candidate
                break
    if not plugin_json.exists():
        return []
    try:
        payload = json.loads(plugin_json.read_text(encoding="utf-8"))
    except Exception:
        return []
    ui_schema = payload.get("ui_schema", {})
    settings = ui_schema.get("settings", [])
    if not isinstance(settings, list):
        return []
    out: list[str] = []
    for item in settings:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "") or "").strip()
        if key not in {"model_id", "embeddings_model_id"}:
            continue
        options = item.get("options", [])
        if not isinstance(options, list):
            continue
        for opt in options:
            if not isinstance(opt, dict):
                continue
            value = str(opt.get("value", "") or "").strip()
            if value:
                out.append(value)
    return list(dict.fromkeys(out))


def _load_models_for_plugin(repo_root: Path, plugin_id: str) -> list[str]:
    models = _load_models_from_settings(repo_root, plugin_id)
    if models:
        return models
    models = _load_models_from_plugin_json(repo_root, plugin_id)
    return models


def _build_variants(
    plugin_ids: Iterable[str],
    models_map: dict[str, list[str]],
) -> list[VariantSpec]:
    variants: list[VariantSpec] = []
    for plugin_id in plugin_ids:
        models = models_map.get(plugin_id, [])
        if not models:
            params = {
                "compare_enabled": False,
                "compare_models": "",
                "allow_download": False,
            }
            variants.append(VariantSpec(plugin_id=plugin_id, model_id=None, params=params))
            continue
        for model_id in models:
            params = {
                "model_id": model_id,
                "embeddings_model_id": model_id,
                "compare_enabled": False,
                "compare_models": "",
                "allow_download": False,
            }
            variants.append(VariantSpec(plugin_id=plugin_id, model_id=model_id, params=params))
    return variants


def _load_or_create_meeting(
    store: FileMeetingStore,
    base_name: str,
    transcript_path: Path | None,
    audio_path: Path | None,
) -> MeetingManifest | None:
    meeting_path = store.output_dir / f"{base_name}__MEETING.json"
    if meeting_path.exists():
        try:
            meeting = store.load(base_name)
        except Exception:
            meeting = None
    else:
        meeting = None

    if meeting is None:
        source_path = audio_path or transcript_path
        if not source_path:
            return None
        meeting_id = _meeting_id_for(base_name, source_path)
        created_at = utc_now_iso()
        fingerprint = compute_source_fingerprint(str(source_path))
        item = SourceItem(
            source_id="src1",
            input_filename=source_path.name,
            input_path=str(source_path),
            size_bytes=source_path.stat().st_size,
            mtime_utc=datetime.fromtimestamp(
                source_path.stat().st_mtime, timezone.utc
            )
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            content_fingerprint=fingerprint,
        )
        meeting = MeetingManifest(
            schema_version=SCHEMA_VERSION,
            meeting_id=meeting_id,
            base_name=base_name,
            created_at=created_at,
            updated_at=created_at,
            storage=StorageInfo(),
            source=SourceInfo(items=[item]),
        )

    if transcript_path:
        meeting.transcript_relpath = transcript_path.name
    if audio_path:
        meeting.audio_relpath = audio_path.name
    return meeting


def _collect_inputs(output_dir: Path) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path]]:
    transcripts: dict[str, Path] = {}
    audios: dict[str, Path] = {}
    meetings: dict[str, Path] = {}
    for item in output_dir.iterdir():
        if item.is_dir():
            continue
        name = item.name
        if name.endswith("__MEETING.json"):
            base_name = name[: -len("__MEETING.json")]
            meetings[base_name] = item
            continue
        base_name = _parse_transcript_base(name)
        if base_name:
            transcripts[base_name] = item
            continue
        base_name = _parse_audio_base(name)
        if base_name:
            audios[base_name] = item
    return transcripts, audios, meetings


def _load_active_preset_id(repo_root: Path) -> str:
    active_path = repo_root / "config" / "settings" / "pipeline" / "active.json"
    if not active_path.exists():
        return "default"
    try:
        payload = json.loads(active_path.read_text(encoding="utf-8"))
    except Exception:
        return "default"
    preset = str(payload.get("preset", "") or "").strip()
    return preset or "default"


def _load_transcription_stage(repo_root: Path) -> tuple[str, dict]:
    preset = _load_active_preset_id(repo_root)
    preset_path = repo_root / "config" / "settings" / "pipeline" / f"{preset}.json"
    if not preset_path.exists():
        preset_path = repo_root / "config" / "settings" / "pipeline" / "default.json"
    try:
        payload = json.loads(preset_path.read_text(encoding="utf-8"))
    except Exception:
        return "transcription.whisperadvanced", {}
    stages = payload.get("stages", {})
    if not isinstance(stages, dict):
        return "transcription.whisperadvanced", {}
    stage = stages.get("transcription", {})
    if not isinstance(stage, dict):
        return "transcription.whisperadvanced", {}
    plugin_id = str(stage.get("plugin_id", "") or "").strip() or "transcription.whisperadvanced"
    params = stage.get("params", {})
    return plugin_id, (params if isinstance(params, dict) else {})


def _variant_report_record(
    *,
    batch_id: str,
    meeting: MeetingManifest,
    transcript_relpath: str,
    variant: VariantSpec,
    plugin_version: str,
    node_fingerprint: str,
    alias: str | None,
    edited_relpath: str | None,
    public_params: dict,
    run_params: dict,
    status: str,
    cache_hit: bool,
    error: str | None,
    warnings: list[str],
) -> dict:
    return {
        "batch_id": batch_id,
        "meeting_id": meeting.meeting_id,
        "base_name": meeting.base_name,
        "transcript_relpath": transcript_relpath,
        "plugin_id": variant.plugin_id,
        "plugin_version": plugin_version,
        "model_id": variant.model_id,
        "variant_key": variant.key,
        "node_fingerprint": node_fingerprint,
        "alias": alias,
        "edited_relpath": edited_relpath,
        "public_params": public_params,
        "run_params": run_params,
        "status": status,
        "cache_hit": cache_hit,
        "error": error,
        "warnings": warnings,
        "recorded_at": utc_now_iso(),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Batch-run text_processing variants on transcripts.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="",
        help="Output directory (default: ./output).",
    )
    parser.add_argument(
        "--plugins",
        type=str,
        default="",
        help="Comma/semicolon-separated list of plugin IDs to run.",
    )
    parser.add_argument(
        "--include-mock",
        action="store_true",
        help="Include mock/fake text_processing plugins.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-run even if cache hit exists.",
    )
    parser.add_argument(
        "--transcribe-missing",
        action="store_true",
        help="If transcripts are missing, run the active transcription stage on audio files first.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of meetings processed (0 = all).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else (repo_root / "output")
    if not output_dir.exists():
        print(f"output_dir_not_found: {output_dir}")
        return 2

    transcripts, audios, meetings = _collect_inputs(output_dir)
    # text_processing requires a transcript; optionally generate missing transcripts from audio.
    base_names = sorted(set(transcripts) | set(meetings) | (set(audios) if args.transcribe_missing else set()))
    if args.limit and args.limit > 0:
        base_names = base_names[: args.limit]
    if not base_names:
        print("no_inputs_found")
        return 0

    plugin_ids = _discover_text_processing_plugins(repo_root, include_mock=args.include_mock)
    if args.plugins:
        raw = re.split(r"[;,|\n]+", args.plugins.strip())
        allowed = {item.strip() for item in raw if item.strip()}
        plugin_ids = [pid for pid in plugin_ids if pid in allowed]
    if not plugin_ids:
        print("no_text_processing_plugins")
        return 2

    models_map = {pid: _load_models_for_plugin(repo_root, pid) for pid in plugin_ids}
    variants = _build_variants(plugin_ids, models_map)
    if not variants:
        print("no_variants_resolved")
        return 2

    transcription_plugin_id = ""
    transcription_params: dict = {}
    if args.transcribe_missing:
        transcription_plugin_id, transcription_params = _load_transcription_stage(repo_root)

    registry_payload, _source, _path = load_registry_payload(repo_root)
    ensure_ids = list(plugin_ids)
    if transcription_plugin_id:
        ensure_ids.append(transcription_plugin_id)
    registry_payload = ensure_plugins_enabled(registry_payload, ensure_ids)
    registry_config = PluginsConfig(registry_payload)
    plugin_manager = PluginManager(repo_root, registry_config)
    plugin_manager.load()

    stage_policy = StagePolicy(stage_id="text_processing", required=True, continue_on_error=True, depends_on=[])
    stage_params = {"cleanup_pre_edit": True}
    transcription_policy = StagePolicy(
        stage_id="transcription",
        required=True,
        continue_on_error=False,
        depends_on=[],
    )

    report_dir = output_dir / "analysis"
    report_dir.mkdir(parents=True, exist_ok=True)
    batch_id = datetime.now(timezone.utc).strftime("batch_%Y%m%d_%H%M%S")
    report_path = report_dir / f"edit_variant_report_{batch_id}.jsonl"
    summary_path = report_dir / f"edit_variant_summary_{batch_id}.json"

    store = FileMeetingStore(output_dir)
    total_records = 0
    skipped_meetings: list[str] = []
    errors: list[str] = []

    with report_path.open("w", encoding="utf-8") as report_file:
        for base_name in base_names:
            transcript_path = transcripts.get(base_name)
            audio_path = audios.get(base_name)
            meeting = _load_or_create_meeting(store, base_name, transcript_path, audio_path)
            if not meeting or not meeting.transcript_relpath:
                if not args.transcribe_missing or not meeting or not audio_path:
                    skipped_meetings.append(base_name)
                    continue

                transcribe_config_data = {
                    "pipeline": {"preset": "batch_edit_variants"},
                    "stages": {
                        "transcription": {
                            "plugin_id": transcription_plugin_id,
                            "params": dict(transcription_params),
                        }
                    },
                }
                transcribe_config = PluginsConfig(transcribe_config_data)
                transcribe_adapter = TranscriptionAdapter(transcription_policy, transcribe_config)

                def _emit(event) -> None:
                    if event is None:
                        return

                transcribe_context = StageContext(
                    meeting=meeting,
                    force_run=bool(args.force),
                    output_dir=str(output_dir),
                    plugin_manager=plugin_manager,
                    event_callback=_emit,
                )
                transcribe_result = transcribe_adapter.run(transcribe_context)
                meeting.updated_at = utc_now_iso()
                store.save(meeting)

                if transcribe_result.status != "success" or not meeting.transcript_relpath:
                    skipped_meetings.append(base_name)
                    continue
            transcript_relpath = meeting.transcript_relpath
            reader = ArtifactReader(output_dir)
            transcript_input = reader.read_text_with_fingerprint(transcript_relpath)
            if not transcript_input.fingerprint:
                skipped_meetings.append(base_name)
                continue

            for variant in variants:
                config_data = {
                    "pipeline": {"preset": "batch_edit_variants"},
                    "stages": {
                        "text_processing": {
                            "params": dict(stage_params),
                            "variants": [
                                {"plugin_id": variant.plugin_id, "params": dict(variant.params)}
                            ],
                        }
                    },
                }
                config = PluginsConfig(config_data)
                adapter = TextProcessingAdapter(stage_policy, config)
                warnings: list[str] = []

                def _emit(event):
                    if event.event_type == "plugin_notice" and event.message:
                        warnings.append(str(event.message))

                context = StageContext(
                    meeting=meeting,
                    force_run=bool(args.force),
                    output_dir=str(output_dir),
                    plugin_manager=plugin_manager,
                    event_callback=_emit,
                )

                merged_params = dict(stage_params)
                merged_params.update(variant.params)
                public_params, run_params = adapter._resolve_plugin_params(
                    context, variant.plugin_id, merged_params
                )
                public_params, run_params = adapter._apply_embeddings_fallback(
                    context, variant.plugin_id, public_params, run_params
                )
                plugin_version = "unknown"
                manifest = plugin_manager.manifest_for(variant.plugin_id)
                if manifest:
                    plugin_version = manifest.version
                parent_alias = adapter._find_parent_alias(meeting, transcript_relpath)
                parent_fps = [meeting.nodes[parent_alias].fingerprint] if parent_alias else []
                node_fp = compute_fingerprint(
                    "text_processing",
                    variant.plugin_id,
                    plugin_version,
                    public_params,
                    parent_fps + [transcript_input.fingerprint],
                )

                result = adapter.run(context)
                meeting.updated_at = utc_now_iso()
                store.save(meeting)

                alias = find_node_by_fingerprint(meeting, node_fp)
                edited_relpath = None
                if alias:
                    node = meeting.nodes.get(alias)
                    if node:
                        edited = next((a for a in node.artifacts if a.kind == "edited"), None)
                        if edited:
                            edited_relpath = edited.path
                if alias and edited_relpath:
                    expected = store.resolve_artifact_path(base_name, alias, "edited", "md")
                    if edited_relpath != expected and (output_dir / expected).exists():
                        edited_relpath = expected

                record = _variant_report_record(
                    batch_id=batch_id,
                    meeting=meeting,
                    transcript_relpath=transcript_relpath,
                    variant=variant,
                    plugin_version=plugin_version,
                    node_fingerprint=node_fp,
                    alias=alias,
                    edited_relpath=edited_relpath,
                    public_params=public_params,
                    run_params=run_params,
                    status=result.status,
                    cache_hit=bool(result.cache_hit),
                    error=result.error,
                    warnings=warnings,
                )
                report_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                total_records += 1
                if result.status == "failed":
                    errors.append(
                        f"{base_name}:{variant.key}:{result.error or 'unknown_error'}"
                    )

    summary = {
        "batch_id": batch_id,
        "output_dir": str(output_dir),
        "meetings_total": len(base_names),
        "meetings_skipped": skipped_meetings,
        "variants_total": len(variants),
        "records_total": total_records,
        "errors": errors,
        "report_path": str(report_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"batch_id: {batch_id}")
    print(f"variants: {len(variants)}")
    print(f"records: {total_records}")
    print(f"report: {report_path}")
    print(f"summary: {summary_path}")
    if skipped_meetings:
        print(f"skipped_meetings: {len(skipped_meetings)}")
    if errors:
        print(f"errors: {len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
