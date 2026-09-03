"""고정된 배포 자산을 검증하고 안전한 스테이징 폴더를 만듭니다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import urlparse


CHUNK_SIZE = 1024 * 1024
ALLOWED_SOURCE_HOSTS = {
    "codeload.github.com",
    "download.qt.io",
    "github.com",
    "raw.githubusercontent.com",
    "www.python.org",
}


class AssetError(RuntimeError):
    """배포 자산 검증이나 추출에 실패했을 때 발생합니다."""


def sha256_file(path: Path) -> str:
    """파일의 SHA-256을 소문자 16진수로 반환합니다."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, object]:
    """지원하는 스키마의 JSON 자산 목록을 읽습니다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AssetError(f"배포 자산 목록을 읽을 수 없습니다: {error}") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise AssetError("지원하지 않는 배포 자산 목록입니다.")
    return data


def validate_download_record(record: object) -> dict[str, object]:
    """다운로드 항목의 필수 필드와 값 범위를 검증합니다."""
    if not isinstance(record, dict):
        raise AssetError("다운로드 항목은 객체여야 합니다.")
    required = {"filename", "url", "size", "sha256"}
    if not required.issubset(record):
        raise AssetError("다운로드 항목에 필수 필드가 없습니다.")

    filename = record["filename"]
    url = record["url"]
    size = record["size"]
    digest = record["sha256"]
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise AssetError("캐시 파일 이름이 올바르지 않습니다.")
    if not isinstance(url, str):
        raise AssetError("다운로드 주소가 올바르지 않습니다.")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
        raise AssetError(f"허용되지 않은 다운로드 주소입니다: {url}")
    if not isinstance(size, int) or not 0 < size <= 2_000_000_000:
        raise AssetError("다운로드 크기가 허용 범위를 벗어났습니다.")
    if not isinstance(digest, str) or len(digest) != 64:
        raise AssetError("SHA-256 형식이 올바르지 않습니다.")
    try:
        int(digest, 16)
    except ValueError as error:
        raise AssetError("SHA-256 형식이 올바르지 않습니다.") from error
    return record


def ensure_download(record: object, cache_directory: Path) -> Path:
    """캐시를 재검증하거나 공식 주소에서 자산을 내려받습니다."""
    item = validate_download_record(record)
    filename = str(item["filename"])
    expected_size = int(item["size"])
    expected_hash = str(item["sha256"]).lower()
    target = cache_directory / filename
    cache_directory.mkdir(parents=True, exist_ok=True)

    if target.is_file() and target.stat().st_size == expected_size and sha256_file(target) == expected_hash:
        print(f"캐시 검증 완료: {filename}")
        return target

    target.unlink(missing_ok=True)
    request = urllib.request.Request(
        str(item["url"]),
        headers={"User-Agent": "YTDownloader-release-builder/1"},
    )
    temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
    temporary.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as output:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https":
                raise AssetError("다운로드가 안전하지 않은 주소로 이동했습니다.")
            copy_limited(response, output, expected_size)
        if temporary.stat().st_size != expected_size:
            raise AssetError(f"다운로드 크기가 일치하지 않습니다: {filename}")
        if sha256_file(temporary) != expected_hash:
            raise AssetError(f"다운로드 SHA-256이 일치하지 않습니다: {filename}")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    print(f"다운로드 및 검증 완료: {filename}")
    return target


def copy_limited(source: BinaryIO, destination: BinaryIO, maximum_size: int) -> int:
    """최대 크기를 넘지 않는 범위에서 스트림을 복사합니다."""
    total = 0
    while chunk := source.read(CHUNK_SIZE):
        total += len(chunk)
        if total > maximum_size:
            raise AssetError("허용된 크기보다 큰 파일을 거부했습니다.")
        destination.write(chunk)
    return total


def safe_destination(root: Path, relative_name: str) -> Path:
    """상대 경로가 출력 폴더 안에만 위치하도록 확인합니다."""
    relative = PurePosixPath(relative_name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise AssetError(f"안전하지 않은 출력 경로입니다: {relative_name}")
    destination = (root / Path(*relative.parts)).resolve()
    resolved_root = root.resolve()
    if destination != resolved_root and resolved_root not in destination.parents:
        raise AssetError(f"출력 폴더를 벗어나는 경로입니다: {relative_name}")
    return destination


def write_stream_atomic(source: BinaryIO, destination: Path, maximum_size: int) -> None:
    """검증된 스트림을 임시 파일을 거쳐 원자적으로 저장합니다."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open("xb") as output:
            copy_limited(source, output, maximum_size)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    """ZIP 항목이 유닉스 심볼릭 링크인지 확인합니다."""
    mode = info.external_attr >> 16
    return stat.S_IFMT(mode) == stat.S_IFLNK


def checked_zip_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """암호화·심볼릭 링크·상위 경로가 없는 일반 ZIP 항목만 반환합니다."""
    entries: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise AssetError(f"ZIP의 안전하지 않은 경로를 거부했습니다: {info.filename}")
        if info.flag_bits & 0x1:
            raise AssetError("암호화된 ZIP 항목을 거부했습니다.")
        if is_zip_symlink(info):
            raise AssetError("ZIP 심볼릭 링크를 거부했습니다.")
        if not info.is_dir():
            entries.append(info)
    return entries


