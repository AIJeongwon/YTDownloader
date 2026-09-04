from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from deployment.checksums import verify_checksums, write_checksums
from deployment.prepare_assets import (
    AssetError,
    generated_source_assets,
    prepare_generated_source_input,
    prepare_sources,
    safe_destination,
    selected_source_assets,
    validate_build_python,
    validate_reusable_source_mapping,
)
from deployment.prune_bundle import normalize_python_runtime_dlls, remove_bundled_system_icu
from deployment.release_metadata import project_version, version_tuple, write_source_offer, write_version_file
from deployment.reusable_sources import verify_reusable_sources
from ytdownloader.__main__ import main


class DeploymentTest(unittest.TestCase):
    @staticmethod
    def reusable_source_manifest() -> dict[str, object]:
        return {
            "schema_version": 1,
            "build_python_versions": ["3.12.14"],
            "source_assets": [
                {
                    "id": "build-scripts",
                    "title": "빌드 스크립트",
                    "filename": "build-scripts.tar.gz",
                    "url": "https://github.com/ExampleOwner/ExampleRepo/releases/download/build-input/build-scripts.tar.gz",
                    "size": 1,
                    "sha256": "1" * 64,
                },
                {
                    "id": "python",
                    "title": "Python 소스",
                    "filename": "Python.tar.xz",
                    "url": "https://www.python.org/example",
                    "size": 1,
                    "sha256": "2" * 64,
                    "python_version": "3.12.14",
                },
            ],
            "generated_source_assets": [
                {
                    "id": "generated",
                    "title": "생성 소스",
                    "filename": "generated-source.tar",
                    "input_filename": "build-scripts.tar.gz",
                    "release_tag": "ffmpeg-sources-1234567890-abcdef1234",
                }
            ],
            "reusable_source_assets": [
                {
                    "id": "generated",
                    "title": "생성 소스",
                    "filename": "generated-source.tar",
                    "url": "https://github.com/ExampleOwner/ExampleRepo/releases/download/v1.0.0/generated-source.tar",
                    "size": 123,
                    "sha256": "a" * 64,
                }
            ],
        }

    def test_version_command_does_not_start_gui(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = main(["--version"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "0.2.1")

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
                        {
                            "id": "bad",
                            "title": "잘못된 파일",
                            "filename": "../bad.tar",
                            "input_filename": "input.tar.gz",
                            "release_tag": "ffmpeg-sources-1234567890-abcdef1234",
                        }
                    ]
                }
            )

    def test_reusable_source_mapping_requires_exact_match(self) -> None:
        manifest = self.reusable_source_manifest()
        validate_reusable_source_mapping(manifest)
        manifest["reusable_source_assets"][0]["filename"] = "other.tar"
        with self.assertRaisesRegex(AssetError, "일치하지 않습니다"):
            validate_reusable_source_mapping(manifest)

    def test_generated_source_input_can_precede_reusable_asset_update(self) -> None:
        manifest = self.reusable_source_manifest()
        manifest["reusable_source_assets"][0]["filename"] = "previous-source.tar"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def write_fake_asset(record: object, cache: Path, destination: Path) -> Path:
                del record, cache
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"input")
                return destination

            with mock.patch("deployment.prepare_assets.copy_verified_asset", side_effect=write_fake_asset):
                prepare_generated_source_input(
                    manifest,
                    root / "cache",
                    root / "input",
                    "3.12.14",
                    "generated",
                )

            self.assertEqual((root / "input" / "build-scripts.tar.gz").read_bytes(), b"input")

    def test_source_offer_uses_release_asset_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "assets.json"
            manifest.write_text(json.dumps(self.reusable_source_manifest(), ensure_ascii=False), encoding="utf-8")
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
            self.assertIn("/releases/download/v1.0.0/generated-source.tar", content)
            self.assertIn("SHA-256: " + "a" * 64, content)

    def test_source_manifest_records_reusable_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "sources"

            def write_fake_asset(record: object, cache: Path, destination: Path) -> Path:
                del record, cache
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"x")
                return destination

            with mock.patch("deployment.prepare_assets.copy_verified_asset", side_effect=write_fake_asset):
                prepare_sources(
                    self.reusable_source_manifest(),
                    root / "cache",
                    output,
                    "3.12.14",
                )

            metadata = json.loads((output / "SOURCE-ASSETS.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["schema_version"], 2)
            self.assertEqual(metadata["reusable_sources"][0]["sha256"], "a" * 64)
            self.assertEqual(
                metadata["reusable_sources"][0]["url"],
                "https://github.com/ExampleOwner/ExampleRepo/releases/download/v1.0.0/generated-source.tar",
            )

    def test_reusable_source_verification_uses_github_digest(self) -> None:
        manifest = self.reusable_source_manifest()
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "assets": [
                    {
                        "name": "generated-source.tar",
                        "state": "uploaded",
                        "size": 123,
                        "digest": "sha256:" + "a" * 64,
                        "browser_download_url": "https://github.com/ExampleOwner/ExampleRepo/releases/download/v1.0.0/generated-source.tar",
                    }
                ],
            }
        ).encode()
        opener = mock.Mock(return_value=response)

        with redirect_stdout(StringIO()):
            verify_reusable_sources(manifest, "ExampleOwner/ExampleRepo", opener)

        request = opener.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/ExampleOwner/ExampleRepo/releases/tags/v1.0.0",
        )

    def test_reusable_source_verification_rejects_digest_mismatch(self) -> None:
        manifest = self.reusable_source_manifest()
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "assets": [
                    {
                        "name": "generated-source.tar",
                        "state": "uploaded",
                        "size": 123,
                        "digest": "sha256:" + "b" * 64,
                        "browser_download_url": "https://github.com/ExampleOwner/ExampleRepo/releases/download/v1.0.0/generated-source.tar",
                    }
                ],
            }
        ).encode()

        with self.assertRaisesRegex(AssetError, "일치하지 않습니다"):
            verify_reusable_sources(manifest, "ExampleOwner/ExampleRepo", mock.Mock(return_value=response))

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
