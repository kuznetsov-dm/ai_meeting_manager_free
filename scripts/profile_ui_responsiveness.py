from __future__ import annotations

import json
import os
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from aimn.ui.main_window import MainWindow
from aimn.ui.meetings_tab_v2 import PIPELINE_STAGE_ORDER


@dataclass
class _TimerSeries:
    values_ms: list[float]

    def add(self, value_ms: float) -> None:
        self.values_ms.append(float(max(0.0, value_ms)))

    def as_dict(self) -> dict[str, float | int]:
        if not self.values_ms:
            return {
                "count": 0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "max_ms": 0.0,
            }
        data = sorted(self.values_ms)
        p50 = data[min(len(data) - 1, int(round((len(data) - 1) * 0.50)))]
        p95 = data[min(len(data) - 1, int(round((len(data) - 1) * 0.95)))]
        return {
            "count": len(data),
            "avg_ms": round(statistics.fmean(data), 3),
            "p50_ms": round(float(p50), 3),
            "p95_ms": round(float(p95), 3),
            "max_ms": round(float(data[-1]), 3),
        }


class _LoopJitterProbe:
    def __init__(self, parent, *, interval_ms: int = 16) -> None:
        self._interval_ms = max(1, int(interval_ms))
        self._timer = QTimer(parent)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._on_tick)
        self._last_ts: float | None = None
        self.jitter_ms = _TimerSeries(values_ms=[])
        self.gap_ms = _TimerSeries(values_ms=[])
        self.freeze_over_100ms = 0
        self.freeze_over_250ms = 0

    def start(self) -> None:
        self._last_ts = time.perf_counter()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _on_tick(self) -> None:
        now = time.perf_counter()
        if self._last_ts is None:
            self._last_ts = now
            return
        delta_ms = (now - self._last_ts) * 1000.0
        self._last_ts = now
        self.gap_ms.add(delta_ms)
        jitter = max(0.0, delta_ms - float(self._interval_ms))
        self.jitter_ms.add(jitter)
        if delta_ms >= 100.0:
            self.freeze_over_100ms += 1
        if delta_ms >= 250.0:
            self.freeze_over_250ms += 1

    def as_dict(self) -> dict[str, object]:
        return {
            "interval_ms": self._interval_ms,
            "gap": self.gap_ms.as_dict(),
            "jitter": self.jitter_ms.as_dict(),
            "freeze_over_100ms": self.freeze_over_100ms,
            "freeze_over_250ms": self.freeze_over_250ms,
        }