def extract_file_asset(archive_path: Path, extract: dict[str, object], output: Path) -> list[Path]:
    """검증한 단일 실행 파일을 출력 폴더로 복사합니다."""
    destination = safe_destination(output, str(extract["destination"]))
    maximum_size = int(extract["max_size"])
    with archive_path.open("rb") as source:
        write_stream_atomic(source, destination, maximum_size)
    return [destination]


def extract_zip_member(archive_path: Path, extract: dict[str, object], output: Path) -> list[Path]:
    """ZIP에서 이름이 정확히 일치하는 단일 항목을 추출합니다."""
    source_name = str(extract["source_name"]).casefold()
    destination = safe_destination(output, str(extract["destination"]))
    maximum_size = int(extract["max_size"])
    with zipfile.ZipFile(archive_path) as archive:
        matches = [info for info in checked_zip_entries(archive) if PurePosixPath(info.filename).name.casefold() == source_name]
        if len(matches) != 1:
            raise AssetError(f"ZIP에서 {source_name} 항목 하나를 찾지 못했습니다.")
        info = matches[0]
        if info.file_size > maximum_size:
            raise AssetError(f"ZIP 항목이 허용된 크기보다 큽니다: {info.filename}")
        with archive.open(info) as source:
            write_stream_atomic(source, destination, maximum_size)
    return [destination]


def extract_zip_flat_directory(archive_path: Path, extract: dict[str, object], output: Path) -> list[Path]:
    """ZIP 내부의 지정 폴더에 바로 속한 허용 파일만 추출합니다."""
    source_directory = str(extract["source_directory"]).casefold()
    destination_directory = safe_destination(output, str(extract["destination"]))
    allowed_suffixes = {str(value).casefold() for value in extract["allowed_suffixes"]}
    allowed_executable_names = {
        str(value).casefold() for value in extract.get("allowed_executable_names", [])
    }
    maximum_file_size = int(extract["max_file_size"])
    maximum_total_size = int(extract["max_total_size"])
    selected: dict[str, zipfile.ZipInfo] = {}

    with zipfile.ZipFile(archive_path) as archive:
        for info in checked_zip_entries(archive):
            path = PurePosixPath(info.filename)
            if len(path.parts) < 2 or path.parts[-2].casefold() != source_directory:
                continue
            if path.suffix.casefold() not in allowed_suffixes:
                continue
            filename_key = path.name.casefold()
            if path.suffix.casefold() == ".exe" and allowed_executable_names and filename_key not in allowed_executable_names:
                continue
            if filename_key in selected:
                raise AssetError(f"ZIP에 중복된 파일 이름이 있습니다: {path.name}")
            if info.file_size > maximum_file_size:
                raise AssetError(f"ZIP 항목이 허용된 크기보다 큽니다: {info.filename}")
            selected[filename_key] = info

        required = {str(value).casefold() for value in extract["required_files"]}
        if not required.issubset(selected):
            missing = ", ".join(sorted(required - selected.keys()))
            raise AssetError(f"ZIP에 필요한 실행 파일이 없습니다: {missing}")
        if sum(info.file_size for info in selected.values()) > maximum_total_size:
            raise AssetError("ZIP에서 추출할 전체 크기가 허용 범위를 벗어났습니다.")

        extracted: list[Path] = []
        for key in sorted(selected):
            info = selected[key]
            destination = safe_destination(destination_directory, PurePosixPath(info.filename).name)
            with archive.open(info) as source:
                write_stream_atomic(source, destination, maximum_file_size)
            extracted.append(destination)
    return extracted


def extract_runtime_asset(asset: object, cache_directory: Path, output: Path) -> list[Path]:
    """자산 유형에 맞는 안전한 추출 방법을 적용합니다."""
    if not isinstance(asset, dict) or not isinstance(asset.get("extract"), dict):
        raise AssetError("실행 자산 항목이 올바르지 않습니다.")
    archive_path = ensure_download(asset.get("archive"), cache_directory)
    extract = asset["extract"]
    extract_type = extract.get("type")
    if extract_type == "file":
        return extract_file_asset(archive_path, extract, output)
    if extract_type == "zip_member":
        return extract_zip_member(archive_path, extract, output)
    if extract_type == "zip_flat_directory":
        return extract_zip_flat_directory(archive_path, extract, output)
    raise AssetError(f"지원하지 않는 추출 형식입니다: {extract_type}")


