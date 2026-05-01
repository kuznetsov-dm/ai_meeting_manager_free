# AI Meeting Manager Responsiveness Backlog

Last updated: 2026-02-28

## Scope

Goal: remove visible UI freezes on tab/tile/panel switching, keep startup/provider checks non-blocking, and prevent hangs on provider startup (including Ollama).

## Consolidated Audit Intake (GEM -> Main Project)

Source reviewed: `apps/ai_meeting_manager_GEM/BACKLOG_PERFORMANCE_UI.md` and related implementation.

Accepted ideas (with adaptation):
- async background workers for heavy UI-bound data loading;
- settings drawer widget cache (avoid rebuilding forms on each tile click);
- plain-text editor path for large artifacts/logs where rich text is not needed.

Rejected as-is:
- direct copy of GEM pipeline/workspace layout changes that reparent private widgets;
- direct copy of GEM async calls without stale-result guards/cancellation semantics;
- "MVC history" claim from GEM backlog is not implemented there (history still uses `QListWidget`).

## Baseline (Current Main Branch)

Latest profiling run:
- `logs/ui_responsiveness_profile_20260228_143353.json` (pre-async baseline)

Key numbers:
- tab switch p95: `14.2ms`;
- history meeting switch p95: `67.9ms`;
- event-loop freezes `>250ms`: `3`;
- startup prewarm: `llm.ollama` server/models/health = `ok`.

Interpretation:
- startup/provider path is much better than before;
- remaining freezes are likely from synchronous history/meeting payload/search paths on the UI thread.

## Backlog

Done:
- [x] Remove synchronous provider model discovery calls from Meetings UI refresh path.
- [x] Add startup background prewarm (health/model checks + auto-start server actions for enabled providers).
- [x] Keep UI responsive during prewarm and avoid modal/blocking waits.
- [x] Make Management tab reload stale-aware on tab switch (`reload_if_stale`).
- [x] Batch text panel meeting-context update path.
- [x] Add slow-path telemetry for key hotspots.
- [x] Cache history meta (`base_name + updated_at`).
- [x] Fix action isolation imports for prewarm subprocess (`plugins.*` resolution).
- [x] Add/maintain offscreen responsiveness profiling script + reports.
- [x] Optimize history tile selected-state update to O(1) on selection change.
- [x] Add shared async UI worker service (`QThreadPool`) with in-flight worker retention to keep callbacks reliable.
- [x] Move `MeetingsTabV2._refresh_history` off the UI thread with request-version stale-result guard.
- [x] Move `MeetingsTabV2._on_meeting_selected` payload load off the UI thread with request-version stale-result guard.
- [x] Move global transcript search execution off the UI thread with request-version stale-result guard.
- [x] Update profiling script to wait for async history population before sampling.
- [x] P1-1: Add settings-form cache in pipeline drawer (reuse stage settings widgets instead of full rebuild each switch).
- [x] P1-2: Replace heavy read-only text views with `QPlainTextEdit` where rich text is not required (non-transcript plain artifact views).
- [x] P1-3: Add throttling/debounce for repeated history refresh triggers during bursty operations.

Planned now (priority order):
- [x] P2-1: Make Management data load optionally async when dataset grows (keep render on UI thread).
- [x] P2-2: Add hard timeout + failure telemetry around provider prewarm actions to prevent long single-plugin stalls.

## Execution Plan

Phase 1 (critical freeze fixes):
1. implement shared UI async worker utility (`QThreadPool` + main-thread callbacks + error callbacks);
2. migrate history refresh and meeting selection loading to async with stale guards;
3. migrate global search execution to async with stale guards.

Phase 2 (interaction smoothness):
1. add stage-settings drawer cache;
2. reduce text widget overhead (`QPlainTextEdit` path);
3. coalesce duplicate history refresh calls.

Phase 3 (hardening and proof):
1. add unit tests for stale-result guard logic and async error paths;
2. rerun `scripts/profile_ui_responsiveness.py` and compare freeze buckets / p95 metrics;
3. update this backlog with before/after metrics and checkboxes.

## Execution Log

- 2026-02-28: merged main-project backlog with GEM audit intake; accepted only safe reusable ideas.
- 2026-02-28: verified latest baseline profile `143353` before next async migration wave.
- 2026-02-28: implemented async worker utility (`src/aimn/ui/services/async_worker.py`) and integrated it into Meetings history refresh, meeting selection load, and global search.
- 2026-02-28: added stale-request guards for history refresh / meeting select / global search to prevent out-of-order UI state writes.
- 2026-02-28: fixed async worker lifecycle by retaining in-flight workers until finish/error callback.
- 2026-02-28: updated profiler for async history initialization and reran:
  - `logs/ui_responsiveness_profile_20260228_144418.json`
  - `logs/ui_responsiveness_profile_20260228_144459.json`
- 2026-02-28: observed after async migration:
  - meeting switch select p95 improved from baseline `67.9ms` -> `55.9-57.4ms`;
  - startup prewarm for `llm.ollama` remains `ok`;
  - freeze bucket `>250ms` still fluctuates (`4-5` in latest runs), so Phase 2 remains required.
- 2026-02-28: Phase 2 implemented:
  - settings drawer stage-tab cache in `PipelinePanelV2` (reuses `SettingsTab` per `stage_id` with stage-signature invalidation);
  - plain text editors switched to `QPlainTextEdit` for non-transcript read-only views;
  - history refresh calls are now debounced/coalesced before async execution.
- 2026-02-28: added tests:
  - `tests/unit/test_pipeline_panel_settings_cache.py` (drawer settings tab reuse);
  - `tests/unit/test_async_worker.py`;
  - `tests/unit/test_meeting_history_controller.py` cache snapshot/restore roundtrip.
- 2026-02-28: latest profile after Phase 2:
  - `logs/ui_responsiveness_profile_20260228_153444.json`;
  - history switch p95 improved to `48.8ms` (from baseline `67.9ms`);
  - event-loop freeze `>250ms`: `3`;
  - `llm.ollama` prewarm/health remains `ok`.
- 2026-02-28: Phase 3 / P2 hardening implemented:
  - `ManagementTabV2.reload` moved to async background loading with request-version guard + debounced reload queue;
  - startup prewarm steps (`server/models/health`) now run with hard step timeouts and timeout telemetry (`timed_out_steps`, elapsed per plugin);
  - model/health checks are skipped for plugins that do not declare corresponding capabilities.
- 2026-02-28: latest profile after P2 hardening:
  - `logs/ui_responsiveness_profile_20260228_155032.json`;
  - event-loop freeze `>250ms`: `0`;
  - startup prewarm `llm.ollama`: `server=ok, models=ok, health=ok`;
  - prewarm log now includes per-plugin elapsed ms and timeout markers when applicable.
