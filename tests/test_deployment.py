from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from deployment.checksums import verify_checksums, write_checksums
from deployment.prepare_assets import (
    AssetError,
    generated_source_assets,
    safe_destination,
    selected_source_assets,
    validate_build_python,
)
from deployment.prune_bundle import normalize_python_runtime_dlls, remove_bundled_system_icu
from deployment.release_metadata import project_version, version_tuple, write_source_offer, write_version_file
from ytdownloader.__main__ import main


class DeploymentTest(unittest.TestCase):
    def test_version_command_does_not_start_gui(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = main(["--version"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "0.1.2")

    def test_installation_check_starts_qt_without_updater(self) -> None:
        self.assertEqual(main(["--check-installation"]), 0)

    def test_project_version_and_windows_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "pyproject.toml"
            project.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
            self.assertEqual(project_version(project), "1.2.3")
            self.assertEqual(version_tuple("1.2.3"), (1, 2, 3, 0))

    def test_version_file_contains_fixed_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "version.txt"
            write_version_file(output, "1.2.3", "ExampleOwner")
            content = output.read_text(encoding="utf-8")
            self.assertIn("filevers=(1, 2, 3, 0)", content)
            self.assertIn("ExampleOwner", content)

    def test_version_file_rejects_unsafe_publisher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(AssetError):
                write_version_file(Path(temporary) / "version.txt", "1.2.3", "bad'name")

    def test_safe_destination_rejects_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(AssetError):
                safe_destination(Path(temporary), "../outside.exe")

    def test_bundled_system_icu_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            internal = bundle / "_internal"
            internal.mkdir()
            (internal / "icuuc.dll").write_bytes(b"wrong ICU")
            (internal / "icudt78.dll").write_bytes(b"wrong ICU data")
            keep = internal / "Qt6Core.dll"
            keep.write_bytes(b"keep")
            remove_bundled_system_icu(bundle)
            self.assertFalse((internal / "icuuc.dll").exists())
            self.assertFalse((internal / "icudt78.dll").exists())
            self.assertTrue(keep.exists())

    def test_python_runtime_dlls_are_replaced_from_python_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            internal = root / "bundle" / "_internal"
            source_directory = root / "python" / "DLLs"
            internal.mkdir(parents=True)
            source_directory.mkdir(parents=True)
            (internal / "_ssl.pyd").write_bytes(b"extension")
            for name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll"):
                (internal / name).write_bytes(b"wrong")
                (source_directory / name).write_bytes(f"python:{name}".encode())

            dependencies = {"libcrypto-3-x64.dll", "libssl-3-x64.dll"}
            with mock.patch("deployment.prune_bundle.imported_dlls", return_value=dependencies):
                copied = normalize_python_runtime_dlls(root / "bundle", root / "python")

            self.assertEqual(set(copied), dependencies)
            for name in dependencies:
                self.assertEqual(
                    (internal / name).read_bytes(),
                    (source_directory / name).read_bytes(),
                )

    def test_python_source_selection_requires_exact_version(self) -> None:
        manifest = {
            "source_assets": [
                {"id": "common", "filename": "common.tar.gz"},
                {"id": "python", "filename": "python.tar.xz", "python_version": "3.12.14"},
            ]
        }
        selected = selected_source_assets(manifest, "3.12.14")
        self.assertEqual([item["id"] for item in selected], ["common", "python"])
        with self.assertRaises(AssetError):
            selected_source_assets(manifest, "3.12.13")

    def test_build_python_requires_exact_patch_version(self) -> None:
        manifest = {"build_python_versions": ["3.12.13", "3.13.15"]}
        validate_build_python(manifest, "3.12.13")
        validate_build_python(manifest, "3.13.15")
        with self.assertRaises(AssetError):
            validate_build_python(manifest, "3.12.14")
        for malformed in (None, [], ["3.13.15", 313], [""]):
            with self.subTest(malformed=malformed), self.assertRaises(AssetError):
                validate_build_python({"build_python_versions": malformed}, "3.13.15")

    def test_generated_source_assets_reject_paths(self) -> None:
        with self.assertRaises(AssetError):
            generated_source_assets(
                {
                    "generated_source_assets": [
                        {"id": "bad", "title": "잘못된 파일", "filename": "../bad.tar"}
                    ]
                }
            )

    def test_source_offer_uses_release_asset_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "assets.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_assets": [
                            {
                                "id": "python",
                                "title": "Python 소스",
                                "filename": "Python.tar.xz",
                                "url": "https://www.python.org/example",
                                "size": 1,
                                "sha256": "0" * 64,
                                "python_version": "3.12.14",
                            }
                        ],
                        "generated_source_assets": [
                            {
                                "id": "generated",
                                "title": "생성 소스",
                                "filename": "generated-source.tar",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = root / "SOURCE-OFFER.txt"
            write_source_offer(
                output,
                manifest,
                "https://github.com/ExampleOwner/ExampleRepo",
                "1.2.3",
                "3.12.14",
            )
            content = output.read_text(encoding="utf-8")
            self.assertIn("/releases/download/v1.2.3/Python.tar.xz", content)
            self.assertIn("/releases/download/v1.2.3/generated-source.tar", content)

    def test_checksum_file_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "b.bin"
            second = root / "a.bin"
            first.write_bytes(b"b")
            second.write_bytes(b"a")
            output = root / "SHA256SUMS.txt"
            write_checksums(output, [first, second])
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines[0].endswith("  a.bin"))
            self.assertEqual(lines[0].split()[0], hashlib.sha256(b"a").hexdigest())

    def test_checksum_verification_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "asset.bin"
            asset.write_bytes(b"original")
            checksum_file = root / "SHA256SUMS.txt"
            write_checksums(checksum_file, [asset])
            verify_checksums(checksum_file, root)
            asset.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_checksums(checksum_file, root)


if __name__ == "__main__":
    unittest.main()
