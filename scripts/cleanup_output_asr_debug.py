from __future__ import annotations

import argparse
from pathlib import Path

from aimn.core.meeting_store import FileMeetingStore


ASR_DEBUG_KINDS = {"asr_segments_json", "asr_diagnostics_json"}


def _desired_status_from_last_run(meeting) -> str:
    runs = getattr(meeting, "pipeline_runs", []) or []
    if not runs:
        return ""
    last = runs[-1]
    finished_at = str(getattr(last, "finished_at", "") or "").strip()
    if not finished_at:
        return ""
    result = str(getattr(last, "result", "") or "").strip().lower()
    if result in {"success", "partial_success"}:
        return "completed"
    if result == "failed":
        return "failed"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup legacy ASR debug artifacts in output/")
    parser.add_argument("--output-dir", default="output", help="Output directory (default: ./output)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing/deleting")
    args = parser.parse_args()

    output_dir = Path(str(args.output_dir)).expanduser().resolve()
    store = FileMeetingStore(output_dir)

    changed_meetings = 0
    removed_refs = 0
    deleted_files = 0

    for base_name in list(store.list_meetings()):
        meeting = store.load(base_name)
        changed = False

        desired = _desired_status_from_last_run(meeting)
        current = str(getattr(meeting, "processing_status", "") or "").strip().lower()
        if desired and current == "running":
            if args.dry_run:
                print(f"[DRY] status {base_name}: running -> {desired}")
            else:
                setattr(meeting, "processing_status", desired)
                if desired != "failed":
                    setattr(meeting, "processing_error", "")
            changed = True

        nodes = getattr(meeting, "nodes", {}) or {}
        if isinstance(nodes, dict):
            for _alias, node in nodes.items():
                artifacts = list(getattr(node, "artifacts", []) or [])
                kept = []
                for art in artifacts:
                    kind = str(getattr(art, "kind", "") or "")
                    if kind in ASR_DEBUG_KINDS:
                        relpath = str(getattr(art, "path", "") or "")
                        removed_refs += 1
                        if relpath:
                            target = output_dir / relpath
                            if target.exists():
                                if args.dry_run:
                                    print(f"[DRY] delete {target}")
                                else:
                                    try:
                                        target.unlink()
                                        deleted_files += 1
                                    except Exception:
                                        pass
                        changed = True
                        continue
                    kept.append(art)
                if len(kept) != len(artifacts):
                    node.artifacts = kept

        if changed:
            changed_meetings += 1
            if not args.dry_run:
                store.save(meeting)

    print(
        f"Done. meetings_changed={changed_meetings} artifact_refs_removed={removed_refs} files_deleted={deleted_files}"
        + (" (dry-run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

