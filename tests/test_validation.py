from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ytdownloader.models import MediaKind
from ytdownloader.validation import ValidationError, build_request, format_time, parse_time, validate_file_stem, validate_youtube_url


class UrlValidationTests(unittest.TestCase):
    def test_supported_urls_are_normalized(self) -> None:
        self.assertEqual(
            validate_youtube_url(" HTTPS://WWW.YOUTUBE.COM/watch?v=abcdefghijk#comment "),
            "https://www.youtube.com/watch?v=abcdefghijk",
        )
        self.assertEqual(
            validate_youtube_url("https://youtu.be/abcdefghijk?t=30"),
            "https://youtu.be/abcdefghijk?t=30",
        )
        for value in (
            "https://youtube.com/shorts/abcdefghijk",
            "https://m.youtube.com/live/abcdefghijk?feature=share",
            "https://www.youtube.com/embed/abcdefghijk",
            "https://music.youtube.com/watch?v=abcdefghijk&list=RDabcdefghijk",
        ):
            with self.subTest(value=value):
                self.assertEqual(validate_youtube_url(value), value)

    def test_untrusted_urls_are_rejected(self) -> None:
        for value in (
            "",
            "http://youtube.com/watch?v=abcdefghijk",
            "https://youtube.com.evil.test/watch?v=abcdefghijk",
            "https://user@youtube.com/watch?v=abcdefghijk",
            "https://youtube.com:444/watch?v=abcdefghijk",
            "https://youtube.com:bad/watch?v=abcdefghijk",
            "https://youtube.com/",
            "https://youtube.com/channel/UC123",
            "https://youtube.com/playlist?list=PL123",
            "https://youtube.com/redirect?q=https://example.com",
            "https://youtube.com/watch?v=short",
            "https://youtube.com/watch?v=abcdefghijk&v=lmnopqrstuv",
            "https://youtu.be/abcdefghijk/extra",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_youtube_url(value)


class TimeValidationTests(unittest.TestCase):
    def test_supported_time_formats(self) -> None:
        self.assertIsNone(parse_time("", "시작"))
        self.assertEqual(parse_time("90.5", "시작"), 90.5)
        self.assertEqual(parse_time("123", "시작"), 83)
        self.assertEqual(parse_time("13033", "시작"), 5433)
        self.assertEqual(parse_time("01:30", "시작"), 90)
        self.assertEqual(parse_time("1:02:03.25", "시작"), 3723.25)

    def test_compact_hhmmss_is_formatted_without_typing_colons(self) -> None:
        self.assertEqual(format_time(parse_time("0", "시작")), "00:00:00")
        self.assertEqual(format_time(parse_time("90", "시작")), "00:01:30")
        self.assertEqual(format_time(parse_time("123", "시작")), "00:01:23")
        self.assertEqual(format_time(parse_time("13033", "시작")), "01:30:33")
        self.assertEqual(format_time(parse_time("3723.25", "시작")), "00:37:23.25")
        self.assertEqual(format_time(parse_time("1:30", "시작")), "00:01:30")

    def test_invalid_time_formats(self) -> None:
        for value in (
            "-1",
            "1:60",
            "1:60:00",
            "1.5:20",
            "1:2:3:4",
            "한시",
            "1000:00:00",
            "9" * 4301,
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_time(value, "시작")

    def test_request_requires_complete_increasing_range(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = dict(
                url="https://youtu.be/abcdefghijk",
                output_directory=directory,
                media_kind=MediaKind.VIDEO,
                max_height=1080,
                cookie_file="",
            )
            with self.assertRaises(ValidationError):
                build_request(**base, start_time="10", end_time="")
            with self.assertRaises(ValidationError):
                build_request(**base, start_time="10", end_time="5")
            request = build_request(**base, start_time="10", end_time="20", file_stem="구간")
            self.assertEqual(request.output_directory, Path(directory).resolve())
            self.assertEqual(request.file_stem, "구간")


class FilenameValidationTests(unittest.TestCase):
    def test_safe_title_is_normalized(self) -> None:
        self.assertEqual(validate_file_stem("  첫 번째   장면  "), "첫 번째 장면")

    def test_unsafe_titles_are_rejected(self) -> None:
        for value in ("", "../탈출", "제목% (id)s", "CON", "COM¹", "LPT³.txt", "끝.", "a" * 181):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_file_stem(value)

    def test_section_requires_a_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = dict(
                url="https://youtu.be/abcdefghijk",
                output_directory=directory,
                media_kind=MediaKind.VIDEO,
                max_height=1080,
                cookie_file="",
            )
            with self.assertRaises(ValidationError):
                build_request(**base, start_time="10", end_time="20")
            request = build_request(**base, start_time="10", end_time="20", file_stem="인트로")
            self.assertEqual(request.file_stem, "인트로")


if __name__ == "__main__":
    unittest.main()
