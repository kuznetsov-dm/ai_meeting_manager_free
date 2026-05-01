from __future__ import annotations

import argparse
from pathlib import Path

from aimn.core.index_service import create_default_index_service
from aimn.core.meeting_store import FileMeetingStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild index from meeting passports.")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--meeting-id", default=None)
    parser.add_argument("--base-name", default=None)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output_dir) if args.output_dir else repo_root / "output"
    store = FileMeetingStore(output_dir)
    index_service = create_default_index_service(output_dir)

    meeting_id = args.meeting_id
    if args.base_name:
        meeting = store.load(args.base_name)
        meeting_id = meeting.meeting_id

    index_service.rebuild(meeting_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
