"""외부 실행 파일을 신뢰 가능한 위치에서 찾습니다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .paths import application_directory, bin_directory


class ToolError(RuntimeError):
    """필수 외부 도구가 없거나 안전하지 않을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class ToolPaths:
    """다운로드에 사용할 외부 도구의 절대 경로입니다."""

    yt_dlp: Path
    ffmpeg: Path
    ffprobe: Path
    deno: Path | None


def discover_tools() -> ToolPaths:
    """앱의 bin을 우선하고 절대 PATH를 보조 경로로 사용합니다."""
    yt_dlp = find_tool(("yt-dlp.exe", "yt-dlp"))
    ffmpeg_tools = find_tool_pair(
        ("ffmpeg.exe", "ffmpeg"),
        ("ffprobe.exe", "ffprobe"),
    )
    if yt_dlp is None:
        raise ToolError("yt-dlp를 찾을 수 없습니다. 자동 업데이트 상태를 확인해 주세요.")
    if ffmpeg_tools is None:
        raise ToolError("ffmpeg와 ffprobe를 같은 폴더에서 찾을 수 없습니다. bin 폴더 또는 PATH에 함께 설치해 주세요.")
    ffmpeg, ffprobe = ffmpeg_tools
    return ToolPaths(
        yt_dlp=yt_dlp,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        deno=find_tool(("deno.exe", "deno")),
    )


def find_tool(names: tuple[str, ...]) -> Path | None:
    """상대 PATH와 현재 폴더를 제외하고 일반 실행 파일만 찾습니다."""
    for directory in _search_directories():
        for name in names:
            candidate = directory / name
            if _is_regular_executable(candidate):
                return candidate.resolve()
    return None


def find_tool_pair(
    first_names: tuple[str, ...],
    second_names: tuple[str, ...],
) -> tuple[Path, Path] | None:
    """동일한 폴더에 있는 외부 도구 한 쌍만 반환합니다."""
    for directory in _search_directories():
        first = _first_matching_tool(directory, first_names)
        second = _first_matching_tool(directory, second_names)
        if first is not None and second is not None:
            return first, second
    return None


def _first_matching_tool(directory: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = directory / name
        if _is_regular_executable(candidate):
            return candidate.resolve()
    return None


def _search_directories() -> tuple[Path, ...]:
    """프로젝트 bin과 신뢰 가능한 절대 PATH 폴더를 검색 순서대로 반환합니다."""
    directories = [bin_directory().resolve()]

    excluded = {Path.cwd().resolve(), application_directory().resolve()}
    seen = set(directories)
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = raw_entry.strip().strip('"')
        if not entry:
            continue
        directory = Path(entry)
        if not directory.is_absolute():
            continue
        try:
            resolved = directory.resolve()
        except OSError:
            continue
        if resolved in excluded or resolved in seen:
            continue
        seen.add(resolved)
        directories.append(resolved)
    return tuple(directories)


def _is_regular_executable(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size > 0
    except OSError:
        return False
