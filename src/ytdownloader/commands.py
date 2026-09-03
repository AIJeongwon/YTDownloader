"""검증된 요청에서 yt-dlp 인자 목록을 구성합니다."""

from __future__ import annotations

from collections import deque
import math
from pathlib import Path
import re
import time

from .models import DownloadRequest, MediaKind
from .tools import ToolPaths

PROGRESS_PREFIX = "__YTDLP_PROGRESS__:"
POSTPROCESS_PREFIX = "__YTDLP_POSTPROCESS__:"
DONE_PREFIX = "__YTDLP_DONE__:"

_FFMPEG_CLOCK = re.compile(
    r"^(?P<hours>\d+):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d(?:\.\d+)?)$"
)
_FFMPEG_STREAM_QUALITY = re.compile(r"^stream_\d+_\d+_q$")
_FFMPEG_PROGRESS_KEYS = {
    "frame",
    "fps",
    "bitrate",
    "total_size",
    "out_time_us",
    "out_time_ms",
    "out_time",
    "dup_frames",
    "drop_frames",
    "speed",
    "progress",
}


class FFmpegProgressEstimator:
    """초기 FFmpeg 배율과 최근 처리 구간을 조합해 처리 배율을 추정합니다."""

    def __init__(
        self,
        *,
        window_seconds: float = 5.0,
        warmup_samples: int = 3,
    ) -> None:
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("추정 구간은 0보다 큰 유한한 값이어야 합니다.")
        if not isinstance(warmup_samples, int) or isinstance(warmup_samples, bool) or warmup_samples < 1:
            raise ValueError("초기 표본 수는 1 이상의 정수여야 합니다.")
        self._window_seconds = window_seconds
        self._warmup_samples = warmup_samples
        self._samples: deque[tuple[float, float]] = deque()
        self._valid_sample_count = 0

    def reset(self) -> None:
        """새 다운로드를 위해 모든 처리 속도 표본을 비웁니다."""
        self._samples.clear()
        self._valid_sample_count = 0

    def update(
        self,
        fields: dict[str, str],
        *,
        sampled_at: float | None = None,
    ) -> float | None:
        """초기에는 FFmpeg 배율을, 이후에는 최근 구간 처리 배율을 반환합니다."""
        sample_time = time.monotonic() if sampled_at is None else sampled_at
        if not math.isfinite(sample_time):
            return None
        out_time = fields.get("out_time", "")
        if out_time == "N/A":
            if not self._samples:
                self._samples.append((sample_time, 0.0))
            return None
        media_seconds = _ffmpeg_elapsed_seconds(out_time)
        if media_seconds is None:
            return None
        reported_speed = _ffmpeg_speed_multiplier(fields.get("speed", ""))

        if self._samples:
            previous_time, previous_media = self._samples[-1]
            if sample_time < previous_time or media_seconds < previous_media:
                self.reset()
                self._samples.append((sample_time, media_seconds))
            elif sample_time - previous_time >= 0.2:
                self._samples.append((sample_time, media_seconds))
        else:
            self._samples.append((sample_time, media_seconds))

        cutoff = sample_time - self._window_seconds
        while len(self._samples) > 2 and self._samples[1][0] <= cutoff:
            self._samples.popleft()
        self._valid_sample_count += 1
        slice_speed = self._current_speed()
        if self._valid_sample_count <= self._warmup_samples:
            return reported_speed if reported_speed is not None else slice_speed
        return slice_speed if slice_speed is not None else reported_speed

    def _current_speed(self) -> float | None:
        """현재 보관 중인 처음과 마지막 샘플로 처리 배율을 계산합니다."""
        if len(self._samples) < 2:
            return None
        first_time, first_media = self._samples[0]
        last_time, last_media = self._samples[-1]
        elapsed_time = last_time - first_time
        processed_time = last_media - first_media
        if elapsed_time <= 0 or processed_time <= 0:
            return None
        speed = processed_time / elapsed_time
        return speed if math.isfinite(speed) and speed > 0 else None


