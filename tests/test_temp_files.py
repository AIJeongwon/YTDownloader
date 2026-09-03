from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytdownloader.temp_files import (
    SegmentTempDirectory,
    SegmentTempError,
    create_segment_temp_directory,
    remove_segment_temp_directory,
)


class SegmentTempFileTests(unittest.TestCase):
    def test_cleanup_removes_only_owned_segment_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            unrelated_part = output / "다른 다운로드.mp4.part"
            unrelated_part.write_bytes(b"keep")
            temporary = create_segment_temp_directory(output)
            (temporary.path / "현재 구간.mp4.part").write_bytes(b"partial")

            remove_segment_temp_directory(temporary)

            self.assertFalse(temporary.path.exists())
            self.assertEqual(unrelated_part.read_bytes(), b"keep")

    def test_cleanup_refuses_directory_without_matching_owner_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve()
            fake = output / ".ytdownloader-segment-not-owned"
            fake.mkdir()
            protected_file = fake / "보호할 파일.part"
            protected_file.write_bytes(b"keep")
            unowned = SegmentTempDirectory(fake, output, "wrong-owner")

            with self.assertRaises(SegmentTempError):
                remove_segment_temp_directory(unowned)

            self.assertEqual(protected_file.read_bytes(), b"keep")

    def test_cleanup_refuses_tampered_owner_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = create_segment_temp_directory(Path(directory))
            marker = temporary.path / ".ytdownloader-owner"
            marker.write_text("tampered", encoding="ascii")
            protected_file = temporary.path / "보호할 파일.part"
            protected_file.write_bytes(b"keep")

            with self.assertRaises(SegmentTempError):
                remove_segment_temp_directory(temporary)

            self.assertEqual(protected_file.read_bytes(), b"keep")

    def test_cleanup_refuses_changed_output_parent(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            temporary = create_segment_temp_directory(Path(first_directory))
            protected_file = temporary.path / "보호할 파일.part"
            protected_file.write_bytes(b"keep")
            wrong_parent = SegmentTempDirectory(
                temporary.path,
                Path(second_directory).resolve(),
                temporary.owner_token,
            )

            with self.assertRaises(SegmentTempError):
                remove_segment_temp_directory(wrong_parent)

            self.assertEqual(protected_file.read_bytes(), b"keep")

    def test_cleanup_refuses_reparse_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = create_segment_temp_directory(Path(directory))
            protected_file = temporary.path / "보호할 파일.part"
            protected_file.write_bytes(b"keep")

            with (
                patch("ytdownloader.temp_files._is_reparse_point", return_value=True),
                self.assertRaises(SegmentTempError),
            ):
                remove_segment_temp_directory(temporary)

            self.assertEqual(protected_file.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
