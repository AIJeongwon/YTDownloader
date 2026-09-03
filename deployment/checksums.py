"""릴리스 파일의 재현 가능한 SHA-256 목록을 생성합니다."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^/\\]+)$")


def sha256_file(path: Path) -> str:
    """파일의 SHA-256을 소문자 16진수로 반환합니다."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(output: Path, files: list[Path]) -> None:
    """중복이 없는 일반 파일 목록을 이름순으로 기록합니다."""
    resolved_output = output.resolve()
    unique: dict[str, Path] = {}
    for file in files:
        resolved = file.resolve()
        if not resolved.is_file() or resolved == resolved_output:
            raise ValueError(f"체크섬 대상이 올바른 일반 파일이 아닙니다: {file}")
        key = resolved.name.casefold()
        if key in unique:
            raise ValueError(f"체크섬 대상 파일 이름이 중복됩니다: {resolved.name}")
        unique[key] = resolved

    lines = [f"{sha256_file(path)}  {path.name}" for _, path in sorted(unique.items())]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_checksums(checksum_file: Path, search_root: Path) -> None:
    """목록에 적힌 파일을 검색 루트에서 하나씩 찾아 SHA-256을 확인합니다."""
    if not checksum_file.is_file() or not search_root.is_dir():
        raise ValueError("체크섬 파일 또는 검색 폴더가 올바르지 않습니다.")
    try:
        lines = checksum_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"체크섬 파일을 읽을 수 없습니다: {error}") from error
    if not lines:
        raise ValueError("체크섬 목록이 비어 있습니다.")

    expected: dict[str, tuple[str, str]] = {}
    for line in lines:
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"체크섬 줄 형식이 올바르지 않습니다: {line}")
        digest, name = match.groups()
        key = name.casefold()
        if key in expected:
            raise ValueError(f"체크섬 파일 이름이 중복됩니다: {name}")
        expected[key] = (name, digest)

    candidates: dict[str, list[Path]] = {}
    for path in search_root.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.resolve() != checksum_file.resolve():
            candidates.setdefault(path.name.casefold(), []).append(path)
    for key, (name, digest) in expected.items():
        matches = candidates.get(key, [])
        if len(matches) != 1:
            raise ValueError(f"체크섬 대상 파일을 정확히 하나 찾지 못했습니다: {name}")
        if sha256_file(matches[0]) != digest:
            raise ValueError(f"SHA-256이 일치하지 않습니다: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="릴리스 파일의 SHA-256 목록을 생성하거나 검증합니다.")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--output", type=Path)
    operation.add_argument("--verify", type=Path)
    parser.add_argument("--search-root", type=Path)
    parser.add_argument("files", type=Path, nargs="*")
    arguments = parser.parse_args()
    if arguments.verify is not None:
        if arguments.search_root is None or arguments.files:
            parser.error("--verify에는 --search-root만 함께 사용할 수 있습니다.")
        verify_checksums(arguments.verify, arguments.search_root)
    else:
        if arguments.search_root is not None or not arguments.files:
            parser.error("--output에는 체크섬 대상 파일이 하나 이상 필요합니다.")
        write_checksums(arguments.output, arguments.files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
