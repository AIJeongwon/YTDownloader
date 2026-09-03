"""GUI 입력을 외부 명령에 전달하기 전에 검증합니다."""

from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .models import DownloadRequest, MediaKind


class ValidationError(ValueError):
    """사용자가 수정할 수 있는 입력 오류입니다."""


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
_TIME_PART = re.compile(r"^[0-9]+(?:\.[0-9]{1,3})?$")
_MAX_TIME_CHARACTERS = 16
_MAX_TIME_SECONDS = 1000 * 60 * 60
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_FORBIDDEN_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*%\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
    *(f"COM{number}" for number in ("¹", "²", "³")),
    *(f"LPT{number}" for number in ("¹", "²", "³")),
}


def validate_youtube_url(raw_url: str) -> str:
    """허용된 HTTPS YouTube URL을 정리해 반환합니다."""
    value = raw_url.strip()
    if not value:
        raise ValidationError("YouTube 주소를 입력해 주세요.")
    if len(value) > 2048 or any(ord(character) < 32 for character in value):
        raise ValidationError("주소의 형식이 올바르지 않습니다.")

    parsed = urlsplit(value)
    try:
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as error:
        raise ValidationError("주소의 호스트 또는 포트가 올바르지 않습니다.") from error
    if (
        parsed.scheme.lower() != "https"
        or host not in _YOUTUBE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValidationError("HTTPS YouTube 영상 주소만 사용할 수 있습니다.")
    if not _is_youtube_video_path(host, parsed.path, parsed.query):
        raise ValidationError("영상이 지정된 YouTube 주소를 입력해 주세요.")

    netloc = host if port is None else f"{host}:443"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, ""))


