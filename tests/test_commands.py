from __future__ import annotations

import unittest
from pathlib import Path

from ytdownloader.commands import (
    FFmpegProgressEstimator,
    build_ffmpeg_progress,
    build_download_arguments,
    parse_ffmpeg_progress_field,
    parse_postprocess_line,
    parse_progress_line,
)
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
        progress_templates = [
            arguments[index + 1]
            for index, value in enumerate(arguments)
            if value == "--progress-template"
        ]
        self.assertEqual(len(progress_templates), 2)
        self.assertTrue(any("progress.downloaded_bytes" in value for value in progress_templates))
        self.assertTrue(any(value.startswith("postprocess:") for value in progress_templates))
        downloader_args_index = arguments.index("--downloader-args")
        self.assertEqual(
            arguments[downloader_args_index + 1],
            "ffmpeg:-progress pipe:2 -stats_period 0.5 -nostats",
        )

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
        self.assertEqual(
            parse_progress_line(
                "__YTDLP_PROGRESS__:42.6%|1048576|2097152|2202009.6|3"
            ),
            (43, "43% · 1.0 MiB / 2.0 MiB · 2.1 MiB/s · 남은 시간 00:00:03"),
        )
        self.assertEqual(
            parse_progress_line("__YTDLP_PROGRESS__:NA|512|1024|NA|NA"),
            (50, "50% · 512 B / 1.0 KiB"),
        )
        self.assertEqual(
            parse_progress_line("__YTDLP_PROGRESS__:104%|NA|NA|NA|NA"),
            (100, "100%"),
        )
        self.assertIsNone(parse_progress_line("__YTDLP_PROGRESS__:inf|NA|NA|1|1"))
        self.assertIsNone(parse_progress_line("[download] 50%"))

    def test_ffmpeg_section_progress_uses_machine_readable_fields(self) -> None:
        fields = {
            "out_time": "00:00:01.166667",
            "total_size": "131072",
            "speed": "1.14x",
        }
        self.assertEqual(
            build_ffmpeg_progress(fields, 5),
            (23, "23% · 00:00:01 / 00:00:05 · 약 4초 남음"),
        )
        self.assertEqual(
            build_ffmpeg_progress({"out_time": "N/A"}, 5),
            (0, "구간 데이터를 준비하는 중"),
        )
        self.assertEqual(
            build_ffmpeg_progress({"out_time": "00:00:02.000000", "speed": "N/A"}, 5),
            (40, "40% · 00:00:02 / 00:00:05"),
        )
        self.assertIsNone(build_ffmpeg_progress(fields, None))
        self.assertEqual(
            parse_ffmpeg_progress_field("out_time=00:00:01.166667"),
            ("out_time", "00:00:01.166667"),
        )
        self.assertEqual(
            parse_ffmpeg_progress_field("stream_0_0_q=24.0"),
            ("stream_0_0_q", "24.0"),
        )
        self.assertIsNone(parse_ffmpeg_progress_field("unexpected=value"))

    def test_ffmpeg_speed_estimator_uses_recent_processing_slice(self) -> None:
        estimator = FFmpegProgressEstimator(window_seconds=5.0, warmup_samples=3)

        self.assertEqual(
            estimator.update(
                {"out_time": "00:00:01.000000", "speed": "0.50x"},
                sampled_at=101.0,
            ),
            0.5,
        )
        self.assertEqual(
            estimator.update(
                {"out_time": "00:00:03.000000", "speed": "0.75x"},
                sampled_at=102.0,
            ),
            0.75,
        )
        self.assertEqual(
            estimator.update(
                {"out_time": "00:00:05.000000", "speed": "1.00x"},
                sampled_at=103.0,
            ),
            1.0,
        )
        self.assertAlmostEqual(
            estimator.update(
                {"out_time": "00:00:07.000000", "speed": "9.99x"},
                sampled_at=106.0,
            ),
            1.2,
        )

    def test_ffmpeg_speed_estimator_falls_back_to_first_measured_slice(self) -> None:
        estimator = FFmpegProgressEstimator()

        self.assertIsNone(
            estimator.update({"out_time": "N/A", "speed": "N/A"}, sampled_at=100.0)
        )
        self.assertEqual(
            estimator.update(
                {"out_time": "00:00:02.000000", "speed": "N/A"},
                sampled_at=101.0,
            ),
            2.0,
        )

    def test_ffmpeg_estimated_speed_overrides_missing_reported_speed(self) -> None:
        self.assertEqual(
            build_ffmpeg_progress(
                {"out_time": "00:00:02.000000", "speed": "N/A"},
                10,
                estimated_speed=2.0,
            ),
            (20, "20% · 00:00:02 / 00:00:10 · 약 4초 남음"),
        )

    def test_postprocess_progress_is_validated(self) -> None:
        self.assertEqual(
            parse_postprocess_line("__YTDLP_POSTPROCESS__:started|FFmpegExtractAudio"),
            ("started", "FFmpegExtractAudio"),
        )
        self.assertIsNone(parse_postprocess_line("__YTDLP_POSTPROCESS__:unknown|FFmpeg"))


if __name__ == "__main__":
    unittest.main()
