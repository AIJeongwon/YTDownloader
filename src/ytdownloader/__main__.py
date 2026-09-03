"""GUI 애플리케이션 진입점입니다."""

from __future__ import annotations

import sys


def main(arguments: list[str] | None = None) -> int:
    """Qt 애플리케이션을 시작합니다."""
    command_arguments = sys.argv[1:] if arguments is None else arguments
    if command_arguments == ["--version"]:
        from . import __version__

        print(__version__)
        return 0

    installation_check = command_arguments == ["--check-installation"]
    if installation_check:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    application_arguments = [sys.argv[0]] if installation_check else (
        sys.argv if arguments is None else [sys.argv[0], *command_arguments]
    )
    application = QApplication(application_arguments)
    application.setApplicationName("YTDownloader")
    application.setOrganizationName("YTDownloader")
    application.setStyle("Fusion")

    if installation_check:
        import ssl

        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QWidget

        ssl.create_default_context()
        probe = QWidget()
        probe.setWindowTitle("YTDownloader 설치 검사")
        probe.show()

        def finish_check() -> None:
            probe.close()
            application.quit()

        QTimer.singleShot(0, finish_check)
        return application.exec()

    from .gui import MainWindow

    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