def _run_event_loop(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(max(1, int(ms)), loop.quit)
    loop.exec()


def _benchmark_repeated(iterations: int, fn: Callable[[], None]) -> _TimerSeries:
    samples = _TimerSeries(values_ms=[])
    for _ in range(max(1, int(iterations))):
        started = time.perf_counter()
        fn()
        QApplication.processEvents()
        samples.add((time.perf_counter() - started) * 1000.0)
    return samples


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    QApplication.processEvents()

    meetings_tab = window._meetings_tab  # noqa: SLF001
    text_panel = meetings_tab._text_panel  # noqa: SLF001

    # Give startup timers a chance to fire (startup prewarm starts here).
    _run_event_loop(1800)

    # Gather sample payload from the largest available meeting to stress update paths.
    payload_sample: dict[str, object] = {}
    try:
        meetings_tab._refresh_history()  # noqa: SLF001
    except Exception:
        pass
    # History refresh can be async; give it time to populate the cache before sampling.
    attempts = 0
    while attempts < 24 and not list(getattr(meetings_tab, "_all_meetings", []) or []):  # noqa: SLF001
        _run_event_loop(200)
        attempts += 1
    meeting_bases = [
        str(getattr(item, "base_name", "") or "").strip()
        for item in list(getattr(meetings_tab, "_all_meetings", []) or [])
        if str(getattr(item, "base_name", "") or "").strip()
    ]
    best_count = -1
    for base in meeting_bases[:12]:
        try:
            payload = meetings_tab._meeting_selection_controller.load_selection_payload(  # noqa: SLF001
                base_name=base,
                load_meeting=lambda b: meetings_tab._artifact_service.load_meeting(b),  # noqa: SLF001
                list_artifacts=lambda meeting, include_internal: meetings_tab._artifact_service.list_artifacts(  # noqa: SLF001
                    meeting, include_internal=include_internal
                ),
                all_meetings=list(meetings_tab._all_meetings),  # noqa: SLF001
                stage_order=list(PIPELINE_STAGE_ORDER),
            )
        except Exception:
            continue
        artifacts = list(payload.get("active_artifacts", []) or [])
        if len(artifacts) > best_count:
            payload_sample = dict(payload)
            best_count = len(artifacts)
    if not payload_sample:
        payload_sample = {
            "active_artifacts": [],
            "segments_relpaths": {},
            "pinned_aliases": {},
            "active_aliases": {},
            "preferred_kind": "",
        }

    artifacts = list(payload_sample.get("active_artifacts", []) or [])
    segments_relpaths = dict(payload_sample.get("segments_relpaths", {}) or {})
    pinned_aliases = dict(payload_sample.get("pinned_aliases", {}) or {})
    active_aliases = dict(payload_sample.get("active_aliases", {}) or {})
    preferred_kind = str(payload_sample.get("preferred_kind", "") or "").strip()

    # Microbenchmark: old sequential updates vs new batched update path.
    old_samples = _benchmark_repeated(
        18,
        lambda: (
            text_panel.set_segments_relpaths(segments_relpaths),
            text_panel.set_pinned_aliases(pinned_aliases),
            text_panel.set_active_aliases(active_aliases),
            text_panel.set_artifacts(artifacts, preferred_kind=preferred_kind),
        ),
    )
    new_samples = _benchmark_repeated(
        18,
        lambda: text_panel.set_meeting_context(
            artifacts=artifacts,
            segments_relpaths=segments_relpaths,
            pinned_aliases=pinned_aliases,
            active_aliases=active_aliases,
            preferred_kind=preferred_kind,
        ),
    )

    # Runtime scenario: rapid tab switches while startup prewarm is active/finishing.
    jitter = _LoopJitterProbe(window, interval_ms=16)
    jitter.start()

    tab_switch_costs = _TimerSeries(values_ms=[])
    sequence = [1, 0, 2, 0, 3, 0]
    state = {"i": 0}

    def _switch_once() -> None:
        idx = sequence[state["i"] % len(sequence)]
        state["i"] += 1
        started = time.perf_counter()
        window._tabs.setCurrentIndex(idx)  # noqa: SLF001
        tab_switch_costs.add((time.perf_counter() - started) * 1000.0)

    switch_timer = QTimer(window)
    switch_timer.setInterval(65)
    switch_timer.timeout.connect(_switch_once)
    switch_timer.start()

    # Meeting switch churn (if enough history exists).
    meeting_switch_costs = _TimerSeries(values_ms=[])
    base_cycle = [base for base in meeting_bases if base]
    cycle_state = {"i": 0}

    def _switch_meeting_once() -> None:
        if len(base_cycle) < 2:
            return
        base = base_cycle[cycle_state["i"] % len(base_cycle)]
        cycle_state["i"] += 1
        started = time.perf_counter()
        meetings_tab._history_panel.select_by_base_name(base)  # noqa: SLF001
        meeting_switch_costs.add((time.perf_counter() - started) * 1000.0)

    meeting_timer = QTimer(window)
    meeting_timer.setInterval(220)
    meeting_timer.timeout.connect(_switch_meeting_once)
    meeting_timer.start()

    _run_event_loop(12500)

    switch_timer.stop()
    meeting_timer.stop()
    jitter.stop()

    # Wait for startup prewarm completion to capture final provider statuses.
    prewarm_wait_ms = 0
    max_prewarm_wait_ms = 50000
    while prewarm_wait_ms < max_prewarm_wait_ms:
        with meetings_tab._startup_prewarm_lock:  # noqa: SLF001
            running = bool(meetings_tab._startup_prewarm_job.get("running", False))  # noqa: SLF001
            done = bool(meetings_tab._startup_prewarm_job.get("done", False))  # noqa: SLF001
        if done or not running:
            break
        _run_event_loop(1000)
        prewarm_wait_ms += 1000

    with meetings_tab._startup_prewarm_lock:  # noqa: SLF001
        prewarm_snapshot = {
            "running": bool(meetings_tab._startup_prewarm_job.get("running", False)),  # noqa: SLF001
            "done": bool(meetings_tab._startup_prewarm_job.get("done", False)),  # noqa: SLF001
            "error": str(meetings_tab._startup_prewarm_job.get("error", "") or "").strip(),  # noqa: SLF001
            "results": list(meetings_tab._startup_prewarm_job.get("results", []) or []),  # noqa: SLF001
            "waited_ms": prewarm_wait_ms,
        }

    all_logs = [entry.message for entry in meetings_tab._log_service.get_all_logs()]  # noqa: SLF001
    perf_logs = [msg for msg in all_logs if "slow_ui_path" in msg or "[perf]" in msg or "Prewarm " in msg]

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).resolve().parents[1] / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_json = out_dir / f"ui_responsiveness_profile_{timestamp}.json"
    report_md = out_dir / f"ui_responsiveness_profile_{timestamp}.md"

    old_stats = old_samples.as_dict()
    new_stats = new_samples.as_dict()
    delta_avg = round(float(old_stats["avg_ms"]) - float(new_stats["avg_ms"]), 3)
    speedup = 0.0
    if float(new_stats["avg_ms"]) > 0:
        speedup = round(float(old_stats["avg_ms"]) / float(new_stats["avg_ms"]), 3)

    report = {
        "timestamp": timestamp,
        "qt_platform": os.environ.get("QT_QPA_PLATFORM", ""),
        "sample_meeting_count": len(meeting_bases),
        "sample_artifacts_count": len(artifacts),
        "meeting_context_update_old_path": old_stats,
        "meeting_context_update_new_path": new_stats,
        "meeting_context_delta_avg_ms": delta_avg,
        "meeting_context_speedup_x": speedup,
        "tab_switch_set_index_cost": tab_switch_costs.as_dict(),
        "meeting_switch_select_cost": meeting_switch_costs.as_dict(),
        "event_loop": jitter.as_dict(),
        "startup_prewarm": prewarm_snapshot,
        "perf_log_tail": perf_logs[-120:],
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# UI Responsiveness Profile",
        "",
        f"- Timestamp: `{timestamp}`",
        f"- QT platform: `{report['qt_platform']}`",
        f"- Meetings discovered: `{len(meeting_bases)}`",
        f"- Artifact sample size: `{len(artifacts)}`",
        "",
        "## Meeting Context (before/after)",
        f"- Old avg: `{old_stats['avg_ms']} ms`",
        f"- New avg: `{new_stats['avg_ms']} ms`",
        f"- Delta avg: `{delta_avg} ms`",
        f"- Speedup: `{speedup}x`",
        "",
        "## UI Runtime",
        f"- Tab switch setCurrentIndex p95: `{report['tab_switch_set_index_cost']['p95_ms']} ms`",
        f"- Event-loop max gap: `{report['event_loop']['gap']['max_ms']} ms`",
        f"- Event-loop freezes >100ms: `{report['event_loop']['freeze_over_100ms']}`",
        f"- Event-loop freezes >250ms: `{report['event_loop']['freeze_over_250ms']}`",
        "",
        "## Startup Prewarm",
        f"- done: `{prewarm_snapshot['done']}`",
        f"- running: `{prewarm_snapshot['running']}`",
        f"- error: `{prewarm_snapshot['error']}`",
        f"- rows: `{len(prewarm_snapshot['results'])}`",
        "",
        f"JSON report: `{report_json}`",
    ]
    report_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(str(report_json))
    print(str(report_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
