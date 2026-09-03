"""드래그해서 불러올 수 있는 YTDownloader 작업 파일을 처리합니다."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .validation import ValidationError, format_time, parse_time, validate_file_stem, validate_youtube_url

JOB_FILE_EXTENSION = ".ytdjob"
JOB_FILE_VERSION = 1
MAX_JOB_FILE_BYTES = 1024 * 1024
MAX_JOB_SEGMENTS = 500


class JobFileError(ValueError):
    """사용자가 작업 파일을 수정하면 해결할 수 있는 오류입니다."""


@dataclass(frozen=True)
class JobSegment:
    """작업 파일에 저장되는 하나의 다운로드 구간입니다."""

    title: str
    start: str
    end: str


@dataclass(frozen=True)
class JobDocument:
    """검증과 정규화를 마친 작업 파일 내용입니다."""

    url: str
    segments: tuple[JobSegment, ...]


def create_job_document(url: str, segments: list[tuple[str, str, str]]) -> JobDocument:
    """화면 입력으로부터 검증된 작업 문서를 만듭니다."""
    try:
        normalized_url = validate_youtube_url(url)
    except ValidationError as error:
        raise JobFileError(str(error)) from error

    if len(segments) > MAX_JOB_SEGMENTS:
        raise JobFileError(f"구간은 최대 {MAX_JOB_SEGMENTS}개까지 저장할 수 있습니다.")

    normalized_segments: list[JobSegment] = []
    names: set[str] = set()
    for index, (raw_title, raw_start, raw_end) in enumerate(segments, start=1):
        try:
            title = validate_file_stem(raw_title)
            start_seconds = parse_time(raw_start, "시작 시간")
            end_seconds = parse_time(raw_end, "종료 시간")
        except ValidationError as error:
            raise JobFileError(f"{index}번째 구간: {error}") from error

        if start_seconds is None or end_seconds is None:
            raise JobFileError(f"{index}번째 구간: 시작 시간과 종료 시간을 모두 입력해 주세요.")
        if end_seconds <= start_seconds:
            raise JobFileError(f"{index}번째 구간: 종료 시간은 시작 시간보다 뒤여야 합니다.")

        name_key = title.casefold()
        if name_key in names:
            raise JobFileError(f"{index}번째 구간의 파일 제목이 앞 구간과 중복됩니다.")
        names.add(name_key)
        normalized_segments.append(
            JobSegment(
                title=title,
                start=format_time(start_seconds),
                end=format_time(end_seconds),
            )
        )
    return JobDocument(url=normalized_url, segments=tuple(normalized_segments))


def load_job_file(path: Path) -> JobDocument:
    """로컬 작업 파일 전체를 검증한 뒤 정규화된 문서를 반환합니다."""
    _validate_job_path(path, must_exist=True)
    try:
        file_size = path.stat().st_size
    except OSError as error:
        raise JobFileError(f"작업 파일 정보를 읽을 수 없습니다: {error}") from error
    if file_size > MAX_JOB_FILE_BYTES:
        raise JobFileError("작업 파일은 1MiB보다 작아야 합니다.")

    try:
        text = path.read_text(encoding="utf-8-sig")
        raw_document = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as error:
        raise JobFileError("작업 파일은 UTF-8로 저장되어야 합니다.") from error
    except json.JSONDecodeError as error:
        raise JobFileError(f"JSON 형식이 올바르지 않습니다. {error.lineno}행 {error.colno}열을 확인해 주세요.") from error
    except OSError as error:
        raise JobFileError(f"작업 파일을 읽을 수 없습니다: {error}") from error

    return _document_from_json(raw_document)


def save_job_file(path: Path, document: JobDocument) -> Path:
    """작업 문서를 같은 폴더의 임시 파일을 거쳐 원자적으로 저장합니다."""
    if path.suffix.lower() != JOB_FILE_EXTENSION:
        path = path.with_suffix(JOB_FILE_EXTENSION)
    _validate_job_path(path, must_exist=False)

    payload = {
        "version": JOB_FILE_VERSION,
        "url": document.url,
        "segments": [
            {"title": segment.title, "start": segment.start, "end": segment.end}
            for segment in document.segments
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        raise JobFileError(f"작업 파일을 저장할 수 없습니다: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return path


def _document_from_json(raw_document: Any) -> JobDocument:
    if type(raw_document) is not dict:
        raise JobFileError("작업 파일의 최상위 값은 JSON 객체여야 합니다.")
    expected_keys = {"version", "url", "segments"}
    if set(raw_document) != expected_keys:
        raise JobFileError("작업 파일에는 version, url, segments 항목만 있어야 합니다.")
    if type(raw_document["version"]) is not int or raw_document["version"] != JOB_FILE_VERSION:
        raise JobFileError(f"지원하지 않는 작업 파일 버전입니다. version은 {JOB_FILE_VERSION}이어야 합니다.")
    if type(raw_document["url"]) is not str:
        raise JobFileError("url은 문자열이어야 합니다.")
    if type(raw_document["segments"]) is not list:
        raise JobFileError("segments는 배열이어야 합니다.")

    segments: list[tuple[str, str, str]] = []
    for index, raw_segment in enumerate(raw_document["segments"], start=1):
        if type(raw_segment) is not dict or set(raw_segment) != {"title", "start", "end"}:
            raise JobFileError(f"{index}번째 구간에는 title, start, end 항목만 있어야 합니다.")
        if any(type(raw_segment[key]) is not str for key in ("title", "start", "end")):
            raise JobFileError(f"{index}번째 구간의 title, start, end는 문자열이어야 합니다.")
        segments.append((raw_segment["title"], raw_segment["start"], raw_segment["end"]))
    return create_job_document(raw_document["url"], segments)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JobFileError(f"JSON 항목이 중복되었습니다: {key}")
        result[key] = value
    return result


def _validate_job_path(path: Path, *, must_exist: bool) -> None:
    if path.suffix.lower() != JOB_FILE_EXTENSION:
        raise JobFileError(f"{JOB_FILE_EXTENSION} 확장자의 작업 파일만 사용할 수 있습니다.")
    if must_exist and not path.is_file():
        raise JobFileError("선택한 작업 파일을 찾을 수 없습니다.")
    if not must_exist and not path.parent.is_dir():
        raise JobFileError("작업 파일을 저장할 폴더를 찾을 수 없습니다.")
