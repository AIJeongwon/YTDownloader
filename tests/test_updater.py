from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytdownloader.updater import YtDlpUpdater, _parse_release


class _Response(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def _payload(binary: bytes, version: str = "2026.08.19") -> dict[str, object]:
    name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    return {
        "tag_name": version,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": len(binary),
                "digest": f"sha256:{hashlib.sha256(binary).hexdigest()}",
                "browser_download_url": f"https://github.com/yt-dlp/yt-dlp/releases/download/{version}/{name}",
            }
        ],
    }


class UpdaterTests(unittest.TestCase):
    def test_failed_backup_move_keeps_existing_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("ytdownloader.updater.bin_directory", return_value=Path(directory)):
            updater = YtDlpUpdater()
            updater.target.write_bytes(b"existing")
            temporary = Path(directory) / "new.tmp"
            temporary.write_bytes(b"new")
            backup = Path(directory) / "backup"

            with patch("ytdownloader.updater.os.replace", side_effect=OSError("잠김")), self.assertRaises(OSError):
                updater._replace(temporary, backup, hashlib.sha256(b"new").hexdigest())

            self.assertEqual(updater.target.read_bytes(), b"existing")
            self.assertEqual(temporary.read_bytes(), b"new")
            self.assertFalse(backup.exists())

    def test_failed_install_restores_created_backup(self) -> None:
        real_replace = os.replace
        calls = 0

        def fail_second_replace(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("설치 실패")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as directory, patch("ytdownloader.updater.bin_directory", return_value=Path(directory)):
            updater = YtDlpUpdater()
            updater.target.write_bytes(b"existing")
            temporary = Path(directory) / "new.tmp"
            temporary.write_bytes(b"new")
            backup = Path(directory) / "backup"

            with patch("ytdownloader.updater.os.replace", side_effect=fail_second_replace), self.assertRaises(OSError):
                updater._replace(temporary, backup, hashlib.sha256(b"new").hexdigest())

            self.assertEqual(updater.target.read_bytes(), b"existing")
            self.assertEqual(temporary.read_bytes(), b"new")
            self.assertFalse(backup.exists())

    def test_official_release_is_installed_after_all_checks(self) -> None:
        header = b"MZ" if os.name == "nt" else b"#!"
        binary = header + (b"x" * 1_000_000)
        payload = json.dumps(_payload(binary)).encode("utf-8")

        def opener(request, _timeout):
            return _Response(payload if request.full_url.endswith("/releases/latest") else binary)

        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, "2026.08.19\n", "")

        with tempfile.TemporaryDirectory() as directory, patch("ytdownloader.updater.bin_directory", return_value=Path(directory)):
            result = YtDlpUpdater(opener=opener, runner=runner).ensure_latest()
            target = Path(directory) / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
            self.assertTrue(result.ready)
            self.assertTrue(result.updated)
            self.assertEqual(target.read_bytes(), binary)

    def test_digest_mismatch_does_not_replace_existing_file(self) -> None:
        header = b"MZ" if os.name == "nt" else b"#!"
        binary = header + (b"x" * 1_000_000)
        payload_object = _payload(binary)
        asset = payload_object["assets"][0]
        asset["digest"] = "sha256:" + ("0" * 64)
        payload = json.dumps(payload_object).encode("utf-8")

        def opener(request, _timeout):
            return _Response(payload if request.full_url.endswith("/releases/latest") else binary)

        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, "2026.07.04\n", "")

        with tempfile.TemporaryDirectory() as directory, patch("ytdownloader.updater.bin_directory", return_value=Path(directory)):
            target = Path(directory) / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
            target.write_bytes(header + b"existing")
            result = YtDlpUpdater(opener=opener, runner=runner).ensure_latest()
            self.assertTrue(result.ready)
            self.assertFalse(result.updated)
            self.assertEqual(result.version, "2026.07.04")
            self.assertEqual(target.read_bytes(), header + b"existing")

    def test_unofficial_asset_url_is_rejected(self) -> None:
        binary = (b"MZ" if os.name == "nt" else b"#!") + (b"x" * 1_000_000)
        payload = _payload(binary)
        payload["assets"][0]["browser_download_url"] = "https://example.com/yt-dlp.exe"
        with self.assertRaisesRegex(Exception, "공식 저장소"):
            _parse_release(payload)

    def test_disabled_update_never_opens_network(self) -> None:
        def opener(*_args):
            raise AssertionError("네트워크를 호출하면 안 됩니다.")

        with tempfile.TemporaryDirectory() as directory, patch("ytdownloader.updater.bin_directory", return_value=Path(directory)), patch.dict(os.environ, {"YTDOWNLOADER_AUTO_UPDATE": "0"}):
            result = YtDlpUpdater(opener=opener).ensure_latest()
            self.assertFalse(result.ready)
            self.assertIn("꺼져", result.message)


if __name__ == "__main__":
    unittest.main()
