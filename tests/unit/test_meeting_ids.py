import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.meeting_ids import make_meeting_ids, sanitize_name


class TestMeetingIds(unittest.TestCase):
    def test_make_meeting_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "My meeting.mp3"
            path.write_text("data", encoding="utf-8")
            ts = datetime(2026, 1, 17, 10, 45).timestamp()
            os.utime(path, (ts, ts))

            meeting_id, base_name = make_meeting_ids(path)
            expected_stamp = datetime.fromtimestamp(ts, timezone.utc).strftime("%y%m%d-%H%M")

            self.assertTrue(meeting_id.startswith(f"{expected_stamp}_"))
            self.assertEqual(base_name, f"{expected_stamp}_{sanitize_name(path.stem)}")
            self.assertEqual(len(meeting_id.split("_", 1)[1]), 8)

    def test_make_meeting_ids_prefers_filename_stamp_and_strips_prefixes(self) -> None:
        with TemporaryDirectory() as tmp:
            # Processing stamp is first, meeting stamp is second (older); meeting ID should use the older one.
            path = Path(tmp) / "260128-1602_251127_1124_07c9e641_2fd6_443a_a.audio.wav"
            path.write_text("data", encoding="utf-8")
            # Set mtime to a different value to ensure the filename timestamp wins.
            ts = datetime(2026, 2, 9, 13, 0, tzinfo=timezone.utc).timestamp()
            os.utime(path, (ts, ts))

            meeting_id, base_name = make_meeting_ids(path)
            self.assertTrue(meeting_id.startswith("251127-1124_"))
            self.assertEqual(base_name, "251127-1124_07c9e641_2fd6_443a_a")

    def test_make_meeting_ids_does_not_duplicate_stamp_in_short_name(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "251127-1124_251127_1124_demo.mp3"
            path.write_text("data", encoding="utf-8")
            ts = datetime(2026, 2, 9, 13, 0, tzinfo=timezone.utc).timestamp()
            os.utime(path, (ts, ts))

            meeting_id, base_name = make_meeting_ids(path)
            self.assertTrue(meeting_id.startswith("251127-1124_"))
            self.assertEqual(base_name, "251127-1124_demo")

    def test_sanitize_name(self) -> None:
        self.assertEqual(sanitize_name("  foo@bar  "), "foo_bar")
        self.assertEqual(sanitize_name(""), "meeting")

    def test_meeting_id_stable_on_rename(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.mp3"
            second = root / "second.mp3"
            first.write_text("data", encoding="utf-8")
            ts = datetime(2026, 1, 17, 10, 45, tzinfo=timezone.utc).timestamp()
            os.utime(first, (ts, ts))
            meeting_id_1, _ = make_meeting_ids(first)
            first.rename(second)
            os.utime(second, (ts, ts))
            meeting_id_2, _ = make_meeting_ids(second)
            self.assertEqual(meeting_id_1, meeting_id_2)
