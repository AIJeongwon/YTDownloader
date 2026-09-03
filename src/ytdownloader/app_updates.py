"""공식 GitHub 릴리스에서 YTDownloader 새 버전을 확인합니다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import BinaryIO, Callable
from urllib.request import Request, urlopen


_API_URL = "https://api.github.com/repos/AIJeongwon/YTDownloader/releases/latest"
_RELEASE_URL_PREFIX = "https://github.com/AIJeongwon/YTDownloader/releases/tag/"
_DOWNLOAD_URL_PREFIX = "https://github.com/AIJeongwon/YTDownloader/releases/download/"
_INSTALLER_NAME = "YTDownloader-Setup.exe"
_MAX_API_BYTES = 1024 * 1024
_MAX_INSTALLER_BYTES = 2_000_000_000
_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_OpenUrl = Callable[[Request, float], BinaryIO]


class AppUpdateError(RuntimeError):
    """앱 릴리스 정보를 안전하게 확인하지 못했을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class AppRelease:
    """검증을 마친 최신 YTDownloader 릴리스입니다."""

    version: str
    page_url: str


@dataclass(frozen=True, slots=True)
class AppUpdateCheckResult:
    """백그라운드 앱 업데이트 확인 결과입니다."""

    release: AppRelease | None
    error: str | None = None


def check_for_app_update(
    current_version: str,
    *,
    opener: _OpenUrl | None = None,
) -> AppRelease | None:
    """현재보다 새로운 공식 정식 릴리스가 있으면 반환합니다."""
    current = _parse_version(current_version)
    open_url = opener or _open_url
    request = Request(
        _API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"YTDownloader-GUI/{current_version}",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        method="GET",
    )
    try:
        with open_url(request, 15.0) as response:
            payload = json.loads(_read_limited(response).decode("utf-8"))
        release = _parse_release(payload)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, AppUpdateError) as error:
        if isinstance(error, AppUpdateError):
            raise
        raise AppUpdateError("GitHub 최신 릴리스 정보를 확인하지 못했습니다.") from error
    return release if _parse_version(release.version) > current else None


def _parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise AppUpdateError(f"지원하지 않는 앱 버전 형식입니다: {value}")
    return tuple(int(part) for part in match.groups())


def _parse_release(payload: object) -> AppRelease:
    if not isinstance(payload, dict):
        raise AppUpdateError("공식 릴리스 응답 형식이 올바르지 않습니다.")
    tag = payload.get("tag_name")
    if (
        not isinstance(tag, str)
        or not tag.startswith("v")
        or _VERSION_PATTERN.fullmatch(tag[1:]) is None
        or payload.get("draft") is not False
        or payload.get("prerelease") is not False
    ):
        raise AppUpdateError("공식 정식 릴리스 정보를 확인할 수 없습니다.")

    page_url = f"{_RELEASE_URL_PREFIX}{tag}"
    if payload.get("html_url") != page_url:
        raise AppUpdateError("공식 저장소가 아닌 릴리스 주소를 거부했습니다.")

    assets = payload.get("assets")
    matches = (
        [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == _INSTALLER_NAME]
        if isinstance(assets, list)
        else []
    )
    if len(matches) != 1:
        raise AppUpdateError("Windows 설치 파일을 하나로 확인할 수 없습니다.")
    asset = matches[0]
    expected_download_url = f"{_DOWNLOAD_URL_PREFIX}{tag}/{_INSTALLER_NAME}"
    size = asset.get("size")
    digest = asset.get("digest")
    if (
        asset.get("state") != "uploaded"
        or asset.get("browser_download_url") != expected_download_url
        or not isinstance(size, int)
        or not 1_000_000 <= size <= _MAX_INSTALLER_BYTES
        or not isinstance(digest, str)
        or _DIGEST_PATTERN.fullmatch(digest) is None
    ):
        raise AppUpdateError("Windows 설치 파일의 상태 또는 무결성 정보가 올바르지 않습니다.")
    return AppRelease(version=tag[1:], page_url=page_url)


def _read_limited(response: BinaryIO) -> bytes:
    content_length = getattr(response, "headers", {}).get("Content-Length")
    if content_length is not None:
        try:
            if not 0 <= int(content_length) <= _MAX_API_BYTES:
                raise AppUpdateError("GitHub 응답이 허용 크기를 초과합니다.")
        except ValueError as error:
            raise AppUpdateError("GitHub 응답 크기 정보가 올바르지 않습니다.") from error
    data = response.read(_MAX_API_BYTES + 1)
    if len(data) > _MAX_API_BYTES:
        raise AppUpdateError("GitHub 응답이 허용 크기를 초과합니다.")
    return data


def _open_url(request: Request, timeout: float) -> BinaryIO:
    return urlopen(request, timeout=timeout)
