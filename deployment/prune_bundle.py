"""앱에서 사용하지 않는 선택적 Qt 플러그인과 의존 모듈을 제거합니다."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

import pefile


OPTIONAL_PATHS = (
    "Qt6Pdf.dll",
    "Qt6Qml.dll",
    "Qt6QmlMeta.dll",
    "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll",
    "Qt6Quick.dll",
    "Qt6OpenGL.dll",
    "Qt6Svg.dll",
    "Qt6VirtualKeyboard.dll",
    "opengl32sw.dll",
    "plugins/iconengines/qsvgicon.dll",
    "plugins/imageformats/qpdf.dll",
    "plugins/imageformats/qsvg.dll",
    "plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
)
REMOVED_DLL_NAMES = {
    Path(value).name.casefold() for value in OPTIONAL_PATHS if value.casefold().endswith(".dll")
}
SYSTEM_ICU_PATTERNS = ("icudt*.dll", "icuin*.dll", "icuuc*.dll")
PYTHON_RUNTIME_DLL_PREFIXES = ("libcrypto-", "libssl-", "libffi-")


def imported_dlls(path: Path) -> set[str]:
    """PE 파일이 정적으로 불러오는 DLL 이름을 반환합니다."""
    image = pefile.PE(str(path), fast_load=True)
    try:
        image.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        return {
            entry.dll.decode("ascii", errors="ignore").casefold()
            for entry in getattr(image, "DIRECTORY_ENTRY_IMPORT", [])
        }
    finally:
        image.close()


def prune_pyside(bundle: Path) -> None:
    """필수 파일 존재와 남은 PE 의존성을 확인한 뒤 선택 모듈만 제거합니다."""
    pyside_root = bundle / "_internal" / "PySide6"
    if not pyside_root.is_dir():
        raise RuntimeError("패키징 결과에서 PySide6 폴더를 찾을 수 없습니다.")

    targets = {pyside_root / Path(value) for value in OPTIONAL_PATHS}
    missing = [path.relative_to(pyside_root) for path in targets if not path.is_file()]
    if missing:
        names = ", ".join(path.as_posix() for path in sorted(missing))
        raise RuntimeError(f"제거 대상으로 고정한 Qt 파일이 없습니다: {names}")

    broken_dependencies: list[str] = []
    for path in sorted(pyside_root.rglob("*")):
        if path in targets or path.suffix.casefold() not in {".dll", ".exe", ".pyd"}:
            continue
        required = imported_dlls(path) & REMOVED_DLL_NAMES
        if required:
            names = ", ".join(sorted(required))
            broken_dependencies.append(f"{path.relative_to(pyside_root).as_posix()}: {names}")
    if broken_dependencies:
        raise RuntimeError("남겨 둘 파일이 선택 모듈을 참조합니다: " + "; ".join(broken_dependencies))

    for path in targets:
        path.unlink()

    translation_directory = pyside_root / "translations"
    if translation_directory.is_dir():
        for pattern in ("qt_*.qm", "qt_help_*.qm"):
            for path in translation_directory.glob(pattern):
                path.unlink()


def remove_bundled_system_icu(bundle: Path) -> None:
    """PATH에서 잘못 수집될 수 있는 ICU를 제거해 Windows 기본 ICU를 사용합니다."""
    internal_directory = bundle / "_internal"
    if not internal_directory.is_dir():
        raise RuntimeError("패키징 결과에서 내부 런타임 폴더를 찾을 수 없습니다.")
    for pattern in SYSTEM_ICU_PATTERNS:
        for path in internal_directory.glob(pattern):
            if path.is_file():
                path.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_python_runtime_dlls(bundle: Path, python_base: Path) -> dict[str, str]:
    """PATH에서 섞인 DLL을 현재 Python 배포본의 원본으로 교체합니다."""
    internal_directory = bundle / "_internal"
    source_directory = python_base / "DLLs"
    if not internal_directory.is_dir():
        raise RuntimeError("패키징 결과에서 내부 런타임 폴더를 찾을 수 없습니다.")
    if not source_directory.is_dir():
        raise RuntimeError(f"Python DLL 폴더를 찾을 수 없습니다: {source_directory}")

    required_names: set[str] = set()
    for extension in sorted(internal_directory.glob("*.pyd")):
        for name in imported_dlls(extension):
            if name.startswith(PYTHON_RUNTIME_DLL_PREFIXES):
                required_names.add(name)
    if not required_names:
        raise RuntimeError("패키징 결과에서 Python 암호화 런타임 DLL 의존성을 찾지 못했습니다.")

    source_files = {path.name.casefold(): path for path in source_directory.glob("*.dll")}
    copied: dict[str, str] = {}
    for name in sorted(required_names):
        source = source_files.get(name)
        if source is None:
            raise RuntimeError(f"현재 Python 배포본에서 필수 DLL을 찾을 수 없습니다: {name}")
        destination = internal_directory / source.name
        shutil.copy2(source, destination)
        source_hash = _sha256_file(source)
        if _sha256_file(destination) != source_hash:
            raise RuntimeError(f"Python 런타임 DLL 복사 검증에 실패했습니다: {source.name}")
        copied[source.name] = source_hash
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="사용하지 않는 Qt 선택 모듈을 안전하게 제거합니다.")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--python-base", type=Path, required=True)
    arguments = parser.parse_args()
    bundle = arguments.bundle.resolve()
    prune_pyside(bundle)
    remove_bundled_system_icu(bundle)
    copied = normalize_python_runtime_dlls(bundle, arguments.python_base.resolve())
    for name, digest in copied.items():
        print(f"Python 런타임 DLL 확인: {name} ({digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
