"""검증된 요청에서 yt-dlp 인자 목록을 구성합니다."""

from __future__ import annotations

import math

from .models import DownloadRequest, MediaKind
from .tools import ToolPaths

PROGRESS_PREFIX = "__YTDLP_PROGRESS__:"
DONE_PREFIX = "__YTDLP_DONE__:"


def build_download_arguments(request: DownloadRequest, tools: ToolPaths) -> list[str]:
    """셸 해석이 필요 없는 고정된 다운로드 인자를 반환합니다."""
    arguments = [
        "--ignore-config",
        "--no-config-locations",
        "--no-plugin-dirs",
        "--no-remote-components",
        "--no-exec",
        "--no-playlist",
        "--abort-on-error",
        "--no-overwrites",
        "--no-post-overwrites",
        "--no-update",
        "--encoding",
        "utf-8",
        "--newline",
        "--progress",
        "--color",
        "never",
        "--windows-filenames",
        "--trim-filenames",
        "180",
        "--ffmpeg-location",
        str(tools.ffmpeg.parent),
        "--paths",
        str(request.output_directory),
        "--output",
        f"{request.file_stem}.%(ext)s" if request.file_stem is not None else "%(title).180B [%(id)s].%(ext)s",
        "--progress-template",
        f"download:{PROGRESS_PREFIX}%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--print",
        f"after_move:{DONE_PREFIX}%(filepath)s",
    ]

    if tools.deno is not None:
        arguments.extend(("--js-runtimes", f"deno:{tools.deno}"))
    if request.cookie_file is not None:
        arguments.extend(("--cookies", str(request.cookie_file)))

    if request.media_kind is MediaKind.AUDIO:
        arguments.extend(("--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"))
    else:
        arguments.extend(
            (
                "--format",
                _video_format(request.max_height),
                "--merge-output-format",
                "mp4",
                "--remux-video",
                "mp4",
            )
        )

    if request.start_seconds is not None and request.end_seconds is not None:
        start = _format_seconds(request.start_seconds)
        end = _format_seconds(request.end_seconds)
        arguments.extend(("--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts"))

    arguments.extend(("--", request.url))
    return arguments


def _video_format(max_height: int | None) -> str:
    if max_height is None:
        return "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    return (
        f"bv*[ext=mp4][height<={max_height}]+ba[ext=m4a]/"
        f"b[ext=mp4][height<={max_height}]/"
        f"bv*[height<={max_height}]+ba/b[height<={max_height}]"
    )


def _format_seconds(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def parse_progress_line(line: str) -> tuple[int, str] | None:
    """진행률 표식 한 줄을 백분율과 사용자 표시 문구로 변환합니다."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    fields = line[len(PROGRESS_PREFIX) :].split("|", 2)
    try:
        raw_percent = float(fields[0].strip().rstrip("%"))
        if not math.isfinite(raw_percent):
            return None
        percent = round(raw_percent)
    except (ValueError, OverflowError, IndexError):
        return None
    percent = max(0, min(100, percent))
    speed = fields[1].strip() if len(fields) > 1 else ""
    eta = fields[2].strip() if len(fields) > 2 else ""
    details = " · ".join(part for part in (f"{percent}%", speed, f"남은 시간 {eta}" if eta and eta != "NA" else "") if part and part != "NA")
    return percent, details
