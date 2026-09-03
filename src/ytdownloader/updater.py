"""공식 GitHub 릴리스에서 앱 소유 yt-dlp를 안전하게 갱신합니다."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .paths import bin_directory

_API_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
_MAX_API_BYTES = 1_048_576
_MAX_BINARY_BYTES = 100 * 1024 * 1024
_VERSION_PATTERN = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}(?:\.[0-9]+)?$")
_DIGEST_PATTERN = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_OpenUrl = Callable[[Request, float], BinaryIO]


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """시작 시 업데이트 결과입니다."""

    ready: bool
    updated: bool
    message: str
    version: str | None = None


@dataclass(frozen=True, slots=True)
class _ReleaseAsset:
    version: str
    url: str
    size: int
    sha256: str


class UpdateError(RuntimeError):
    """공식 업데이트를 검증하거나 설치하지 못했을 때 발생합니다."""


class YtDlpUpdater:
    """프로젝트 bin의 yt-dlp만 설치하고 갱신합니다."""

    def __init__(
        self,
        *,
        opener: _OpenUrl | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._opener = opener or _open_url
        self._runner = runner or subprocess.run
        self.target = bin_directory() / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")

    def ensure_latest(self) -> UpdateResult:
        """최신 안정판을 검증해 설치하고 기존 정상 파일은 실패 시 보존합니다."""
        if os.environ.get("YTDOWNLOADER_AUTO_UPDATE", "1").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            ready = _is_nonempty_file(self.target)
            return UpdateResult(
                ready=ready,
                updated=False,
                message="yt-dlp 자동 업데이트가 꺼져 있습니다." if ready else "자동 업데이트가 꺼져 있고 yt-dlp가 없습니다.",
            )

        self.target.parent.mkdir(parents=True, exist_ok=True)
        with _update_lock(self.target.parent) as acquired:
            if not acquired:
                ready = _is_nonempty_file(self.target)
                return UpdateResult(
                    ready=ready,
                    updated=False,
                    message="다른 창에서 yt-dlp를 확인하고 있어 이번 확인을 건너뜁니다.",
                )

            had_existing = _is_nonempty_file(self.target)
            if self.target.is_symlink() or (self.target.exists() and not had_existing):
                return UpdateResult(False, False, "bin의 yt-dlp 경로가 안전한 일반 파일이 아닙니다.")
            try:
                release = self._fetch_release()
                if had_existing and _sha256_file(self.target) == release.sha256:
                    return UpdateResult(True, False, f"yt-dlp {release.version} 최신 상태입니다.", release.version)
                self._download_and_install(release)
                verb = "업데이트했습니다" if had_existing else "설치했습니다"
                return UpdateResult(True, True, f"yt-dlp 버전 {release.version}을 {verb}", release.version)
            except (OSError, ValueError, UpdateError, json.JSONDecodeError) as error:
                if _is_nonempty_file(self.target):
                    try:
                        existing_version = self._read_version(self.target)
                    except UpdateError:
                        return UpdateResult(
                            False,
                            False,
                            f"자동 업데이트에 실패했고 기존 yt-dlp도 정상 실행되지 않습니다: {error}",
                        )
                    return UpdateResult(
                        True,
                        False,
                        f"자동 업데이트에 실패해 기존 yt-dlp를 사용합니다: {error}",
                        existing_version,
                    )
                return UpdateResult(False, False, f"yt-dlp를 준비하지 못했습니다: {error}")

    def _fetch_release(self) -> _ReleaseAsset:
        request = _request(_API_URL, accept="application/vnd.github+json")
        with self._opener(request, 15.0) as response:
            payload = json.loads(_read_limited(response, _MAX_API_BYTES).decode("utf-8"))
        return _parse_release(payload)

    def _download_and_install(self, release: _ReleaseAsset) -> None:
        request = _request(release.url, accept="application/octet-stream")
        with self._opener(request, 30.0) as response:
            binary = _read_limited(response, _MAX_BINARY_BYTES)
        if len(binary) != release.size:
            raise UpdateError("다운로드 크기가 공식 릴리스 정보와 다릅니다.")
        if hashlib.sha256(binary).hexdigest() != release.sha256:
            raise UpdateError("다운로드 SHA-256이 공식 릴리스 정보와 다릅니다.")
        _validate_header(binary)

        temporary: Path | None = None
        backup = self.target.with_name(f".{self.target.name}.backup")
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{self.target.name}.",
                suffix=".tmp",
                dir=self.target.parent,
                delete=False,
            ) as file:
                file.write(binary)
                file.flush()
                os.fsync(file.fileno())
                temporary = Path(file.name)
            temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR)
            self._verify_version(temporary, release.version)
            self._replace(temporary, backup, release.sha256)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _verify_version(self, executable: Path, expected: str) -> None:
        version = self._read_version(executable)
        if version != expected:
            raise UpdateError("새 yt-dlp의 실행 버전이 릴리스 정보와 일치하지 않습니다.")

    def _read_version(self, executable: Path) -> str:
        """제한된 인자로 yt-dlp 버전을 읽고 형식을 검증합니다."""
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = self._runner(
                [
                    str(executable),
                    "--ignore-config",
                    "--no-plugin-dirs",
                    "--no-update",
                    "--version",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise UpdateError("yt-dlp를 실행해 버전을 확인할 수 없습니다.") from error
        version = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
        if completed.returncode != 0 or not _VERSION_PATTERN.fullmatch(version):
            raise UpdateError("yt-dlp가 올바른 버전 정보를 반환하지 않았습니다.")
        return version

    def _replace(self, temporary: Path, backup: Path, expected_digest: str) -> None:
        had_existing = self.target.exists()
        backup_created = False
        replacement_installed = False
        try:
            if backup.exists():
                if not _is_nonempty_file(self.target):
                    raise UpdateError(f"이전 업데이트 백업을 먼저 확인해 주세요: {backup}")
                backup.unlink()
            if had_existing:
                os.replace(self.target, backup)
                backup_created = True
            os.replace(temporary, self.target)
            replacement_installed = True
            if _sha256_file(self.target) != expected_digest:
                raise UpdateError("교체된 yt-dlp의 SHA-256이 달라졌습니다.")
        except Exception:
            if replacement_installed and self.target.exists():
                self.target.unlink(missing_ok=True)
            if backup_created and backup.exists():
                try:
                    os.replace(backup, self.target)
                except OSError as restore_error:
                    raise UpdateError(f"기존 yt-dlp 복구에 실패했습니다. 백업 위치: {backup}") from restore_error
            raise
        else:
            backup.unlink(missing_ok=True)


def _parse_release(payload: object) -> _ReleaseAsset:
    if not isinstance(payload, dict):
        raise UpdateError("공식 릴리스 응답 형식이 올바르지 않습니다.")
    version = payload.get("tag_name")
    if (
        not isinstance(version, str)
        or not _VERSION_PATTERN.fullmatch(version)
        or payload.get("draft") is not False
        or payload.get("prerelease") is not False
    ):
        raise UpdateError("공식 안정판 릴리스 정보를 확인할 수 없습니다.")

    expected_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    assets = payload.get("assets")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == expected_name] if isinstance(assets, list) else []
    if len(matches) != 1:
        raise UpdateError("현재 운영체제용 공식 자산을 하나로 확인할 수 없습니다.")
    asset = matches[0]
    url = asset.get("browser_download_url")
    size = asset.get("size")
    digest = asset.get("digest")
    digest_match = _DIGEST_PATTERN.fullmatch(digest) if isinstance(digest, str) else None
    if not isinstance(url, str) or not _is_official_asset_url(url, version, expected_name):
        raise UpdateError("공식 저장소가 아닌 다운로드 주소를 거부했습니다.")
    if asset.get("state") != "uploaded" or not isinstance(size, int) or not 1_000_000 <= size <= _MAX_BINARY_BYTES:
        raise UpdateError("공식 자산의 상태 또는 크기가 올바르지 않습니다.")
    if digest_match is None:
        raise UpdateError("공식 자산에 SHA-256 정보가 없습니다.")
    return _ReleaseAsset(version, url, size, digest_match.group(1).lower())


def _is_official_asset_url(url: str, version: str, name: str) -> bool:
    parsed = urlsplit(url)
    expected_path = f"/yt-dlp/yt-dlp/releases/download/{version}/{name}"
    return parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.path == expected_path and not parsed.query and not parsed.fragment


def _request(url: str, *, accept: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "YTDownloader-GUI/0.1",
            "X-GitHub-Api-Version": "2026-03-10",
        },
        method="GET",
    )


def _open_url(request: Request, timeout: float) -> BinaryIO:
    return urlopen(request, timeout=timeout)


def _read_limited(response: BinaryIO, limit: int) -> bytes:
    content_length = getattr(response, "headers", {}).get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise UpdateError("서버 응답이 허용 크기를 초과합니다.")
        except ValueError as error:
            raise UpdateError("서버 응답 크기 정보가 올바르지 않습니다.") from error
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("서버 응답이 허용 크기를 초과합니다.")
    return data


def _validate_header(binary: bytes) -> None:
    expected = b"MZ" if os.name == "nt" else b"#!"
    if not binary.startswith(expected):
        raise UpdateError("다운로드한 파일의 실행 형식이 올바르지 않습니다.")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size > 0
    except OSError:
        return False


@contextmanager
def _update_lock(directory: Path) -> Iterator[bool]:
    lock_path = directory / ".yt-dlp-update.lock"
    descriptor: int | None = None
    for attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            break
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 600
            except OSError:
                stale = False
            if attempt == 0 and stale:
                lock_path.unlink(missing_ok=True)
                continue
            yield False
            return
    try:
        yield descriptor is not None
    finally:
        if descriptor is not None:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)
