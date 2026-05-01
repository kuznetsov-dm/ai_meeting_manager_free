from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from aimn.core.contracts import KIND_EDITED, KIND_SUMMARY, KIND_TRANSCRIPT
from aimn.core.fingerprinting import compute_fingerprint
from aimn.core.lineage import apply_branching, find_node_by_fingerprint
from aimn.core.management_store import ManagementStore
from aimn.core.meeting_store import FileMeetingStore
from aimn.core.node_registry import allocate_alias, register_lineage_node
from aimn.core.pipeline import StageContext, StageEvent, StagePolicy, StageResult
from aimn.core.plugins_config import PluginsConfig
from aimn.core.services.artifact_reader import ArtifactReader
from aimn.core.services.artifact_writer import ArtifactWriter
from aimn.core.stages.base import PluginStageAdapter
from aimn.domain.meeting import ArtifactRef, MeetingManifest


class LlmProcessingAdapter(PluginStageAdapter):
    def __init__(self, policy: StagePolicy, config: PluginsConfig) -> None:
        super().__init__(stage_id="llm_processing", policy=policy, config=config)

    def run(self, context: StageContext) -> StageResult:
        self._context = context
        if not context.output_dir:
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error="output_dir missing for artifacts",
            )

        transcript_items = self._transcript_items(context.meeting)
        if not transcript_items:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="missing_input",
            )

        output_dir = Path(context.output_dir)
        variants = self._variants()
        stage_params = dict(self._config.plugin_params_for(self.stage_id) or {})
        # Legacy UI selection keys; variants list is the canonical source.
        stage_params.pop("selected_models", None)
        stage_params.pop("selected_providers", None)
        if not variants:
            try:
                plugin_id = self._config.plugin_id_for(self.stage_id)
            except Exception:
                return StageResult(
                    stage_id=self.stage_id,
                    status="skipped",
                    cache_hit=False,
                    skip_reason="no_plugin",
                )
            variants = [(plugin_id, stage_params)]

        store = FileMeetingStore(output_dir)
        writer = ArtifactWriter(
            output_dir,
            store,
            stage_id=self.stage_id,
            validator=self._validate_artifact_file,
            event_callback=context.event_callback,
        )
        force_branch = len(variants) > 1 or len(transcript_items) > 1
        cache_hits: list[bool] = []
        wrote_any = False
        total_steps = len(variants) * len(transcript_items)
        completed_steps = 0
        prompt_context_cache: dict[str, tuple[str, str]] = {}
        failed_variants: list[str] = []

        def _variant_label(pid: str, params: dict) -> str:
            model_key = _variant_model_key(params)
            if model_key:
                return f"{pid}:{model_key}"
            model_path = str(params.get("model_path", "") or "").strip()
            if model_path:
                return f"{pid}:{Path(model_path).name or model_path}"
            return pid

        def _emit_progress(message: str = "", *, active_variant: bool = False) -> None:
            if total_steps <= 0:
                return
            percent = _llm_stage_progress_percent(
                completed_steps=completed_steps,
                total_steps=total_steps,
                active_variant=active_variant,
            )
            if context.progress_callback:
                context.progress_callback(percent)
            if context.event_callback:
                context.event_callback(
                    StageEvent(
                        event_type="stage_progress",
                        stage_id=self.stage_id,
                        progress=percent,
                        message=message,
                    )
                )

        reader = ArtifactReader(output_dir)
        for parent_alias, transcript_relpath in transcript_items:
            transcript_input = reader.read_text_with_fingerprint(transcript_relpath)
            if transcript_input.fingerprint is None:
                return StageResult(
                    stage_id=self.stage_id,
                    status="failed",
                    cache_hit=False,
                    error=f"{KIND_TRANSCRIPT} not found: {transcript_relpath}",
                )
            transcript_text = transcript_input.content or ""
            source_fp = transcript_input.fingerprint
            parent_fps = [context.meeting.nodes[parent_alias].fingerprint] if parent_alias else []

            for plugin_id, plugin_params in variants:
                merged_params = dict(stage_params)
                if isinstance(plugin_params, dict):
                    merged_params.update(plugin_params)
                context_key = json.dumps(
                    {
                        "prompt_agenda_id": merged_params.get("prompt_agenda_id"),
                        "prompt_agenda_title": merged_params.get("prompt_agenda_title"),
                        "prompt_agenda_text": merged_params.get("prompt_agenda_text"),
                        "prompt_project_ids": merged_params.get("prompt_project_ids"),
                        "inject_management_context": merged_params.get("inject_management_context"),
                        "use_approved_entities": merged_params.get("use_approved_entities"),
                        "prompt_projects_limit": merged_params.get("prompt_projects_limit"),
                        "prompt_tasks_limit": merged_params.get("prompt_tasks_limit"),
                    },
                    sort_keys=True,
                    ensure_ascii=True,
                )
                cached = prompt_context_cache.get(context_key)
                if cached is None:
                    cached = self._management_prompt_context(
                        app_root=output_dir.parent,
                        meeting_id=str(getattr(context.meeting, "meeting_id", "") or ""),
                        params=merged_params,
                    )
                    prompt_context_cache[context_key] = cached
                prompt_context, context_hash = cached
                prompt_input = _compose_transcript_input(transcript_text, prompt_context)
                public_params, run_params = self._resolve_plugin_params(
                    context, plugin_id, merged_params
                )
                fingerprint_params = self._stable_fingerprint_params(public_params)
                if context_hash:
                    fingerprint_params["_management_context_hash"] = context_hash
                plugin_version = "unknown"
                if context.plugin_manager:
                    manifest = context.plugin_manager.manifest_for(plugin_id)
                    if manifest:
                        plugin_version = manifest.version
                node_fp = compute_fingerprint(
                    self.stage_id,
                    plugin_id,
                    plugin_version,
                    fingerprint_params,
                    parent_fps + [source_fp],
                )
                legacy_node_fp = compute_fingerprint(
                    self.stage_id,
                    plugin_id,
                    plugin_version,
                    public_params,
                    parent_fps + [source_fp],
                )

                apply_branching(
                    context.meeting,
                    self.stage_id,
                    node_fp,
                    force_branch=force_branch,
                    output_dir=output_dir,
                    store=store,
                )

                if not context.force_run:
                    existing_alias = find_node_by_fingerprint(context.meeting, node_fp)
                    if not existing_alias and legacy_node_fp != node_fp:
                        existing_alias = find_node_by_fingerprint(context.meeting, legacy_node_fp)
                    if not existing_alias:
                        existing_alias = self._find_cacheable_node_by_stable_params(
                            context.meeting,
                            stage_id=self.stage_id,
                            plugin_id=plugin_id,
                            plugin_version=plugin_version,
                            stable_params=fingerprint_params,
                            source_fps=[source_fp],
                            parent_fps=parent_fps,
                        )
                    if existing_alias and self._node_artifacts_exist(
                        context.meeting,
                        alias=existing_alias,
                        output_dir=output_dir,
                        required_kinds={KIND_SUMMARY},
                    ):
                        if context.event_callback:
                            context.event_callback(
                                StageEvent(
                                    event_type="cache_hit",
                                    stage_id=self.stage_id,
                                    message=f"{existing_alias}",
                                )
                            )
                        cache_hits.append(True)
                        completed_steps += 1
                        _emit_progress(f"{_variant_label(plugin_id, merged_params)} ({completed_steps}/{total_steps})")
                        continue

                parent_aliases = [parent_alias] if parent_alias else []
                alias_params = dict(fingerprint_params)
                alias_params["plugin_id"] = plugin_id
                alias = allocate_alias(context.meeting, self.stage_id, alias_params, parent_aliases)
                use_alias = alias if context.meeting.naming_mode == "branched" else None

                _emit_progress(
                    f"{_variant_label(plugin_id, merged_params)} ({completed_steps + 1}/{total_steps})",
                    active_variant=True,
                )
                execution = self._run_hook(
                    context,
                    "derive.after_postprocess",
                    plugin_id,
                    run_params,
                    input_text=prompt_input,
                    alias=use_alias,
                )
                if execution is None:
                    if context.event_callback:
                        context.event_callback(
                            StageEvent(
                                event_type="plugin_notice",
                                stage_id=self.stage_id,
                                message=f"llm_provider_skipped_no_handler(plugin={plugin_id})",
                            )
                        )
                    completed_steps += 1
                    _emit_progress(f"{_variant_label(plugin_id, merged_params)} ({completed_steps}/{total_steps})")
                    continue
                if execution.error:
                    return StageResult(
                        stage_id=self.stage_id,
                        status="failed",
                        cache_hit=False,
                        error=execution.error,
                    )
                result = execution.result
                if result is None:
                    return StageResult(
                        stage_id=self.stage_id,
                        status="failed",
                        cache_hit=False,
                        error="empty_plugin_result",
                    )
                if context.event_callback and result.warnings:
                    for warning in result.warnings:
                        context.event_callback(
                            StageEvent(event_type="plugin_notice", stage_id=self.stage_id, message=warning)
                        )

                if self._is_mock_fallback(result):
                    _emit_llm_model_outcome(
                        context,
                        plugin_id=plugin_id,
                        params=merged_params,
                        summary_quality="failed",
                        failure_code=_llm_failure_code_from_warnings(result.warnings),
                    )
                    failed_variants.append(
                        _describe_llm_variant_failure(
                            _variant_label(plugin_id, merged_params),
                            result.warnings,
                        )
                    )
                    completed_steps += 1
                    _emit_progress(f"{_variant_label(plugin_id, merged_params)} ({completed_steps}/{total_steps})")
                    continue

                summary_output = next(
                    (output for output in result.outputs if output.kind == KIND_SUMMARY), None
                )
                if not summary_output:
                    summary_output = next(
                        (output for output in result.outputs if output.kind == KIND_EDITED), None
                    )
                if not summary_output:
                    return StageResult(
                        stage_id=self.stage_id,
                        status="failed",
                        cache_hit=False,
                        error=(
                            "llm_processing plugin produced no "
                            f"'{KIND_SUMMARY}' or '{KIND_EDITED}' output"
                        ),
                    )

                summary_output = summary_output.__class__(
                    kind=KIND_SUMMARY,
                    content=summary_output.content,
                    content_type=summary_output.content_type or "text/markdown",
                    user_visible=True,
                )
                summary_quality, summary_issue = _classify_summary_artifact(summary_output.content)
                if summary_quality != "usable":
                    _emit_llm_model_outcome(
                        context,
                        plugin_id=plugin_id,
                        params=merged_params,
                        summary_quality=summary_quality,
                        failure_code=summary_issue,
                    )
                    if context.event_callback:
                        context.event_callback(
                            StageEvent(
                                event_type="plugin_notice",
                                stage_id=self.stage_id,
                                message=summary_issue or "llm_invalid_summary_artifact",
                            )
                        )
                    failed_variants.append(
                        f"{_variant_label(plugin_id, merged_params)}:{summary_issue or 'llm_invalid_summary_artifact'}"
                    )
                    completed_steps += 1
                    _emit_progress(f"{_variant_label(plugin_id, merged_params)} ({completed_steps}/{total_steps})")
                    continue
                outputs_to_write: list[tuple[str, object, str]] = [(KIND_SUMMARY, summary_output, "md")]

                artifacts: list[ArtifactRef] = []
                for out_kind, output, ext in outputs_to_write:
                    artifact, relpath, error = writer.write_output(
                        context.meeting.base_name,
                        use_alias,
                        output,
                        ext=ext,
                    )
                    if error:
                        return StageResult(
                            stage_id=self.stage_id,
                            status="failed",
                            cache_hit=False,
                            error=f"{out_kind}_{error}:{relpath}",
                        )
                    artifacts.append(
                        artifact
                        if artifact
                        else ArtifactRef(
                            kind=out_kind,
                            path=relpath,
                            content_type=getattr(output, "content_type", None) or "text/markdown",
                            user_visible=True,
                        )
                    )

                cacheable = self._parents_cacheable(context, parent_aliases) and not self._is_mock_fallback(result)
                register_lineage_node(
                    manifest=context.meeting,
                    alias=alias,
                    stage_id=self.stage_id,
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    params=fingerprint_params,
                    parent_aliases=parent_aliases,
                    source_fps=[source_fp],
                    artifacts=artifacts,
                    created_at=datetime.now(UTC)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    cacheable=cacheable,
                )
                _emit_llm_model_outcome(
                    context,
                    plugin_id=plugin_id,
                    params=merged_params,
                    summary_quality="usable",
                    failure_code="",
                )

                wrote_any = True
                cache_hits.append(False)
                completed_steps += 1
                _emit_progress(f"{_variant_label(plugin_id, merged_params)} ({completed_steps}/{total_steps})")

        if not wrote_any and cache_hits:
            return StageResult(stage_id=self.stage_id, status="success", cache_hit=all(cache_hits))
        if not wrote_any and failed_variants:
            detail = "; ".join(item for item in failed_variants[:3] if item)
            return StageResult(
                stage_id=self.stage_id,
                status="failed",
                cache_hit=False,
                error=f"no_real_llm_artifacts:{detail or 'all_variants_failed'}",
            )
        if not wrote_any and not cache_hits:
            return StageResult(
                stage_id=self.stage_id,
                status="skipped",
                cache_hit=False,
                skip_reason="no_plugin",
            )
        return StageResult(stage_id=self.stage_id, status="success", cache_hit=False)

    def _management_prompt_context(
        self,
        *,
        app_root: Path,
        meeting_id: str,
        params: dict,
    ) -> tuple[str, str]:
        include_context = _coerce_bool(params.get("inject_management_context"), default=True)
        if not include_context:
            return "", ""

        agenda_text, agenda_title = _resolve_agenda_context(app_root, params)
        include_approved = _coerce_bool(params.get("use_approved_entities"), default=True)
        max_projects = _coerce_int(params.get("prompt_projects_limit"), default=20, min_value=1, max_value=200)
        max_tasks = _coerce_int(params.get("prompt_tasks_limit"), default=30, min_value=1, max_value=300)
        selected_project_ids = _parse_project_ids(params.get("prompt_project_ids"))

        projects: list[dict] = []
        tasks: list[dict] = []
        if include_approved:
            store = ManagementStore(app_root)
            try:
                projects = store.list_projects()
                tasks = store.list_tasks()
            finally:
                store.close()
            if selected_project_ids:
                projects, tasks = _filter_management_entities_by_projects(
                    projects,
                    tasks,
                    selected_project_ids=selected_project_ids,
                )

        blocks: list[str] = []
        if agenda_text:
            title = agenda_title or "Planned agenda"
            blocks.append(f"## Planned Agenda\nTitle: {title}\n{agenda_text.strip()}")

        if include_approved and (projects or tasks):
            project_lines = _render_approved_projects(projects, limit=max_projects)
            task_lines = _render_approved_tasks(tasks, meeting_id=meeting_id, limit=max_tasks)
            approved_parts: list[str] = []
            if project_lines:
                approved_parts.append("### Approved projects\n" + "\n".join(project_lines))
            if task_lines:
                approved_parts.append("### Approved tasks\n" + "\n".join(task_lines))
            if approved_parts:
                blocks.append("## Approved entities\n" + "\n\n".join(approved_parts))

        if not blocks:
            return "", ""

        context_text = "\n\n".join(
            [
                "You have approved management entities for this workspace.",
                "Primary rule: do not create duplicate project/task entities when an approved one matches.",
                "Reuse approved names exactly when the intent matches.",
                "\n\n".join(blocks),
            ]
        ).strip()
        context_hash = hashlib.sha1(context_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return context_text, context_hash

    def _transcript_items(self, manifest: MeetingManifest) -> list[tuple[str | None, str]]:
        items: list[tuple[str | None, str]] = []
        for alias, node in manifest.nodes.items():
            if node.stage_id != "transcription":
                continue
            for artifact in node.artifacts:
                if artifact.kind == KIND_TRANSCRIPT:
                    items.append((alias, artifact.path))
        if items:
            return items
        relpath = str(getattr(manifest, "transcript_relpath", "") or "").strip()
        if relpath:
            return [(None, relpath)]
        return items

    def _variants(self) -> list[tuple[str, dict]]:
        variants = self._config.variants_for_stage(self.stage_id)
        resolved: list[tuple[str, dict]] = []
        for variant in variants:
            plugin_id = variant.get("plugin_id")
            if not plugin_id:
                continue
            params = variant.get("params", {})
            if not isinstance(params, dict):
                params = {}
            resolved.append((str(plugin_id), params))
        return resolved


def _extract_markdown_section(text: str, *, titles: list[str]) -> str:
    if not text:
        return ""
    wanted = {str(t or "").strip().lower() for t in (titles or []) if str(t or "").strip()}
    if not wanted:
        return ""
    lines = str(text).splitlines()
    in_section = False
    collected: list[str] = []
    for line in lines:
        raw = str(line or "")
        stripped = raw.strip()
        lower = stripped.lower()
        if lower.startswith("#"):
            title = lower.lstrip("#").strip()
            if title in wanted:
                in_section = True
                continue
            if in_section and (lower.startswith("##") or lower.startswith("# ")):
                break
        if not in_section:
            continue
        if not stripped:
            continue
        collected.append(raw)
    if not collected:
        return ""
    return "\n".join(collected).strip()


def _coerce_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_int(value: object, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return max(min_value, min(parsed, max_value))


def _resolve_agenda_context(app_root: Path, params: dict) -> tuple[str, str]:
    raw_text = str(params.get("prompt_agenda_text", "") or "").strip()
    raw_title = str(params.get("prompt_agenda_title", "") or "").strip()
    if raw_text:
        return raw_text, raw_title or "Planned agenda"

    agenda_id = str(params.get("prompt_agenda_id", "") or "").strip()
    if not agenda_id:
        return "", ""
    agendas = _load_agendas_catalog(app_root)
    for agenda in agendas:
        if str(agenda.get("id", "")).strip() != agenda_id:
            continue
        title = str(agenda.get("title", "") or "").strip() or "Planned agenda"
        text = str(agenda.get("text", "") or "").strip()
        return text, title
    return "", ""


def _load_agendas_catalog(app_root: Path) -> list[dict]:
    store = ManagementStore(app_root)
    try:
        raw = store.list_agendas()
    finally:
        store.close()
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        agenda_id = str(entry.get("id", "") or "").strip()
        if not agenda_id:
            continue
        out.append(
            {
                "id": agenda_id,
                "title": str(entry.get("title", "") or "").strip(),
                "text": str(entry.get("text", "") or "").strip(),
            }
        )
    return out


def _render_approved_projects(items: list[dict], *, limit: int) -> list[str]:
    lines: list[str] = []
    for item in items[:limit]:
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        status = str(item.get("status", "") or "").strip()
        if status:
            lines.append(f"- {name} [{status}]")
            continue
        lines.append(f"- {name}")
    return lines


def _render_approved_tasks(items: list[dict], *, meeting_id: str, limit: int) -> list[str]:
    lines: list[str] = []
    count = 0
    target_meeting = str(meeting_id or "").strip()
    for item in items:
        title = str(item.get("title", "") or "").strip()
        if not title:
            continue
        status = str(item.get("status", "") or "").strip()
        meetings = item.get("meetings")
        related = False
        if isinstance(meetings, list):
            related = target_meeting in {str(mid or "").strip() for mid in meetings}
        project_id = str(item.get("project_id", "") or "").strip()
        marker = "(discussed in this meeting)" if related else ""
        suffix = " ".join(part for part in [status, project_id, marker] if part).strip()
        if suffix:
            lines.append(f"- {title} [{suffix}]")
        else:
            lines.append(f"- {title}")
        count += 1
        if count >= limit:
            break
    return lines


def _parse_project_ids(raw: object) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for chunk in text.split(","):
        item = str(chunk or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _filter_management_entities_by_projects(
    projects: list[dict],
    tasks: list[dict],
    *,
    selected_project_ids: list[str],
) -> tuple[list[dict], list[dict]]:
    selected = {str(pid or "").strip() for pid in (selected_project_ids or []) if str(pid or "").strip()}
    if not selected:
        return projects, tasks
    filtered_projects = [
        item
        for item in (projects or [])
        if isinstance(item, dict) and str(item.get("project_id", "") or "").strip() in selected
    ]
    filtered_tasks: list[dict] = []
    for item in tasks or []:
        if not isinstance(item, dict):
            continue
        primary = str(item.get("project_id", "") or "").strip()
        linked = {
            str(pid or "").strip()
            for pid in (item.get("project_ids", []) or [])
            if str(pid or "").strip()
        }
        if primary in selected or bool(linked & selected):
            filtered_tasks.append(item)
    return filtered_projects, filtered_tasks


def _compose_transcript_input(transcript_text: str, management_context: str) -> str:
    transcript = str(transcript_text or "").strip()
    context_block = str(management_context or "").strip()
    if not context_block:
        return transcript
    return "\n".join(
        [
            "[APPROVED_CONTEXT_START]",
            context_block,
            "[APPROVED_CONTEXT_END]",
            "",
            "[MEETING_TRANSCRIPT_START]",
            transcript,
            "[MEETING_TRANSCRIPT_END]",
        ]
    ).strip()


def _describe_llm_variant_failure(variant_label: str, warnings: list[str]) -> str:
    label = str(variant_label or "").strip() or "llm_variant"
    ignored = {"mock_fallback", "mock_output", "empty_input_text"}
    detail = ""
    for item in warnings or []:
        marker = str(item or "").strip()
        if not marker or marker in ignored:
            continue
        detail = marker[:220]
        break
    return f"{label}:{detail or 'mock_fallback'}"


def _variant_model_key(params: dict) -> str:
    model_id = str(params.get("model_id", "") or "").strip()
    if model_id:
        return model_id
    model = str(params.get("model", "") or "").strip()
    if model:
        return model
    model_path = str(params.get("model_path", "") or "").strip()
    if model_path:
        return Path(model_path).name
    return ""


def _llm_stage_progress_percent(
    *,
    completed_steps: int,
    total_steps: int,
    active_variant: bool,
) -> int:
    total = max(0, int(total_steps or 0))
    if total <= 0:
        return 0
    completed = max(0, min(int(completed_steps or 0), total))
    if not active_variant or completed >= total:
        return max(0, min(100, int((completed / total) * 100)))
    in_flight = int(((completed + 0.15) / total) * 100)
    return max(1, min(99, in_flight))


def _emit_llm_model_outcome(
    context: StageContext,
    *,
    plugin_id: str,
    params: dict,
    summary_quality: str,
    failure_code: str,
) -> None:
    if not context.event_callback:
        return
    model_id = _variant_model_key(params if isinstance(params, dict) else {})
    if not model_id:
        return
    payload = {
        "plugin_id": str(plugin_id or "").strip(),
        "model_id": model_id,
        "summary_quality": str(summary_quality or "").strip().lower() or "failed",
        "failure_code": str(failure_code or "").strip().lower(),
    }
    context.event_callback(
        StageEvent(
            event_type="plugin_notice",
            stage_id="llm_processing",
            message=f"llm_model_outcome:{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}",
        )
    )


def _llm_failure_code_from_warnings(warnings: list[str]) -> str:
    items = [str(item or "").strip().lower() for item in (warnings or []) if str(item or "").strip()]
    for item in items:
        if item in {"mock_fallback", "mock_output", "empty_input_text"}:
            continue
        if "api_key_missing" in item or item == "auth_error":
            return "auth_error"
        if "status=429" in item or "rate_limited" in item or "too many requests" in item:
            return "rate_limited"
        if "status=403" in item or "provider_blocked" in item or "blocked" in item:
            return "provider_blocked"
        if "status=404" in item or "model_not_found" in item or "not available" in item:
            return "model_not_found"
        if "timeout" in item:
            return "timeout"
        if any(token in item for token in {"ssl", "unexpected_eof", "transport_error", "connection reset", "winerror 10054"}):
            return "transport_error"
        if "empty_response" in item:
            return "empty_response"
        if "bad_request" in item or "status=400" in item:
            return "bad_request"
        if "request_failed" in item:
            return "request_failed"
    return "request_failed"


def _looks_invalid_summary_artifact(text: object) -> bool:
    quality, _issue = _classify_summary_artifact(text)
    return quality != "usable"


def _classify_summary_artifact(text: object) -> tuple[str, str]:
    value = str(text or "").strip()
    if not value:
        return "failed", "llm_invalid_summary_artifact"
    lowered = value.lower()
    if "<think>" in lowered and "</think>" not in lowered:
        return "failed", "llm_invalid_summary_artifact"
    if lowered.startswith("<think>"):
        return "failed", "llm_invalid_summary_artifact"
    if lowered.startswith("# summary"):
        compact_lines = [line.strip() for line in value.splitlines() if line.strip()]
        if len(compact_lines) <= 2 and any(
            marker in lowered
            for marker in {
                "not available",
                "server not available",
                "response format error",
                "api error",
                "ollama error",
            }
        ):
            return "degraded", "llm_degraded_summary_artifact"
    compact = "".join(ch for ch in value if not ch.isspace())
    heading_count = sum(1 for line in value.splitlines() if line.strip().startswith("#"))
    if heading_count and len(compact) < 25:
        return "failed", "llm_invalid_summary_artifact"
    if heading_count == 1 and len(compact) < 35:
        return "failed", "llm_invalid_summary_artifact"
    return "usable", ""
