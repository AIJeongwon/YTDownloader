"""애플리케이션이 사용하는 기준 경로를 제공합니다."""

from __future__ import annotations

import sys
from pathlib import Path


def application_directory() -> Path:
    """개발 소스 또는 패키징된 실행 파일의 기준 폴더를 반환합니다."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bin_directory() -> Path:
    """앱이 직접 관리하는 외부 도구 폴더를 반환합니다."""
    return application_directory() / "bin"
