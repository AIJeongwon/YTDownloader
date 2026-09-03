from __future__ import annotations

import io
import json
import unittest

from ytdownloader.app_updates import AppUpdateError, check_for_app_update


class _Response(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def _payload(version: str = "0.1.4") -> dict[str, object]:
    tag = f"v{version}"
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/AIJeongwon/YTDownloader/releases/tag/{tag}",
        "assets": [
            {
                "name": "YTDownloader-Setup.exe",
                "state": "uploaded",
                "size": 10_000_000,
                "digest": "sha256:" + ("a" * 64),
                "browser_download_url": (
                    f"https://github.com/AIJeongwon/YTDownloader/releases/download/{tag}/YTDownloader-Setup.exe"
                ),
            }
        ],
    }


class AppUpdateTests(unittest.TestCase):
    def test_newer_official_release_is_returned(self) -> None:
        payload = json.dumps(_payload()).encode("utf-8")

        def opener(request, timeout):
            self.assertEqual(
                request.full_url,
                "https://api.github.com/repos/AIJeongwon/YTDownloader/releases/latest",
            )
            self.assertEqual(timeout, 15.0)
            return _Response(payload)

        release = check_for_app_update("0.1.3", opener=opener)
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "0.1.4")

    def test_same_or_older_release_is_not_returned(self) -> None:
        for version in ("0.1.3", "0.1.2"):
            payload = json.dumps(_payload(version)).encode("utf-8")
            release = check_for_app_update("0.1.3", opener=lambda *_args: _Response(payload))
            self.assertIsNone(release)

    def test_release_page_must_belong_to_the_official_repository(self) -> None:
        payload_object = _payload()
        payload_object["html_url"] = "https://example.com/releases/tag/v0.1.4"
        payload = json.dumps(payload_object).encode("utf-8")

        with self.assertRaisesRegex(AppUpdateError, "공식 저장소"):
            check_for_app_update("0.1.3", opener=lambda *_args: _Response(payload))

    def test_installer_requires_github_digest(self) -> None:
        payload_object = _payload()
        payload_object["assets"][0]["digest"] = None
        payload = json.dumps(payload_object).encode("utf-8")

        with self.assertRaisesRegex(AppUpdateError, "무결성"):
            check_for_app_update("0.1.3", opener=lambda *_args: _Response(payload))

    def test_prerelease_is_rejected(self) -> None:
        payload_object = _payload()
        payload_object["prerelease"] = True
        payload = json.dumps(payload_object).encode("utf-8")

        with self.assertRaisesRegex(AppUpdateError, "정식 릴리스"):
            check_for_app_update("0.1.3", opener=lambda *_args: _Response(payload))


if __name__ == "__main__":
    unittest.main()
