from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ytdownloader.models import DownloadRequest, MediaKind
from ytdownloader.tools import ToolPaths
from ytdownloader.validation import ValidationError
from ytdownloader.video_info import (
    VideoInfo,
    VideoInfoError,
    build_video_info_arguments,
    format_duration,
    parse_video_info,
    validate_request_durations,
    validate_thumbnail_url,
)


class VideoInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.url = "https://youtu.be/abcdefghijk"
        self.tools = ToolPaths(
            Path("C:/tools/yt-dlp.exe"),
            Path("C:/tools/ffmpeg.exe"),
            Path("C:/tools/ffprobe.exe"),
            Path("C:/tools/deno.exe"),
        )

    def test_info_arguments_only_print_selected_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cookie = Path(directory) / "cookies.txt"
            cookie.write_text("cookie", encoding="utf-8")
            arguments = build_video_info_arguments(self.url, self.tools, cookie)

        self.assertIn("--simulate", arguments)
        self.assertIn("--no-remote-components", arguments)
        self.assertIn("--no-plugin-dirs", arguments)
        self.assertIn("--print", arguments)
        self.assertIn("%(.{id,title,channel,uploader,duration,live_status})+j", arguments)
        self.assertIn(f"deno:{self.tools.deno}", arguments)
        self.assertIn(str(cookie), arguments)
        self.assertEqual(arguments[-2:], ["--", self.url])

    def test_valid_info_is_parsed_and_normalized(self) -> None:
        payload = json.dumps(
            {
                "id": "abcdefghijk",
                "title": "  영상\n제목  ",
                "channel": "테스트 채널",
                "uploader": "대체 채널",
                "duration": 90.4,
                "live_status": "not_live",
            },
            ensure_ascii=False,
        ).encode("utf-8")

        info = parse_video_info(payload, self.url)

        self.assertEqual(info.title, "영상 제목")
        self.assertEqual(info.channel, "테스트 채널")
        self.assertEqual(info.duration_seconds, 90.4)
        self.assertEqual(info.thumbnail_url, "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg")

    def test_info_with_different_video_id_is_rejected(self) -> None:
        payload = json.dumps(
            {
                "id": "zzzzzzzzzzz",
                "title": "다른 영상",
                "channel": "채널",
                "duration": 10,
            }
        ).encode()
        with self.assertRaisesRegex(VideoInfoError, "ID"):
            parse_video_info(payload, self.url)

    def test_section_end_must_not_exceed_video_duration(self) -> None:
        request = DownloadRequest(
            url=self.url,
            output_directory=Path("C:/downloads"),
            media_kind=MediaKind.VIDEO,
            max_height=None,
            start_seconds=100,
            end_seconds=121,
            file_stem="마지막 구간",
        )
        info = VideoInfo(self.url, "abcdefghijk", "영상", "채널", 120, "not_live")
        with self.assertRaisesRegex(ValidationError, "영상 길이 00:02:00"):
            validate_request_durations([request], info)

    def test_live_video_without_duration_skips_range_check(self) -> None:
        request = DownloadRequest(
            url=self.url,
            output_directory=Path("C:/downloads"),
            media_kind=MediaKind.VIDEO,
            max_height=None,
            start_seconds=0,
            end_seconds=300,
            file_stem="실시간 구간",
        )
        info = VideoInfo(self.url, "abcdefghijk", "실시간", "채널", None, "is_live")
        validate_request_durations([request], info)
        self.assertEqual(format_duration(None), "길이 정보 없음")

    def test_thumbnail_url_must_match_video_id(self) -> None:
        valid = "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"
        self.assertTrue(validate_thumbnail_url(valid, "abcdefghijk"))
        self.assertFalse(validate_thumbnail_url(valid + "?redirect=1", "abcdefghijk"))
        self.assertFalse(
            validate_thumbnail_url(
                "https://example.com/vi/abcdefghijk/hqdefault.jpg",
                "abcdefghijk",
            )
        )


if __name__ == "__main__":
    unittest.main()
