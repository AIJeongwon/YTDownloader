"""프로젝트 버전과 배포본에 넣을 메타데이터 파일을 생성합니다."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

try:
    from .prepare_assets import (
        AssetError,
        load_manifest,
        reusable_source_assets,
        selected_source_assets,
        validate_reusable_source_mapping,
    )
except ImportError:
    from prepare_assets import (
        AssetError,
        load_manifest,
        reusable_source_assets,
        selected_source_assets,
        validate_reusable_source_mapping,
    )


VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.([0-9]+))?$")


def project_version(project_file: Path) -> str:
    """pyproject.toml에서 숫자 버전을 읽고 형식을 확인합니다."""
    try:
        document = tomllib.loads(project_file.read_text(encoding="utf-8"))
        version = document["project"]["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise AssetError(f"프로젝트 버전을 읽을 수 없습니다: {error}") from error
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise AssetError("프로젝트 버전은 숫자 3~4개로 구성해야 합니다.")
    return version


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """Windows 파일 버전에 사용할 네 개의 숫자를 반환합니다."""
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise AssetError("Windows 파일 버전으로 변환할 수 없습니다.")
    values = [int(value) if value is not None else 0 for value in match.groups()]
    if any(value > 65535 for value in values):
        raise AssetError("Windows 파일 버전의 각 숫자는 65535 이하여야 합니다.")
    return values[0], values[1], values[2], values[3]


def write_version_file(output: Path, version: str, publisher: str) -> None:
    """PyInstaller가 사용할 Windows 실행 파일 버전 정보를 씁니다."""
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", publisher) is None:
        raise AssetError("게시자 이름은 올바른 GitHub 사용자 이름이어야 합니다.")
    numbers = version_tuple(version)
    comma_version = ", ".join(str(value) for value in numbers)
    dotted_version = ".".join(str(value) for value in numbers)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({comma_version}),
    prodvers=({comma_version}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '041204B0',
        [StringStruct('CompanyName', '{publisher}'),
         StringStruct('FileDescription', 'YTDownloader'),
         StringStruct('FileVersion', '{dotted_version}'),
         StringStruct('InternalName', 'YTDownloader'),
         StringStruct('LegalCopyright', 'Copyright (c) 2026 {publisher}'),
         StringStruct('OriginalFilename', 'YTDownloader.exe'),
         StringStruct('ProductName', 'YTDownloader'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])
  ]
)
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def normalize_repository_url(value: str) -> str:
    """GitHub 저장소의 HTTPS 주소만 허용하고 뒤쪽 슬래시를 제거합니다."""
    normalized = value.rstrip("/")
    if re.fullmatch(r"https://github\.com/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+", normalized) is None:
        raise AssetError("GitHub 저장소 주소가 올바르지 않습니다.")
    return normalized


def write_source_offer(
    output: Path,
    manifest_path: Path,
    repository_url: str,
    version: str,
    python_version: str,
) -> None:
    """설치본과 정확히 대응하는 소스 다운로드 안내를 작성합니다."""
    repository_url = normalize_repository_url(repository_url)
    manifest = load_manifest(manifest_path)
    records = selected_source_assets(manifest, python_version)
    reusable_records = reusable_source_assets(manifest)
    validate_reusable_source_mapping(manifest)
    release_url = f"{repository_url}/releases/download/v{version}"
    lines = [
        "YTDownloader 소스 코드 및 제3자 소프트웨어 대응 소스",
        "",
        f"이 설치본의 YTDownloader 소스: {repository_url}/tree/v{version}",
        f"릴리스 페이지: {repository_url}/releases/tag/v{version}",
        "",
        "같은 릴리스에서 다음 대응 소스 아카이브를 다운로드할 수 있습니다.",
    ]
    for record in records:
        lines.append(f"- {record['title']}: {release_url}/{record['filename']}")
    if reusable_records:
        lines.extend(
            [
                "",
                "용량이 큰 다음 대응 소스는 검증된 기존 릴리스 자산을 재사용합니다.",
            ]
        )
        for record in reusable_records:
            lines.append(f"- {record['title']}: {record['url']}")
            lines.append(f"  SHA-256: {str(record['sha256']).lower()}")
    lines.extend(
        [
            "",
            "같은 릴리스 파일의 SHA-256은 SHA256SUMS.txt에서 확인할 수 있습니다.",
            "재사용 대응 소스의 SHA-256은 위 값과 SOURCE-ASSETS.json에 기록되어 있습니다.",
            "세부 라이선스와 재배포 조건은 THIRD_PARTY_NOTICES.md 및 licenses 폴더를 확인하세요.",
            "",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def write_build_info(output: Path, version: str, repository_url: str, python_version: str) -> None:
    """사용자가 설치본의 빌드 기준을 확인할 수 있는 JSON을 씁니다."""
    document = {
        "schema_version": 1,
        "application": "YTDownloader",
        "version": version,
        "repository": normalize_repository_url(repository_url),
        "python_version": python_version,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YTDownloader 배포 메타데이터를 생성합니다.")
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version")

    version_file = subparsers.add_parser("version-file")
    version_file.add_argument("--output", type=Path, required=True)
    version_file.add_argument("--publisher", required=True)

    source_offer = subparsers.add_parser("source-offer")
    source_offer.add_argument("--output", type=Path, required=True)
    source_offer.add_argument("--manifest", type=Path, required=True)
    source_offer.add_argument("--repository-url", required=True)
    source_offer.add_argument("--python-version", required=True)

    build_info = subparsers.add_parser("build-info")
    build_info.add_argument("--output", type=Path, required=True)
    build_info.add_argument("--repository-url", required=True)
    build_info.add_argument("--python-version", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    version = project_version(arguments.project)
    if arguments.command == "version":
        print(version)
    elif arguments.command == "version-file":
        write_version_file(arguments.output, version, arguments.publisher)
    elif arguments.command == "source-offer":
        write_source_offer(
            arguments.output,
            arguments.manifest,
            arguments.repository_url,
            version,
            arguments.python_version,
        )
    elif arguments.command == "build-info":
        write_build_info(arguments.output, version, arguments.repository_url, arguments.python_version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssetError as error:
        print(f"배포 메타데이터 생성 실패: {error}", file=sys.stderr)
        raise SystemExit(1) from error
