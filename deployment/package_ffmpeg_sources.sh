#!/usr/bin/env bash
set -euo pipefail

# 검증된 FFmpeg-Builds 스크립트가 실제 GPL 공유 빌드에 사용한 의존 소스만 묶습니다.
if [[ "$#" -ne 2 ]]; then
    echo "사용법: package_ffmpeg_sources.sh <FFmpeg-Builds 소스> <출력 파일>" >&2
    exit 2
fi

archive="$(realpath "$1")"
output="$(realpath -m "$2")"
if [[ ! -f "$archive" || "$output" == "$archive" ]]; then
    echo "입력 아카이브 또는 출력 경로가 올바르지 않습니다." >&2
    exit 2
fi

work_directory="$(mktemp -d)"
source_directory="$work_directory/source"
package_directory="$work_directory/package"
mkdir -p "$source_directory" "$package_directory"
tar -xzf "$archive" -C "$source_directory"

mapfile -t roots < <(find "$source_directory" -mindepth 1 -maxdepth 1 -type d -print)
if [[ "${#roots[@]}" -ne 1 ]]; then
    echo "FFmpeg-Builds 소스의 최상위 폴더를 정확히 하나 찾지 못했습니다." >&2
    exit 1
fi
build_root="${roots[0]}"

(
    cd "$build_root"
    ./generate.sh win64 gpl-shared
    ./download.sh

    mapfile -t source_files < <(
        grep -oE '\.cache/downloads/[A-Za-z0-9._-]+\.tar\.xz' Dockerfile |
            sort -u
    )
    if [[ "${#source_files[@]}" -eq 0 ]]; then
        echo "GPL 공유 빌드의 의존 소스 목록을 찾지 못했습니다." >&2
        exit 1
    fi

    mkdir -p "$package_directory/dependency-sources"
    : > "$package_directory/SOURCE-CHECKSUMS.txt"
    for source_file in "${source_files[@]}"; do
        if [[ ! -f "$source_file" || -L "$source_file" ]]; then
            echo "의존 소스 아카이브를 찾지 못했습니다: $source_file" >&2
            exit 1
        fi
        filename="$(basename "$source_file")"
        cp "$source_file" "$package_directory/dependency-sources/$filename"
        sha256sum "$source_file" | sed "s#  .*#  dependency-sources/$filename#" \
            >> "$package_directory/SOURCE-CHECKSUMS.txt"
    done
)

cp "$archive" "$package_directory/FFmpeg-Builds-source.tar.gz"
(
    cd "$package_directory"
    tar -cf "$output" .
)
test -s "$output"
echo "FFmpeg 의존 대응 소스 생성 완료: $output"