def build_download_arguments(
    request: DownloadRequest,
    tools: ToolPaths,
    *,
    temp_directory: Path | None = None,
) -> list[str]:
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
        "--downloader-args",
        "ffmpeg:-progress pipe:2 -stats_period 0.5 -nostats",
        "--paths",
        str(request.output_directory),
        "--output",
        f"{request.file_stem}.%(ext)s" if request.file_stem is not None else "%(title).180B [%(id)s].%(ext)s",
        "--progress-template",
        (
            f"download:{PROGRESS_PREFIX}%(progress._percent_str)s|"
            "%(progress.downloaded_bytes)s|"
            "%(progress.total_bytes,progress.total_bytes_estimate)s|"
            "%(progress.speed)s|%(progress.eta)s"
        ),
        "--progress-template",
        f"postprocess:{POSTPROCESS_PREFIX}%(progress.status)s|%(progress.postprocessor)s",
        "--print",
        f"after_move:{DONE_PREFIX}%(filepath)s",
    ]

    if temp_directory is not None:
        arguments.extend(("--paths", f"temp:{temp_directory}"))

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
    """yt-dlp 진행률 한 줄을 백분율과 용량·속도·남은 시간으로 변환합니다."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    fields = line[len(PROGRESS_PREFIX) :].split("|", 4)
    if len(fields) != 5:
        return None

    raw_percent = _number(fields[0].strip().rstrip("%"))
    downloaded_bytes = _number(fields[1])
    total_bytes = _number(fields[2])
    speed = _number(fields[3])
    eta = _number(fields[4])
    if raw_percent is None and downloaded_bytes is not None and total_bytes not in (None, 0):
        raw_percent = downloaded_bytes / total_bytes * 100
    if raw_percent is None:
        return None
    percent = max(0, min(100, round(raw_percent)))

    details = [f"{percent}%"]
    if downloaded_bytes is not None:
        size_text = _format_bytes(downloaded_bytes)
        if total_bytes is not None and total_bytes > 0:
            size_text = f"{size_text} / {_format_bytes(total_bytes)}"
        details.append(size_text)
    if speed is not None and speed > 0:
        details.append(f"{_format_bytes(speed)}/s")
    if eta is not None and eta >= 0:
        details.append(f"남은 시간 {_format_clock(eta)}")
    return percent, " · ".join(details)


def parse_ffmpeg_progress_field(line: str) -> tuple[str, str] | None:
    """FFmpeg의 기계 판독용 진행 출력에서 허용한 필드만 반환합니다."""
    key, separator, value = line.partition("=")
    if not separator or (
        key not in _FFMPEG_PROGRESS_KEYS and _FFMPEG_STREAM_QUALITY.fullmatch(key) is None
    ):
        return None
    normalized = value.strip()
    if len(normalized) > 80 or any(ord(character) < 32 for character in normalized):
        return None
    if key == "progress" and normalized not in {"continue", "end"}:
        return None
    return key, normalized


def build_ffmpeg_progress(
    fields: dict[str, str],
    duration_seconds: float | None,
    *,
    estimated_speed: float | None = None,
) -> tuple[int, str] | None:
    """한 묶음의 FFmpeg 진행 필드에서 경과 시간 기반 진행률을 계산합니다."""
    if duration_seconds is None or not math.isfinite(duration_seconds) or duration_seconds <= 0:
        return None
    out_time = fields.get("out_time", "")
    elapsed = _ffmpeg_elapsed_seconds(out_time)
    if elapsed is None:
        if out_time == "N/A":
            return 0, "구간 데이터를 준비하는 중"
        return None

    percent = max(0, min(100, round(elapsed / duration_seconds * 100)))
    details = [f"{percent}%", f"{_format_clock(elapsed)} / {_format_clock(duration_seconds)}"]
    speed = estimated_speed
    if speed is None or not math.isfinite(speed) or speed <= 0:
        speed = _ffmpeg_speed_multiplier(fields.get("speed", ""))
    if speed is not None and math.isfinite(speed) and speed > 0:
        remaining_seconds = math.ceil(max(0, duration_seconds - elapsed) / speed)
        details.append(f"약 {remaining_seconds}초 남음")
    return percent, " · ".join(details)


def _ffmpeg_elapsed_seconds(out_time: str) -> float | None:
    """FFmpeg의 시:분:초 처리 시간을 초 단위로 변환합니다."""
    time_match = _FFMPEG_CLOCK.fullmatch(out_time)
    if time_match is None:
        return None
    return (
        int(time_match.group("hours")) * 3600
        + int(time_match.group("minutes")) * 60
        + float(time_match.group("seconds"))
    )


def _ffmpeg_speed_multiplier(speed_text: str) -> float | None:
    """FFmpeg의 처리 배율 문자열을 유한한 양수로 변환합니다."""
    speed_match = re.fullmatch(r"(?P<value>\d+(?:\.\d+)?)x", speed_text.strip())
    if speed_match is None:
        return None
    speed = float(speed_match.group("value"))
    return speed if math.isfinite(speed) and speed > 0 else None


def parse_postprocess_line(line: str) -> tuple[str, str] | None:
    """yt-dlp 후처리 상태 표식을 검증해 상태와 처리기 이름을 반환합니다."""
    if not line.startswith(POSTPROCESS_PREFIX):
        return None
    fields = line[len(POSTPROCESS_PREFIX) :].split("|", 1)
    if len(fields) != 2:
        return None
    status = fields[0].strip().lower()
    processor = fields[1].strip()
    if status not in {"started", "processing", "finished"}:
        return None
    if not processor or len(processor) > 80 or any(ord(character) < 32 for character in processor):
        processor = "미디어"
    return status, processor


def _number(value: str) -> float | None:
    """yt-dlp 숫자 필드를 유한한 0 이상의 실수로 변환합니다."""
    try:
        number = float(value.strip())
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _format_bytes(value: float) -> str:
    """바이트 값을 사람이 읽을 수 있는 이진 단위로 표시합니다."""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = value
    unit = units[0]
    for candidate in units:
        unit = candidate
        if size < 1024 or candidate == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{round(size)} {unit}"
    return f"{size:.1f} {unit}"


def _format_clock(seconds: float) -> str:
    """초를 진행 상태용 시:분:초 문자열로 표시합니다."""
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_value = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_value:02d}"