def copy_verified_asset(record: object, cache_directory: Path, destination: Path) -> Path:
    """검증한 다운로드 자산을 지정 위치에 원자적으로 복사합니다."""
    source_path = ensure_download(record, cache_directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as source:
        write_stream_atomic(source, destination, source_path.stat().st_size)
    return destination


def write_file_manifest(root: Path, destination: Path, metadata: dict[str, object]) -> None:
    """스테이징 결과의 상대 경로·크기·해시를 기록합니다."""
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path != destination:
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    document = {**metadata, "files": files}
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def selected_source_assets(manifest: dict[str, object], python_version: str) -> list[dict[str, object]]:
    """현재 패키징 Python 버전과 일치하는 대응 소스만 선택합니다."""
    values = manifest.get("source_assets")
    if not isinstance(values, list):
        raise AssetError("대응 소스 목록이 올바르지 않습니다.")
    selected = []
    for value in values:
        if not isinstance(value, dict):
            raise AssetError("대응 소스 항목이 올바르지 않습니다.")
        required_python = value.get("python_version")
        if required_python is None or required_python == python_version:
            selected.append(value)
    if not any(value.get("python_version") == python_version for value in selected):
        raise AssetError(f"Python {python_version} 대응 소스가 자산 목록에 없습니다.")
    return selected


def generated_source_assets(manifest: dict[str, object]) -> list[dict[str, str]]:
    """릴리스 과정에서 생성해야 하는 대응 소스 파일 정보를 검증합니다."""
    values = manifest.get("generated_source_assets")
    if not isinstance(values, list):
        raise AssetError("생성 대응 소스 목록이 올바르지 않습니다.")
    selected: list[dict[str, str]] = []
    names: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise AssetError("생성 대응 소스 항목이 올바르지 않습니다.")
        if not all(isinstance(value.get(key), str) and value[key] for key in ("id", "title", "filename")):
            raise AssetError("생성 대응 소스 항목의 필수 필드가 올바르지 않습니다.")
        filename = str(value["filename"])
        if Path(filename).name != filename or filename.casefold() in names:
            raise AssetError(f"생성 대응 소스 파일 이름이 올바르지 않습니다: {filename}")
        names.add(filename.casefold())
        selected.append({key: str(value[key]) for key in ("id", "title", "filename")})
    return selected


def validate_build_python(manifest: dict[str, object], python_version: str) -> None:
    """배포 자산과 빌드 Python의 패치 버전까지 일치하는지 확인합니다."""
    expected = manifest.get("build_python_version")
    if not isinstance(expected, str) or expected != python_version:
        raise AssetError(f"배포 빌드는 Python {expected}에서만 허용됩니다. 현재 버전: {python_version}")


def prepare_runtime(manifest: dict[str, object], cache: Path, output: Path, python_version: str) -> None:
    """실행 파일과 전체 라이선스 고지를 스테이징합니다."""
    validate_build_python(manifest, python_version)
    runtime_assets = manifest.get("runtime_assets")
    notices = manifest.get("notices")
    if not isinstance(runtime_assets, list) or not isinstance(notices, list):
        raise AssetError("실행 자산 또는 라이선스 목록이 올바르지 않습니다.")

    versions: dict[str, object] = {}
    for asset in runtime_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("id"), str):
            raise AssetError("실행 자산 식별자가 올바르지 않습니다.")
        extract_runtime_asset(asset, cache, output)
        versions[str(asset["id"])] = asset.get("version")

    license_directory = output / "licenses"
    matching_python_notice = False
    for notice in notices:
        if not isinstance(notice, dict):
            raise AssetError("라이선스 항목이 올바르지 않습니다.")
        required_python = notice.get("python_version")
        if required_python is not None and required_python != python_version:
            continue
        if required_python == python_version:
            matching_python_notice = True
        record = validate_download_record(notice)
        destination = safe_destination(license_directory, str(record["filename"]))
        copy_verified_asset(record, cache, destination)
    if not matching_python_notice:
        raise AssetError(f"Python {python_version} 라이선스 전문이 자산 목록에 없습니다.")

    write_file_manifest(
        output,
        output / "ASSET-MANIFEST.json",
        {"schema_version": 1, "runtime_versions": versions},
    )


def prepare_sources(manifest: dict[str, object], cache: Path, output: Path, python_version: str) -> None:
    """GitHub Release에 첨부할 대응 소스 아카이브를 준비합니다."""
    validate_build_python(manifest, python_version)
    records = selected_source_assets(manifest, python_version)
    for record in records:
        validated = validate_download_record(record)
        destination = safe_destination(output, str(validated["filename"]))
        copy_verified_asset(validated, cache, destination)
    write_file_manifest(
        output,
        output / "SOURCE-ASSETS.json",
        {
            "schema_version": 1,
            "python_version": python_version,
            "generated_files": [item["filename"] for item in generated_source_assets(manifest)],
        },
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YTDownloader 배포 자산을 검증하고 준비합니다.")
    parser.add_argument("mode", choices=("runtime", "sources"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-version", default=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    manifest = load_manifest(arguments.manifest)
    arguments.output.mkdir(parents=True, exist_ok=True)
    if arguments.mode == "runtime":
        prepare_runtime(manifest, arguments.cache, arguments.output, arguments.python_version)
    else:
        prepare_sources(manifest, arguments.cache, arguments.output, arguments.python_version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssetError as error:
        print(f"배포 자산 준비 실패: {error}", file=sys.stderr)
        raise SystemExit(1) from error
