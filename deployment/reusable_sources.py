"""게시된 재사용 대응 소스 자산이 목록과 정확히 일치하는지 검증합니다."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, unquote, urlparse

try:
    from .prepare_assets import (
        AssetError,
        generated_source_assets,
        load_manifest,
        reusable_source_assets,
        validate_reusable_source_mapping,
    )
except ImportError:
    from prepare_assets import (
        AssetError,
        generated_source_assets,
        load_manifest,
        reusable_source_assets,
        validate_reusable_source_mapping,
    )


MAXIMUM_API_RESPONSE_SIZE = 2 * 1024 * 1024
REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]+$"
)
TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def parse_release_asset_url(url: str, repository: str, filename: str) -> str:
    """GitHub 릴리스 자산 주소를 검증하고 태그를 반환합니다."""
    parsed = urlparse(url)
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    repository_parts = repository.split("/", 1)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.query
        or parsed.fragment
        or len(parts) != 6
        or parts[:2] != repository_parts
        or parts[2:4] != ["releases", "download"]
        or parts[5] != filename
    ):
        raise AssetError(f"재사용 대응 소스 릴리스 주소가 올바르지 않습니다: {url}")
    tag = parts[4]
    if TAG_PATTERN.fullmatch(tag) is None:
        raise AssetError(f"재사용 대응 소스 릴리스 태그가 올바르지 않습니다: {tag}")
    return tag


def read_json_response(response: BinaryIO) -> dict[str, object]:
    """크기가 제한된 GitHub API JSON 응답을 읽습니다."""
    payload = response.read(MAXIMUM_API_RESPONSE_SIZE + 1)
    if len(payload) > MAXIMUM_API_RESPONSE_SIZE:
        raise AssetError("GitHub 릴리스 API 응답이 허용된 크기를 초과했습니다.")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AssetError("GitHub 릴리스 API 응답을 해석할 수 없습니다.") from error
    if not isinstance(document, dict):
        raise AssetError("GitHub 릴리스 API 응답 형식이 올바르지 않습니다.")
    return document


def fetch_release(
    repository: str,
    tag: str,
    opener: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> dict[str, object]:
    """지정한 태그의 GitHub 릴리스 메타데이터를 가져옵니다."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/tags/{quote(tag, safe='')}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "YTDownloader-release-builder/1",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with opener(request, timeout=30) as response:
            return read_json_response(response)
    except AssetError:
        raise
    except (OSError, urllib.error.URLError) as error:
        raise AssetError(f"GitHub 릴리스 정보를 확인할 수 없습니다: {error}") from error


def verify_reusable_sources(
    manifest: dict[str, object],
    repository: str,
    opener: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> list[dict[str, object]]:
    """재사용 자산의 주소·크기·SHA-256을 GitHub 메타데이터와 대조합니다."""
    if REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise AssetError("GitHub 저장소 이름이 올바르지 않습니다.")
    validate_reusable_source_mapping(manifest)
    records = reusable_source_assets(manifest)
    tagged_records: dict[str, list[dict[str, object]]] = {}
    for record in records:
        tag = parse_release_asset_url(str(record["url"]), repository, str(record["filename"]))
        tagged_records.setdefault(tag, []).append(record)

    for tag, tag_records in tagged_records.items():
        release = fetch_release(repository, tag, opener)
        if release.get("tag_name") != tag or release.get("draft") is True:
            raise AssetError(f"게시된 GitHub 릴리스를 확인할 수 없습니다: {tag}")
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise AssetError(f"GitHub 릴리스 자산 목록이 올바르지 않습니다: {tag}")
        for record in tag_records:
            filename = str(record["filename"])
            matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == filename]
            if len(matches) != 1:
                raise AssetError(f"GitHub 릴리스에서 재사용 대응 소스 하나를 찾지 못했습니다: {filename}")
            asset = matches[0]
            expected_digest = f"sha256:{str(record['sha256']).lower()}"
            if (
                asset.get("state") != "uploaded"
                or asset.get("size") != record["size"]
                or str(asset.get("digest", "")).lower() != expected_digest
                or asset.get("browser_download_url") != record["url"]
            ):
                raise AssetError(f"재사용 대응 소스 메타데이터가 목록과 일치하지 않습니다: {filename}")
            print(f"재사용 대응 소스 검증 완료: {filename}")
    return records


def generated_field(manifest: dict[str, object], identifier: str, field: str) -> str:
    """수동 생성 워크플로가 사용할 생성 대상 필드를 반환합니다."""
    matches = [item for item in generated_source_assets(manifest) if item["id"] == identifier]
    if len(matches) != 1:
        raise AssetError(f"생성 대응 소스 항목 하나를 찾지 못했습니다: {identifier}")
    return matches[0][field]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="재사용 대응 소스 릴리스 자산을 검증합니다.")
    parser.add_argument("command", choices=("verify", "generated-field"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository")
    parser.add_argument("--id")
    parser.add_argument("--field", choices=("filename", "input_filename", "release_tag"))
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    manifest = load_manifest(arguments.manifest)
    if arguments.command == "verify":
        if not arguments.repository:
            raise AssetError("검증할 GitHub 저장소 이름이 필요합니다.")
        verify_reusable_sources(manifest, arguments.repository)
    else:
        if not arguments.id or not arguments.field:
            raise AssetError("생성 대응 소스 식별자와 필드가 필요합니다.")
        print(generated_field(manifest, arguments.id, arguments.field))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssetError as error:
        print(f"재사용 대응 소스 처리 실패: {error}", file=sys.stderr)
        raise SystemExit(1) from error
