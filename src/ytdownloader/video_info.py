"""yt-dlp로 안전하게 영상 미리보기 정보를 조회하고 검증합니다."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .models import DownloadRequest
from .tools import ToolPaths
from .validation import ValidationError, validate_youtube_url, youtube_video_id


_INFO_TEMPLATE = "%(.{id,title,channel,uploader,duration,live_status})+j"
_MAX_INFO_BYTES = 64 * 1024
_MAX_DISPLAY_TEXT_BYTES = 1024
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class VideoInfoError(RuntimeError):
    """영상 미리보기 정보를 안전하게 해석할 수 없을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """화면 표시와 구간 범위 검사에 필요한 영상 정보입니다."""

    url: str
    video_id: str
    title: str
    channel: str
    duration_seconds: float | None
    live_status: str | None

    @property
    def thumbnail_url(self) -> str:
        """검증된 영상 ID로 만든 YouTube 썸네일 주소를 반환합니다."""
        return f"https://i.ytimg.com/vi/{self.video_id}/hqdefault.jpg"


def build_video_info_arguments(
    url: str,
    tools: ToolPaths,
    cookie_file: Path | None,
) -> list[str]:
    """영상 파일을 받지 않고 제한된 정보만 JSON으로 출력하는 인자를 만듭니다."""
    normalized_url = validate_youtube_url(url)
    arguments = [
        "--ignore-config",
        "--no-config-locations",
        "--no-plugin-dirs",
        "--no-remote-components",
        "--no-exec",
        "--no-playlist",
        "--abort-on-error",
        "--no-update",
        "--simulate",
        "--no-warnings",
        "--encoding",
        "utf-8",
        "--print",
        _INFO_TEMPLATE,
    ]
    if tools.deno is not None:
        arguments.extend(("--js-runtimes", f"deno:{tools.deno}"))
    if cookie_file is not None:
        arguments.extend(("--cookies", str(cookie_file)))
    arguments.extend(("--", normalized_url))
    return arguments


def parse_video_info(payload: bytes, expected_url: str) -> VideoInfo:
    """yt-dlp의 제한된 JSON 출력을 검증된 영상 정보로 변환합니다."""
    normalized_url = validate_youtube_url(expected_url)
    if not payload or len(payload) > _MAX_INFO_BYTES:
        raise VideoInfoError("영상 정보 응답 크기가 올바르지 않습니다.")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VideoInfoError("영상 정보 응답을 해석할 수 없습니다.") from error
    if not isinstance(document, dict):
        raise VideoInfoError("영상 정보 응답 형식이 올바르지 않습니다.")

    video_id = document.get("id")
    if (
        not isinstance(video_id, str)
        or _VIDEO_ID.fullmatch(video_id) is None
        or video_id != youtube_video_id(normalized_url)
    ):
        raise VideoInfoError("요청한 영상과 응답의 영상 ID가 일치하지 않습니다.")

    title = _display_text(document.get("title"), "영상 제목")
    channel_value = document.get("channel") or document.get("uploader") or "채널 정보 없음"
    channel = _display_text(channel_value, "채널 이름")
    duration_value = document.get("duration")
    if duration_value is None:
        duration = None
    elif (
        isinstance(duration_value, bool)
        or not isinstance(duration_value, (int, float))
        or not math.isfinite(duration_value)
        or duration_value <= 0
    ):
        raise VideoInfoError("영상 길이 정보가 올바르지 않습니다.")
    else:
        duration = float(duration_value)

    live_status_value = document.get("live_status")
    live_status = live_status_value if isinstance(live_status_value, str) else None
    return VideoInfo(normalized_url, video_id, title, channel, duration, live_status)


def _display_text(value: object, field_name: str) -> str:
    """외부 메타데이터 문자열을 한 줄의 제한된 표시 텍스트로 정리합니다."""
    if not isinstance(value, str):
        raise VideoInfoError(f"{field_name} 정보가 올바르지 않습니다.")
    normalized = unicodedata.normalize("NFC", " ".join(value.strip().split()))
    if not normalized or len(normalized.encode("utf-8")) > _MAX_DISPLAY_TEXT_BYTES:
        raise VideoInfoError(f"{field_name} 정보가 올바르지 않습니다.")
    return normalized


def format_duration(seconds: float | None) -> str:
    """영상 길이를 시:분:초로 표시합니다."""
    if seconds is None:
        return "길이 정보 없음"
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_value = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_value:02d}"


def validate_request_durations(requests: list[DownloadRequest], video_info: VideoInfo) -> None:
    """각 구간 종료 시간이 확인된 영상 길이를 넘지 않는지 검사합니다."""
    if video_info.duration_seconds is None:
        return
    for index, request in enumerate(requests, start=1):
        if request.url != video_info.url:
            raise ValidationError("현재 주소와 확인한 영상 정보가 일치하지 않습니다.")
        if request.end_seconds is not None and request.end_seconds > video_info.duration_seconds:
            duration_text = format_duration(video_info.duration_seconds)
            raise ValidationError(
                f"{index}번째 구간의 종료 시간이 영상 길이 {duration_text}을(를) 초과합니다."
            )


def validate_thumbnail_url(url: str, video_id: str) -> bool:
    """썸네일 응답 주소가 요청한 YouTube 정적 이미지인지 확인합니다."""
    parsed = urlsplit(url)
    return (
        _VIDEO_ID.fullmatch(video_id) is not None
        and parsed.scheme == "https"
        and parsed.hostname == "i.ytimg.com"
        and parsed.path == f"/vi/{video_id}/hqdefault.jpg"
        and not parsed.query
        and not parsed.fragment
    )
