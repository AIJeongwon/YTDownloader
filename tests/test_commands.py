from __future__ import annotations

import unittest
from pathlib import Path

from ytdownloader.commands import build_download_arguments, parse_progress_line
from ytdownloader.models import DownloadRequest, MediaKind
from ytdownloader.tools import ToolPaths


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = ToolPaths(
            Path("C:/tools/yt-dlp.exe"),
            Path("C:/tools/ffmpeg.exe"),
            Path("C:/tools/ffprobe.exe"),
            Path("C:/tools/deno.exe"),
        )

    def test_video_arguments_keep_url_after_option_separator(self) -> None:
        request = DownloadRequest(
            url="https://youtu.be/abcdefghijk?x=--exec",
            output_directory=Path("C:/downloads"),
            media_kind=MediaKind.VIDEO,
            max_height=1080,
        )
        arguments = build_download_arguments(request, self.tools)
        self.assertEqual(arguments[-2], "--")
        self.assertEqual(arguments[-1], request.url)
        self.assertIn("--no-plugin-dirs", arguments)
        self.assertIn("--no-remote-components", arguments)
        self.assertIn("--no-post-overwrites", arguments)
        self.assertIn("--no-update", arguments)
        self.assertIn("deno:C:\\tools\\deno.exe", arguments)
        location_index = arguments.index("--ffmpeg-location")
        self.assertEqual(arguments[location_index + 1], "C:\\tools")
        self.assertIn("bv*[ext=mp4][height<=1080]", arguments[arguments.index("--format") + 1])
        self.assertEqual(arguments[arguments.index("--remux-video") + 1], "mp4")

    def test_audio_and_section_arguments(self) -> None:
        request = DownloadRequest(
            url="https://youtu.be/abcdefghijk",
            output_directory=Path("C:/downloads"),
            media_kind=MediaKind.AUDIO,
            max_height=None,
            start_seconds=5.25,
            end_seconds=70,
            file_stem="핵심 장면",
        )
        arguments = build_download_arguments(request, self.tools)
        self.assertIn("--extract-audio", arguments)
        self.assertNotIn("--remux-video", arguments)
        section_index = arguments.index("--download-sections")
        self.assertEqual(arguments[section_index + 1], "*5.25-70")
        output_index = arguments.index("--output")
        self.assertEqual(arguments[output_index + 1], "핵심 장면.%(ext)s")

    def test_progress_line_is_parsed_and_clamped(self) -> None:
        self.assertEqual(parse_progress_line("__YTDLP_PROGRESS__:42.6%|2.1MiB/s|00:03"), (43, "43% · 2.1MiB/s · 남은 시간 00:03"))
        self.assertEqual(parse_progress_line("__YTDLP_PROGRESS__:104%|NA|NA"), (100, "100%"))
        self.assertIsNone(parse_progress_line("__YTDLP_PROGRESS__:inf|1MiB/s|00:01"))
        self.assertIsNone(parse_progress_line("[download] 50%"))


if __name__ == "__main__":
    unittest.main()