def _is_youtube_video_path(host: str, path: str, query: str) -> bool:
    """지원하는 YouTube 단일 영상 URL 형식인지 확인합니다."""
    if host == "youtu.be":
        match = re.fullmatch(r"/([A-Za-z0-9_-]{11})/?", path)
        return match is not None

    if path == "/watch":
        video_ids = parse_qs(query, keep_blank_values=True).get("v", [])
        return len(video_ids) == 1 and _VIDEO_ID.fullmatch(video_ids[0]) is not None

    match = re.fullmatch(r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?", path)
    return match is not None


def parse_time(raw_value: str, field_name: str) -> float | None:
    """빈 값, 숫자 HHMMSS 또는 콜론 형식의 1000시간 미만 시간을 초로 변환합니다."""
    value = raw_value.strip()
    if not value:
        return None
    if len(value) > _MAX_TIME_CHARACTERS:
        raise ValidationError(f"{field_name}은 1000시간 미만으로 입력해 주세요.")

    parts = value.split(":")
    if not 1 <= len(parts) <= 3 or any(not _TIME_PART.fullmatch(part) for part in parts):
        raise ValidationError(f"{field_name}은 초, 분:초 또는 시:분:초 형식이어야 합니다.")
    if any("." in part for part in parts[:-1]):
        raise ValidationError(f"{field_name}의 소수점은 마지막 단위에만 사용할 수 있습니다.")

    if len(parts) == 1:
        whole, separator, fraction = value.partition(".")
        seconds_text = whole[-2:] + (f".{fraction}" if separator else "")
        minutes_text = whole[-4:-2] or "0"
        hours_text = whole[:-4] or "0"
        seconds = (int(hours_text) * 3600) + (int(minutes_text) * 60) + float(seconds_text)
        return _validate_time_range(seconds, field_name)

    numbers = [float(part) for part in parts]
    if len(numbers) >= 2 and numbers[-1] >= 60:
        raise ValidationError(f"{field_name}의 초 값은 60보다 작아야 합니다.")
    if len(numbers) == 3 and numbers[-2] >= 60:
        raise ValidationError(f"{field_name}의 분 값은 60보다 작아야 합니다.")

    seconds = sum(number * (60 ** index) for index, number in enumerate(reversed(numbers)))
    return _validate_time_range(seconds, field_name)


def _validate_time_range(seconds: float, field_name: str) -> float:
    """변환된 시간이 지원 범위에 있는지 확인합니다."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValidationError(f"{field_name}이 올바르지 않습니다.")
    if seconds >= _MAX_TIME_SECONDS:
        raise ValidationError(f"{field_name}은 1000시간 미만으로 입력해 주세요.")
    return seconds


def format_time(seconds: float) -> str:
    """초 단위 시간을 시:분:초 형식으로 정규화합니다."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("시간은 0 이상의 유한한 값이어야 합니다.")
    total_milliseconds = round(seconds * 1000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    second_text = f"{whole_seconds:02d}"
    if milliseconds:
        second_text += f".{milliseconds:03d}".rstrip("0")
    return f"{hours:02d}:{minutes:02d}:{second_text}"


def validate_file_stem(raw_value: str) -> str:
    """사용자가 지정한 파일 제목을 안전한 단일 Windows 파일명으로 검증합니다."""
    value = unicodedata.normalize("NFC", " ".join(raw_value.strip().split()))
    if not value:
        raise ValidationError("각 구간의 파일 제목을 입력해 주세요.")
    if value.endswith((".", " ")) or _FORBIDDEN_FILENAME_CHARACTERS.search(value):
        raise ValidationError("파일 제목에 Windows에서 사용할 수 없는 문자가 있습니다.")
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValidationError("Windows 예약 이름은 파일 제목으로 사용할 수 없습니다.")
    if len(value.encode("utf-8")) > 180:
        raise ValidationError("파일 제목은 UTF-8 기준 180바이트 이하여야 합니다.")
    return value


def build_request(
    *,
    url: str,
    output_directory: str,
    media_kind: MediaKind,
    max_height: int | None,
    start_time: str,
    end_time: str,
    cookie_file: str,
    file_stem: str = "",
) -> DownloadRequest:
    """GUI 문자열을 완전한 다운로드 요청으로 변환합니다."""
    normalized_url = validate_youtube_url(url)
    output = Path(output_directory).expanduser()
    if not output.is_dir():
        raise ValidationError("존재하는 저장 폴더를 선택해 주세요.")
    output = output.resolve()

    if max_height is not None and max_height not in {480, 720, 1080, 1440, 2160}:
        raise ValidationError("지원하지 않는 화질입니다.")

    start = parse_time(start_time, "시작 시간")
    end = parse_time(end_time, "종료 시간")
    if (start is None) != (end is None):
        raise ValidationError("구간 다운로드는 시작 시간과 종료 시간을 모두 입력해 주세요.")
    if start is not None and end is not None and end <= start:
        raise ValidationError("종료 시간은 시작 시간보다 뒤여야 합니다.")

    normalized_stem: str | None = None
    if start is not None:
        normalized_stem = validate_file_stem(file_stem)
        extension = "mp3" if media_kind is MediaKind.AUDIO else "mp4"
        if (output / f"{normalized_stem}.{extension}").exists():
            raise ValidationError(f"이미 같은 이름의 파일이 있습니다: {normalized_stem}.{extension}")
    elif file_stem.strip():
        raise ValidationError("파일 제목 지정은 구간 다운로드에서만 사용합니다.")

    cookie: Path | None = None
    if cookie_file.strip():
        cookie = Path(cookie_file.strip()).expanduser()
        if not cookie.is_file():
            raise ValidationError("선택한 쿠키 파일을 찾을 수 없습니다.")
        if cookie.stat().st_size > 20 * 1024 * 1024:
            raise ValidationError("쿠키 파일은 20MiB보다 작아야 합니다.")
        cookie = cookie.resolve()

    return DownloadRequest(
        url=normalized_url,
        output_directory=output,
        media_kind=media_kind,
        max_height=max_height,
        start_seconds=start,
        end_seconds=end,
        cookie_file=cookie,
        file_stem=normalized_stem,
    )
