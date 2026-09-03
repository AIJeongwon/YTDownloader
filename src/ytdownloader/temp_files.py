"""구간 다운로드 전용 임시 폴더를 안전하게 생성하고 정리합니다."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import shutil
import stat
import tempfile

_SEGMENT_TEMP_PREFIX = ".ytdownloader-segment-"
_OWNER_MARKER_NAME = ".ytdownloader-owner"
_OWNER_TOKEN_BYTES = 32


class SegmentTempError(RuntimeError):
    """구간 임시 폴더를 안전하게 처리할 수 없을 때 발생합니다."""


@dataclass(frozen=True)
class SegmentTempDirectory:
    """앱이 생성한 구간 임시 폴더의 소유권 검증 정보입니다."""

    path: Path
    output_directory: Path
    owner_token: str


def create_segment_temp_directory(output_directory: Path) -> SegmentTempDirectory:
    """저장 폴더 바로 아래에 소유권 표식이 있는 고유 임시 폴더를 만듭니다."""
    try:
        output = output_directory.resolve(strict=True)
    except OSError as error:
        raise SegmentTempError("저장 폴더를 확인할 수 없습니다.") from error
    if not output.is_dir():
        raise SegmentTempError("저장 경로가 폴더가 아닙니다.")

    try:
        temporary = Path(tempfile.mkdtemp(prefix=_SEGMENT_TEMP_PREFIX, dir=output))
        resolved_temporary = temporary.resolve(strict=True)
    except OSError as error:
        raise SegmentTempError("구간 다운로드용 임시 폴더를 만들 수 없습니다.") from error

    if (
        resolved_temporary.parent != output
        or not resolved_temporary.name.startswith(_SEGMENT_TEMP_PREFIX)
        or _is_reparse_point(resolved_temporary)
    ):
        _remove_empty_created_directory(temporary)
        raise SegmentTempError("생성된 구간 임시 폴더의 위치를 검증하지 못했습니다.")

    owner_token = secrets.token_hex(_OWNER_TOKEN_BYTES)
    marker = resolved_temporary / _OWNER_MARKER_NAME
    try:
        with marker.open("x", encoding="ascii", newline="\n") as marker_file:
            marker_file.write(owner_token)
    except OSError as error:
        _remove_empty_created_directory(resolved_temporary)
        raise SegmentTempError("구간 임시 폴더의 소유권 표식을 만들 수 없습니다.") from error

    return SegmentTempDirectory(resolved_temporary, output, owner_token)


def remove_segment_temp_directory(temporary: SegmentTempDirectory) -> None:
    """저장 위치와 소유권이 모두 일치하는 구간 임시 폴더만 삭제합니다."""
    path = temporary.path
    if not os.path.lexists(path):
        return

    try:
        output = temporary.output_directory.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except OSError as error:
        raise SegmentTempError("구간 임시 폴더의 현재 위치를 확인할 수 없습니다.") from error

    if (
        path != resolved_path
        or resolved_path.parent != output
        or not resolved_path.name.startswith(_SEGMENT_TEMP_PREFIX)
        or not resolved_path.is_dir()
        or _is_reparse_point(resolved_path)
    ):
        raise SegmentTempError("구간 임시 폴더의 위치 또는 종류가 달라져 삭제하지 않았습니다.")

    marker = resolved_path / _OWNER_MARKER_NAME
    try:
        marker_stat = marker.lstat()
        if (
            not stat.S_ISREG(marker_stat.st_mode)
            or _is_reparse_point(marker)
            or marker_stat.st_size > _OWNER_TOKEN_BYTES * 2
            or marker.read_text(encoding="ascii") != temporary.owner_token
        ):
            raise SegmentTempError("구간 임시 폴더의 소유권 표식이 달라져 삭제하지 않았습니다.")
    except SegmentTempError:
        raise
    except (OSError, UnicodeError) as error:
        raise SegmentTempError("구간 임시 폴더의 소유권을 확인할 수 없어 삭제하지 않았습니다.") from error

    try:
        shutil.rmtree(resolved_path)
    except OSError as error:
        raise SegmentTempError("구간 임시 파일을 완전히 삭제하지 못했습니다.") from error


def _is_reparse_point(path: Path) -> bool:
    """심볼릭 링크와 Windows 정션을 포함한 재분석 지점인지 확인합니다."""
    try:
        path_stat = path.lstat()
    except OSError:
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(path_stat, "st_file_attributes", 0)
    return path.is_symlink() or bool(reparse_flag and file_attributes & reparse_flag)


def _remove_empty_created_directory(path: Path) -> None:
    """생성 직후 비어 있는 것으로 확인된 폴더만 비재귀적으로 제거합니다."""
    try:
        path.rmdir()
    except OSError:
        return
