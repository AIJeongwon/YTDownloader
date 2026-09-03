from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytdownloader.tools import ToolError, discover_tools


class ToolDiscoveryTests(unittest.TestCase):
    def test_ffmpeg_and_ffprobe_are_required_as_a_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bin_path = Path(directory)
            (bin_path / "yt-dlp.exe").write_bytes(b"yt-dlp")
            (bin_path / "ffmpeg.exe").write_bytes(b"ffmpeg")
            with (
                patch("ytdownloader.tools.bin_directory", return_value=bin_path),
                patch.dict(os.environ, {"PATH": ""}),
                self.assertRaisesRegex(ToolError, "ffmpeg와 ffprobe"),
            ):
                discover_tools()

    def test_matching_ffmpeg_pair_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bin_path = Path(directory)
            for name in ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe"):
                (bin_path / name).write_bytes(name.encode("ascii"))
            with patch("ytdownloader.tools.bin_directory", return_value=bin_path), patch.dict(os.environ, {"PATH": ""}):
                tools = discover_tools()

            self.assertEqual(tools.ffmpeg.parent, tools.ffprobe.parent)
            self.assertEqual(tools.ffprobe.name, "ffprobe.exe")


if __name__ == "__main__":
    unittest.main()
