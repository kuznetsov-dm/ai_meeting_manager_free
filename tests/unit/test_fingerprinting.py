import sys
import tempfile
import unittest
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
src_root = repo_root / "src"
for path in (repo_root, src_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aimn.core.fingerprinting import compute_source_fingerprint  # noqa: E402


class TestSourceFingerprint(unittest.TestCase):
    def test_fingerprint_stable_on_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_bytes(b"hello world")
            fp1 = compute_source_fingerprint(str(first))
            first.rename(second)
            fp2 = compute_source_fingerprint(str(second))
            self.assertEqual(fp1, fp2)

    def test_fingerprint_changes_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.txt"
            path.write_bytes(b"alpha")
            fp1 = compute_source_fingerprint(str(path))
            path.write_bytes(b"beta")
            fp2 = compute_source_fingerprint(str(path))
            self.assertNotEqual(fp1, fp2)

    def test_fingerprint_uses_tail_for_large_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "large.bin"
            size = 9 * 1024 * 1024
            path.write_bytes(b"a" * size)
            fp1 = compute_source_fingerprint(str(path))
            with path.open("r+b") as handle:
                handle.seek(-1, 2)
                handle.write(b"b")
            fp2 = compute_source_fingerprint(str(path))
            self.assertNotEqual(fp1, fp2)


if __name__ == "__main__":
    unittest.main()
