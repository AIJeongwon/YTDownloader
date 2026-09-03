"""다운로드 요청 자료형을 정의합니다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class MediaKind(str, Enum):
    """최종 저장 형식입니다."""

    VIDEO = "video"
    AUDIO = "audio"


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    """검증을 마친 단일 다운로드 요청입니다."""

    url: str
    output_directory: Path
    media_kind: MediaKind
    max_height: int | None
    start_seconds: float | None = None
    end_seconds: float | None = None
    cookie_file: Path | None = None
    file_stem: str | None = None
