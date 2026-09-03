"""다운로드와 그 자식 프로세스를 안전하게 종료합니다."""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path


def terminate_process_tree(process_id: int) -> bool:
    """Windows 시스템 도구로 지정한 프로세스와 자식 프로세스를 강제 종료합니다."""
    if os.name != "nt" or process_id <= 0:
        return False

    system_directory = _windows_system_directory()
    if system_directory is None:
        return False
    executable = system_directory / "taskkill.exe"
    try:
        if not executable.is_file() or executable.is_symlink():
            return False
        completed = subprocess.run(
            [str(executable), "/PID", str(process_id), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _windows_system_directory() -> Path | None:
    """환경 변수 대신 Windows API에서 신뢰할 수 있는 시스템 폴더를 얻습니다."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_system_directory = kernel32.GetSystemDirectoryW
        get_system_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        get_system_directory.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32_768)
        length = get_system_directory(buffer, len(buffer))
    except (AttributeError, OSError):
        return None
    if length == 0 or length >= len(buffer):
        return None
    return Path(buffer.value)
