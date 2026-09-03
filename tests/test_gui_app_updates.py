from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ytdownloader.app_updates import AppRelease, AppUpdateCheckResult
from ytdownloader.gui import MainWindow, _AppUpdateDialog


class AppUpdateGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.timer_patch = patch("ytdownloader.gui.QTimer.singleShot")
        self.timer_patch.start()

    def tearDown(self) -> None:
        self.timer_patch.stop()

    def test_dialog_has_per_version_suppression_checkbox(self) -> None:
        release = AppRelease("0.1.4", "https://github.com/AIJeongwon/YTDownloader/releases/tag/v0.1.4")
        dialog = _AppUpdateDialog(release)
        self.assertIn("0.1.4", dialog.text())
        self.assertEqual(
            dialog.suppress_checkbox.text(),
            "이 버전의 업데이트 알림을 다시 표시하지 않기",
        )
        dialog.close()

    def test_ignored_version_is_not_shown_again(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window._settings.value.return_value = "0.1.4"
        release = AppRelease("0.1.4", "https://github.com/AIJeongwon/YTDownloader/releases/tag/v0.1.4")

        with patch.object(window, "_show_app_update") as show_update:
            window._finish_app_update_check(AppUpdateCheckResult(release))

        show_update.assert_not_called()
        window.close()

    def test_newer_version_is_shown_after_an_older_version_was_ignored(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        window._settings.value.return_value = "0.1.4"
        release = AppRelease("0.1.5", "https://github.com/AIJeongwon/YTDownloader/releases/tag/v0.1.5")

        with patch.object(window, "_show_app_update") as show_update:
            window._finish_app_update_check(AppUpdateCheckResult(release))

        show_update.assert_called_once_with(release)
        window.close()

    def test_checked_version_is_saved_and_release_page_is_opened(self) -> None:
        window = MainWindow()
        window._settings = Mock()
        release = AppRelease("0.1.4", "https://github.com/AIJeongwon/YTDownloader/releases/tag/v0.1.4")
        dialog = Mock()
        dialog.download_button = object()
        dialog.clickedButton.return_value = dialog.download_button
        dialog.suppress_checkbox.isChecked.return_value = True

        with (
            patch("ytdownloader.gui._AppUpdateDialog", return_value=dialog),
            patch("ytdownloader.gui.QDesktopServices.openUrl", return_value=True) as open_url,
        ):
            window._show_app_update(release)

        window._settings.setValue.assert_called_once_with("ignoredAppUpdateVersion", "0.1.4")
        window._settings.sync.assert_called_once_with()
        self.assertEqual(open_url.call_args.args[0].toString(), release.page_url)
        window.close()


if __name__ == "__main__":
    unittest.main()
