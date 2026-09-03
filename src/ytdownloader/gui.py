"""PySide6 기반 메인 화면과 비동기 작업 제어를 구현합니다."""

from __future__ import annotations

import bisect
import os
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QMimeData,
    QObject,
    QProcess,
    QProcessEnvironment,
    QPropertyAnimation,
    QSettings,
    QSize,
    QThread,
    QTimer,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QImageReader,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .app_updates import AppRelease, AppUpdateCheckResult, check_for_app_update
from .commands import DONE_PREFIX, build_download_arguments, parse_progress_line
from .job_files import (
    JOB_FILE_EXTENSION,
    JobDocument,
    JobFileError,
    create_job_document,
    load_job_file,
    save_job_file,
)
from .models import DownloadRequest, MediaKind
from .process_control import terminate_process_tree
from .tools import ToolError, ToolPaths, discover_tools
from .updater import UpdateResult, YtDlpUpdater
from .validation import (
    ValidationError,
    build_request,
    format_time,
    parse_time,
    validate_cookie_file,
    validate_youtube_url,
)
from .video_info import (
    VideoInfo,
    VideoInfoError,
    build_video_info_arguments,
    format_duration,
    parse_video_info,
    validate_request_durations,
    validate_thumbnail_url,
)

_VISIBLE_SEGMENT_ROWS = 6
_SEGMENT_ROW_HEIGHT = 40
_MINIMUM_WINDOW_SIZE = QSize(760, 640)
_PREFERRED_WINDOW_SIZE = QSize(880, 980)
_INITIAL_SCREEN_MARGIN = 64
_THUMBNAIL_SIZE = QSize(144, 81)
_MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
_SEGMENT_HELP = """구간을 추가하면 각 행을 서로 다른 파일로 저장합니다.

• 파일 제목: 확장자를 제외한 저장 이름
• 시작/종료: 시:분:초 형식
• 숫자만 입력: 오른쪽부터 초 2자리, 분 2자리, 나머지는 시간
  예) 123 → 00:01:23, 13033 → 01:30:33

‘작업 저장’으로 현재 주소와 구간 목록을 .ytdjob 파일로 보관할 수 있습니다.
저장한 파일은 ‘작업 불러오기’를 누르거나 이 창으로 끌어다 놓아 불러올 수 있습니다."""


def _initial_window_size(available_size: QSize | None) -> QSize:
    """화면 여백과 최소 크기를 지키는 최초 창 크기를 반환합니다."""
    if available_size is None or not available_size.isValid():
        return QSize(_PREFERRED_WINDOW_SIZE)
    width = min(
        _PREFERRED_WINDOW_SIZE.width(),
        max(_MINIMUM_WINDOW_SIZE.width(), available_size.width() - _INITIAL_SCREEN_MARGIN),
    )
    height = min(
        _PREFERRED_WINDOW_SIZE.height(),
        max(_MINIMUM_WINDOW_SIZE.height(), available_size.height() - _INITIAL_SCREEN_MARGIN),
    )
    return QSize(width, height)


class _SmoothTableWidget(QTableWidget):
    """마우스 휠 이동을 픽셀 단위 애니메이션으로 처리하는 표입니다."""

    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._scroll_target = 0
        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(170)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def wheelEvent(self, event: QWheelEvent) -> None:
        bar = self.verticalScrollBar()
        pixel_delta = event.pixelDelta().y()
        angle_delta = event.angleDelta().y()
        if pixel_delta == 0 and angle_delta == 0:
            super().wheelEvent(event)
            return

        delta = pixel_delta or angle_delta
        at_boundary = (
            bar.maximum() <= bar.minimum()
            or (delta < 0 and bar.value() >= bar.maximum())
            or (delta > 0 and bar.value() <= bar.minimum())
        )
        if at_boundary:
            self._forward_wheel_to_outer_scroll(event)
            return

        if self._scroll_animation.state() == QAbstractAnimation.State.Running:
            base = self._scroll_target
        else:
            base = bar.value()

        positions = {bar.minimum(), bar.maximum()}
        for row in range(self.rowCount()):
            position = self.verticalHeader().sectionPosition(row)
            positions.add(max(bar.minimum(), min(bar.maximum(), position)))
        ordered_positions = sorted(positions)
        steps = max(1, round(abs(angle_delta) / 120 * 2)) if angle_delta else 1
        if delta < 0:
            index = bisect.bisect_right(ordered_positions, base)
            index = min(len(ordered_positions) - 1, index + steps - 1)
        else:
            index = bisect.bisect_left(ordered_positions, base) - 1
            index = max(0, index - steps + 1)
        self._scroll_target = ordered_positions[index]

        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(self._scroll_target)
        self._scroll_animation.start()
        event.accept()

    def _forward_wheel_to_outer_scroll(self, event: QWheelEvent) -> None:
        """표가 더 움직일 수 없으면 가장 가까운 바깥 스크롤 영역을 움직입니다."""
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.wheelEvent(event)
                return
            parent = parent.parentWidget()
        event.ignore()


class _TimeEdit(QLineEdit):
    """콜론 없는 HHMMSS 입력도 시:분:초로 자동 정규화하는 입력란입니다."""

    def __init__(self) -> None:
        super().__init__()
        self._last_normalized_text = ""
        self.setPlaceholderText("00:00:00")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMaxLength(16)
        self.editingFinished.connect(self.normalize_time)

    @Slot()
    def normalize_time(self) -> None:
        value = self.text().strip()
        if not value:
            self._last_normalized_text = ""
            return

        parse_value = value
        if self._last_normalized_text and value.startswith(self._last_normalized_text):
            appended_digits = value[len(self._last_normalized_text) :]
            if appended_digits.isdigit():
                previous_digits = self._last_normalized_text.replace(":", "").lstrip("0") or "0"
                parse_value = previous_digits + appended_digits

        try:
            seconds = parse_time(parse_value, "시간")
        except ValidationError:
            return
        if seconds is not None:
            normalized_text = format_time(seconds)
            self._last_normalized_text = normalized_text
            self.setText(normalized_text)


class _UpdateWorker(QObject):
    """업데이트의 블로킹 네트워크 작업을 전용 스레드에서 수행합니다."""

    completed = Signal(object)

    @Slot()
    def run(self) -> None:
        try:
            result = YtDlpUpdater().ensure_latest()
        except Exception as error:
            result = UpdateResult(False, False, f"업데이트 처리 중 예상하지 못한 오류가 발생했습니다: {type(error).__name__}")
        self.completed.emit(result)


class _AppUpdateWorker(QObject):
    """GitHub의 최신 앱 릴리스를 전용 스레드에서 확인합니다."""

    completed = Signal(object)

    @Slot()
    def run(self) -> None:
        try:
            result = AppUpdateCheckResult(check_for_app_update(__version__))
        except Exception as error:
            result = AppUpdateCheckResult(None, f"{type(error).__name__}: {error}")
        self.completed.emit(result)


class _AppUpdateDialog(QMessageBox):
    """새 앱 버전과 버전별 알림 제외 선택지를 표시합니다."""

    def __init__(self, release: AppRelease, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setIcon(QMessageBox.Icon.Information)
        self.setWindowTitle("YTDownloader 업데이트")
        self.setText(f"새 버전 {release.version}이 있습니다.")
        self.setInformativeText("GitHub 릴리스 페이지에서 새 설치 파일을 받을 수 있습니다.")
        self.suppress_checkbox = QCheckBox("이 버전의 업데이트 알림을 다시 표시하지 않기")
        self.setCheckBox(self.suppress_checkbox)
        self.download_button = self.addButton("다운로드 페이지 열기", QMessageBox.ButtonRole.AcceptRole)
        self.addButton("나중에", QMessageBox.ButtonRole.RejectRole)


class MainWindow(QMainWindow):
    """전체 영상 또는 여러 구간 다운로드를 관리하는 메인 창입니다."""

    def __init__(self) -> None:
        super().__init__()
        QImageReader.setAllocationLimit(32)
        self._settings = QSettings()
        self._network_manager = QNetworkAccessManager(self)
        self._tools_ready = False
        self._process: QProcess | None = None
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self._cancel_requested = False
        self._pending_requests: list[DownloadRequest] = []
        self._active_tools: ToolPaths | None = None
        self._current_job_number = 0
        self._total_jobs = 0
        self._update_thread: QThread | None = None
        self._update_worker: _UpdateWorker | None = None
        self._app_update_thread: QThread | None = None
        self._app_update_worker: _AppUpdateWorker | None = None
        self._video_info_process: QProcess | None = None
        self._video_info: VideoInfo | None = None
        self._video_info_cookie: Path | None = None
        self._video_info_query_url: str | None = None
        self._video_info_query_cookie: Path | None = None
        self._video_info_timed_out = False
        self._video_info_refresh_requested = False
        self._download_after_video_info = False
        self._thumbnail_reply: QNetworkReply | None = None
        self._thumbnail_data = bytearray()
        self._thumbnail_too_large = False
        self._close_after_update = False

        self.setWindowTitle("YTDownloader")
        self.setAcceptDrops(True)
        self.setMinimumSize(_MINIMUM_WINDOW_SIZE)
        screen = QApplication.primaryScreen()
        available_size = screen.availableGeometry().size() if screen is not None else None
        self.resize(_initial_window_size(available_size))
        self._build_ui()
        self._apply_style()
        self._adjust_segment_table_height()
        QTimer.singleShot(0, self._start_update)

    def _build_ui(self) -> None:
        page = QWidget()
        page.setObjectName("centralWidget")
        page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.page = page
        root = QVBoxLayout(page)
        root.setContentsMargins(36, 24, 36, 24)
        root.setSpacing(16)

        title = QLabel("YTDownloader")
        title.setObjectName("title")
        subtitle = QLabel("원하는 영상만 간단하고 안전하게 저장하세요.")
        subtitle.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        form_card = QFrame()
        form_card.setObjectName("card")
        self.form_card = form_card
        form = QFormLayout(form_card)
        form.setContentsMargins(24, 24, 24, 24)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(16)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        url_row = QWidget()
        url_layout = QHBoxLayout(url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(8)
        self.url_edit = QLineEdit()
        self.url_edit.setAcceptDrops(False)
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self._invalidate_video_info)
        self.url_edit.editingFinished.connect(self._request_video_info)
        self.video_info_button = QPushButton("정보 확인")
        self.video_info_button.setObjectName("compactButton")
        self.video_info_button.setEnabled(False)
        self.video_info_button.clicked.connect(lambda: self._request_video_info(force=True))
        url_layout.addWidget(self.url_edit, 1)
        url_layout.addWidget(self.video_info_button)
        form.addRow("YouTube 주소", url_row)

        self.video_info_card = QFrame()
        self.video_info_card.setObjectName("videoInfoCard")
        video_info_layout = QHBoxLayout(self.video_info_card)
        video_info_layout.setContentsMargins(12, 10, 12, 10)
        video_info_layout.setSpacing(14)
        self.video_thumbnail = QLabel("미리보기")
        self.video_thumbnail.setObjectName("videoThumbnail")
        self.video_thumbnail.setFixedSize(_THUMBNAIL_SIZE)
        self.video_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_thumbnail.setAccessibleName("영상 썸네일")
        video_info_layout.addWidget(self.video_thumbnail)
        video_text_layout = QVBoxLayout()
        video_text_layout.setContentsMargins(0, 0, 0, 0)
        video_text_layout.setSpacing(4)
        self.video_title = QLabel("주소를 입력하면 영상 정보를 확인합니다.")
        self.video_title.setObjectName("videoTitle")
        self.video_title.setWordWrap(True)
        self.video_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.video_metadata = QLabel("제목 · 채널 · 길이")
        self.video_metadata.setObjectName("muted")
        self.video_metadata.setWordWrap(True)
        self.video_info_status = QLabel("")
        self.video_info_status.setObjectName("videoInfoStatus")
        self.video_info_status.setWordWrap(True)
        video_text_layout.addWidget(self.video_title)
        video_text_layout.addWidget(self.video_metadata)
        video_text_layout.addWidget(self.video_info_status)
        video_text_layout.addStretch(1)
        video_info_layout.addLayout(video_text_layout, 1)
        self.video_info_label = QLabel("영상 정보")
        form.addRow(self.video_info_label, self.video_info_card)
        self.video_info_label.hide()
        self.video_info_card.hide()

        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(8)
        self.output_edit = QLineEdit(self._default_output_directory())
        self.output_edit.setAcceptDrops(False)
        self.output_edit.editingFinished.connect(self._remember_output_directory)
        self.output_button = QPushButton("찾아보기")
        self.output_button.clicked.connect(self._select_output_directory)
        output_layout.addWidget(self.output_edit, 1)
        output_layout.addWidget(self.output_button)
        form.addRow("저장 폴더", output_row)

        option_row = QWidget()
        option_layout = QGridLayout(option_row)
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setHorizontalSpacing(10)
        self.media_combo = QComboBox()
        self.media_combo.addItem("영상 · MP4", MediaKind.VIDEO)
        self.media_combo.addItem("오디오 · MP3", MediaKind.AUDIO)
        self.quality_combo = QComboBox()
        for label, height in (
            ("최고 화질", None),
            ("최대 2160p", 2160),
            ("최대 1440p", 1440),
            ("최대 1080p", 1080),
            ("최대 720p", 720),
            ("최대 480p", 480),
        ):
            self.quality_combo.addItem(label, height)
        self.media_combo.currentIndexChanged.connect(self._sync_media_options)
        option_layout.addWidget(self.media_combo, 0, 0)
        option_layout.addWidget(self.quality_combo, 0, 1)
        form.addRow("형식과 화질", option_row)

        segment_area = QWidget()
        self.segment_area = segment_area
        segment_layout = QVBoxLayout(segment_area)
        segment_layout.setContentsMargins(0, 0, 0, 0)
        segment_layout.setSpacing(8)
        segment_top = QHBoxLayout()
        segment_hint = QLabel("비워 두면 전체 영상")
        segment_hint.setObjectName("muted")
        self.segment_help_button = QToolButton()
        self.segment_help_button.setText("?")
        self.segment_help_button.setObjectName("helpButton")
        self.segment_help_button.setAccessibleName("구간별 저장 도움말")
        self.segment_help_button.setToolTip(_SEGMENT_HELP)
        self.segment_help_button.clicked.connect(self._show_segment_help)
        self.load_job_button = QPushButton("작업 불러오기")
        self.load_job_button.setObjectName("compactButton")
        self.load_job_button.setToolTip(".ytdjob 파일을 선택해 주소와 구간 목록을 불러옵니다.")
        self.load_job_button.clicked.connect(self._select_job_file)
        self.save_job_button = QPushButton("작업 저장")
        self.save_job_button.setObjectName("compactButton")
        self.save_job_button.setToolTip("현재 주소와 구간 목록을 .ytdjob 파일로 저장합니다.")
        self.save_job_button.clicked.connect(self._save_current_job)
        self.add_segment_button = QPushButton("+ 구간 추가")
        self.add_segment_button.setObjectName("compactButton")
        self.add_segment_button.clicked.connect(self._add_segment_row)
        segment_top.addWidget(segment_hint, 1)
        segment_top.addWidget(self.segment_help_button)
        segment_top.addWidget(self.load_job_button)
        segment_top.addWidget(self.save_job_button)
        segment_top.addWidget(self.add_segment_button)
        segment_layout.addLayout(segment_top)

        self.segment_table = _SmoothTableWidget(0, 4)
        self.segment_table.setHorizontalHeaderLabels(("파일 제목", "시작", "종료", ""))
        self.segment_table.setFixedHeight(287)
        self.segment_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.segment_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.segment_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.segment_table.verticalHeader().setVisible(False)
        header = self.segment_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.segment_table.setColumnWidth(1, 132)
        self.segment_table.setColumnWidth(2, 132)
        self.segment_table.setColumnWidth(3, 76)
        segment_layout.addWidget(self.segment_table)
        form.addRow("구간별 저장", segment_area)

        cookie_row = QWidget()
        cookie_layout = QHBoxLayout(cookie_row)
        cookie_layout.setContentsMargins(0, 0, 0, 0)
        cookie_layout.setSpacing(8)
        self.cookie_edit = QLineEdit()
        self.cookie_edit.setAcceptDrops(False)
        self.cookie_edit.setPlaceholderText("선택 사항 · Netscape 형식 cookies.txt")
        self.cookie_edit.textChanged.connect(self._invalidate_video_info)
        self.cookie_button = QPushButton("선택")
        self.cookie_button.clicked.connect(self._select_cookie_file)
        cookie_layout.addWidget(self.cookie_edit, 1)
        cookie_layout.addWidget(self.cookie_button)
        form.addRow("쿠키 파일", cookie_row)
        root.addWidget(form_card)

        status_card = QFrame()
        status_card.setObjectName("card")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(24, 20, 24, 20)
        status_layout.setSpacing(12)
        status_head = QHBoxLayout()
        self.status_label = QLabel("yt-dlp 확인을 준비하고 있습니다…")
        self.status_label.setObjectName("status")
        self.progress_detail = QLabel("")
        self.progress_detail.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.progress_detail.setObjectName("muted")
        status_head.addWidget(self.status_label, 1)
        status_head.addWidget(self.progress_detail)
        status_layout.addLayout(status_head)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        status_layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setAcceptDrops(False)
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setPlaceholderText("작업 상태가 여기에 표시됩니다.")
        status_layout.addWidget(self.log, 1)
        root.addWidget(status_card, 1)

        actions = QHBoxLayout()
        actions.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_download)
        self.download_button = QPushButton("다운로드")
        self.download_button.setObjectName("primaryButton")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._start_download)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.download_button)
        root.addLayout(actions)

        self.root_scroll = QScrollArea()
        self.root_scroll.setObjectName("rootScroll")
        self.root_scroll.setWidgetResizable(True)
        self.root_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.root_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.root_scroll.setWidget(page)
        self.setCentralWidget(self.root_scroll)

    def _apply_style(self) -> None:
        self.setFont(QFont("Malgun Gothic", 10))
        self.setStyleSheet(
            """
            QMainWindow, QScrollArea#rootScroll, QWidget#centralWidget { background: #0f172a; color: #e5e7eb; }
            QWidget { color: #e5e7eb; background: transparent; }
            QLabel { background: transparent; }
            QLabel#title { font-size: 28px; font-weight: 700; color: #f8fafc; }
            QLabel#subtitle, QLabel#muted { color: #94a3b8; }
            QLabel#status { font-weight: 600; }
            QFrame#card { background: #182235; border: 1px solid #263449; border-radius: 14px; }
            QFrame#card[jobDropActive="true"] { border: 2px solid #3b82f6; }
            QFrame#videoInfoCard { background: #101827; border: 1px solid #334155; border-radius: 10px; }
            QLabel#videoThumbnail {
                background: #0b1220; color: #64748b; border: 1px solid #263449; border-radius: 7px;
            }
            QLabel#videoTitle { color: #f8fafc; font-weight: 700; }
            QLabel#videoInfoStatus { color: #fbbf24; }
            QLineEdit, QComboBox, QPlainTextEdit {
                background: #101827; border: 1px solid #334155; border-radius: 8px;
                padding: 9px 11px; selection-background-color: #2563eb;
            }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #3b82f6; }
            QComboBox::drop-down { border: none; width: 28px; }
            QComboBox QAbstractItemView {
                background: #101827; color: #e5e7eb; border: 1px solid #475569;
                outline: none; padding: 4px;
                selection-background-color: #2563eb; selection-color: #ffffff;
            }
            QComboBox QAbstractItemView::item { min-height: 30px; padding: 4px 8px; }
            QComboBox QAbstractItemView::item:hover { background: #1e293b; color: #f8fafc; }
            QComboBox QAbstractItemView::item:selected { background: #2563eb; color: #ffffff; }
            QTableWidget {
                background: #101827; border: 1px solid #334155; border-radius: 8px;
                gridline-color: #263449; padding: 2px;
            }
            QHeaderView::section {
                background: #182235; color: #94a3b8; border: none;
                border-bottom: 1px solid #334155; padding: 7px; font-weight: 600;
            }
            QTableWidget QLineEdit { padding: 6px 10px; border-radius: 6px; }
            QPushButton {
                background: #263449; border: 1px solid #3b4a61; border-radius: 8px;
                padding: 9px 16px; font-weight: 600;
            }
            QPushButton:hover { background: #334155; }
            QPushButton:disabled { color: #64748b; background: #182235; border-color: #263449; }
            QPushButton#primaryButton { background: #2563eb; border-color: #3b82f6; min-width: 116px; }
            QPushButton#primaryButton:hover { background: #1d4ed8; }
            QPushButton#secondaryButton { min-width: 76px; }
            QPushButton#tableButton { padding: 7px 10px; min-width: 48px; }
            QPushButton#compactButton { padding: 7px 10px; }
            QToolButton#helpButton {
                background: #263449; color: #bfdbfe; border: 1px solid #3b4a61;
                border-radius: 10px; min-width: 20px; max-width: 20px;
                min-height: 20px; max-height: 20px; font-weight: 700;
            }
            QToolButton#helpButton:hover { background: #334155; border-color: #3b82f6; }
            QToolTip {
                background: #101827; color: #e5e7eb; border: 1px solid #475569;
                padding: 8px;
            }
            QProgressBar { background: #101827; border: none; border-radius: 5px; height: 10px; }
            QProgressBar::chunk { background: #3b82f6; border-radius: 5px; }
            QScrollBar:vertical {
                background: #101827; width: 9px; margin: 3px 1px;
                border: none; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #475569; border: none; border-radius: 4px; min-height: 32px;
            }
            QScrollBar::handle:vertical:hover { background: #64748b; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                width: 0px; height: 0px; background: transparent; border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QScrollBar:horizontal { height: 0px; background: transparent; }
            """
        )

    def _default_output_directory(self) -> str:
        saved = self._settings.value("outputDirectory", "", str)
        if saved and Path(saved).is_dir():
            return saved
        downloads = Path.home() / "Downloads"
        return str(downloads if downloads.is_dir() else Path.home())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.load_job_button.isEnabled() and self._job_path_from_mime_data(event.mimeData()) is not None:
            self._set_job_drop_highlight(True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_job_drop_highlight(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_job_drop_highlight(False)
        path = self._job_path_from_mime_data(event.mimeData())
        if path is None or not self.load_job_button.isEnabled():
            event.ignore()
            return
        self._load_job_from_path(path)
        event.acceptProposedAction()

    def _job_path_from_mime_data(self, mime_data: QMimeData) -> Path | None:
        if not mime_data.hasUrls():
            return None
        urls = mime_data.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        if path.suffix.lower() != JOB_FILE_EXTENSION or not path.is_file():
            return None
        return path

    def _set_job_drop_highlight(self, active: bool) -> None:
        if self.form_card.property("jobDropActive") is active:
            return
        self.form_card.setProperty("jobDropActive", active)
        style = self.form_card.style()
        style.unpolish(self.form_card)
        style.polish(self.form_card)
        self.form_card.update()

    def _adjust_segment_table_height(self) -> None:
        """헤더와 여섯 행이 한 픽셀도 잘리지 않는 표 높이를 적용합니다."""
        header = self.segment_table.horizontalHeader()
        header_height = header.sizeHint().height()
        header.setFixedHeight(header_height)
        content_height = _VISIBLE_SEGMENT_ROWS * _SEGMENT_ROW_HEIGHT
        frame_height = self.segment_table.frameWidth() * 2
        self.segment_table.setFixedHeight(header_height + content_height + frame_height)
        segment_layout = self.segment_area.layout()
        if segment_layout is not None:
            segment_layout.invalidate()
            self.segment_area.setMinimumHeight(segment_layout.sizeHint().height())
            self.segment_area.updateGeometry()

    @Slot()
    def _select_output_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.output_edit.text())
        if selected:
            self.output_edit.setText(selected)
            self._remember_output_directory()

    @Slot()
    def _remember_output_directory(self) -> None:
        """직접 입력하거나 선택한 유효한 저장 폴더를 즉시 기억합니다."""
        value = self.output_edit.text().strip()
        if not value:
            return
        directory = Path(value).expanduser()
        try:
            if not directory.is_dir():
                return
            resolved = directory.resolve()
        except OSError:
            return
        self._settings.setValue("outputDirectory", str(resolved))

    @Slot()
    def _select_cookie_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "쿠키 파일 선택", "", "텍스트 파일 (*.txt);;모든 파일 (*)")
        if selected:
            self.cookie_edit.setText(selected)

    @Slot(str)
    def _invalidate_video_info(self, _text: str = "") -> None:
        """주소나 쿠키가 바뀌면 이전 미리보기와 길이 검증 결과를 폐기합니다."""
        self._video_info = None
        self._video_info_cookie = None
        self._cancel_thumbnail_request()
        self.video_thumbnail.clear()
        self.video_thumbnail.setText("미리보기")
        self.video_title.setText("주소를 입력하면 영상 정보를 확인합니다.")
        self.video_metadata.setText("제목 · 채널 · 길이")
        self.video_info_status.clear()
        self._set_video_info_visible(False)

    def _request_video_info(self, *, force: bool = False, for_download: bool = False) -> None:
        """현재 주소의 정보를 별도 yt-dlp 프로세스로 비동기 조회합니다."""
        if for_download:
            self._download_after_video_info = True
        if not self._tools_ready:
            self._download_after_video_info = False
            self._set_video_info_visible(True)
            self.video_info_status.setText("yt-dlp 확인이 끝난 뒤 영상 정보를 확인할 수 있습니다.")
            return
        try:
            normalized_url = validate_youtube_url(self.url_edit.text())
            cookie_file = validate_cookie_file(self.cookie_edit.text())
        except (ValidationError, OSError) as error:
            self._video_info_failure(str(error))
            return

        if self._video_info_process is not None:
            self._video_info_refresh_requested = True
            self._set_video_info_visible(True)
            self.video_info_status.setText("진행 중인 영상 정보 확인을 기다리고 있습니다…")
            return
        if (
            not force
            and self._video_info is not None
            and self._video_info.url == normalized_url
            and self._video_info_cookie == cookie_file
        ):
            if self._download_after_video_info:
                self._download_after_video_info = False
                QTimer.singleShot(0, self._start_download)
            return

        try:
            tools = discover_tools()
        except (ToolError, OSError) as error:
            self._video_info_failure(str(error))
            return

        self._video_info_query_url = normalized_url
        self._video_info_query_cookie = cookie_file
        self._video_info_timed_out = False
        self._set_video_info_visible(True)
        self.video_title.setText("영상 정보를 확인하고 있습니다…")
        self.video_metadata.setText("잠시만 기다려 주세요.")
        self.video_info_status.clear()
        self.video_thumbnail.clear()
        self.video_thumbnail.setText("불러오는 중")
        self.video_info_button.setEnabled(False)
        if self._download_after_video_info:
            self.download_button.setEnabled(False)

        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("YTDLP_NO_PLUGINS", "1")
        process.setProcessEnvironment(environment)
        process.setProgram(str(tools.yt_dlp))
        process.setArguments(build_video_info_arguments(normalized_url, tools, cookie_file))
        process.finished.connect(self._video_info_finished)
        process.errorOccurred.connect(self._video_info_process_error)
        self._video_info_process = process
        process.start()
        QTimer.singleShot(30_000, lambda target=process: self._video_info_timeout(target))

    def _video_info_timeout(self, process: QProcess) -> None:
        """영상 정보 조회가 제한 시간을 넘으면 해당 프로세스 트리만 종료합니다."""
        if self._video_info_process is not process or process.state() == QProcess.ProcessState.NotRunning:
            return
        self._video_info_timed_out = True
        self._stop_download_process(process, force=True)

    @Slot(int, QProcess.ExitStatus)
    def _video_info_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        process = self._video_info_process
        if process is None:
            return
        stdout = bytes(process.readAllStandardOutput())
        stderr = bytes(process.readAllStandardError()).decode("utf-8", "replace")
        process.deleteLater()
        self._video_info_process = None
        self.video_info_button.setEnabled(self._tools_ready and self._process is None)
        self.download_button.setEnabled(self._tools_ready and self._process is None)

        if self._video_info_timed_out:
            self._video_info_failure("영상 정보 확인 시간이 초과되었습니다.", stderr)
            return
        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            self._video_info_failure("영상 정보를 확인하지 못했습니다.", stderr)
            return
        try:
            if self._video_info_query_url is None:
                raise VideoInfoError("영상 정보 요청 주소를 확인할 수 없습니다.")
            video_info = parse_video_info(stdout, self._video_info_query_url)
            current_url = validate_youtube_url(self.url_edit.text())
            current_cookie = validate_cookie_file(self.cookie_edit.text())
        except (VideoInfoError, ValidationError, OSError) as error:
            self._video_info_failure(str(error), stderr)
            return

        if current_url != video_info.url or current_cookie != self._video_info_query_cookie:
            pending_download = self._download_after_video_info
            refresh_requested = self._video_info_refresh_requested
            self._download_after_video_info = False
            self._video_info_refresh_requested = False
            self.video_info_status.setText("입력이 변경되어 영상 정보를 다시 확인해야 합니다.")
            if pending_download:
                QTimer.singleShot(0, self._start_download)
            elif refresh_requested:
                QTimer.singleShot(0, self._request_video_info)
            return

        self._video_info_refresh_requested = False
        self._video_info = video_info
        self._video_info_cookie = current_cookie
        self._render_video_info(video_info)
        self._load_video_thumbnail(video_info)
        pending_download = self._download_after_video_info
        self._download_after_video_info = False
        if pending_download:
            QTimer.singleShot(0, self._start_download)

    @Slot(QProcess.ProcessError)
    def _video_info_process_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart or self._video_info_process is None:
            return
        process = self._video_info_process
        self._video_info_process = None
        process.deleteLater()
        self.video_info_button.setEnabled(self._tools_ready and self._process is None)
        self.download_button.setEnabled(self._tools_ready and self._process is None)
        self._video_info_failure("영상 정보 확인을 위한 yt-dlp를 시작하지 못했습니다.")

    def _video_info_failure(self, message: str, details: str = "") -> None:
        """미리보기 실패를 표시하고 대기 중인 다운로드를 안전하게 취소합니다."""
        pending_download = self._download_after_video_info
        refresh_requested = self._video_info_refresh_requested
        self._download_after_video_info = False
        self._video_info_refresh_requested = False
        self._set_video_info_visible(True)
        self.video_title.setText("영상 정보를 확인하지 못했습니다.")
        self.video_metadata.clear()
        self.video_info_status.setText(message)
        self.video_thumbnail.clear()
        self.video_thumbnail.setText("미리보기\n없음")
        self.video_info_button.setEnabled(self._tools_ready and self._process is None)
        self.download_button.setEnabled(self._tools_ready and self._process is None)
        detail_line = next((line.strip() for line in reversed(details.splitlines()) if line.strip()), "")
        if detail_line:
            self._append_log(f"영상 정보 확인 실패: {detail_line[:500]}")
        if refresh_requested:
            if pending_download:
                self._download_after_video_info = True
            QTimer.singleShot(0, self._request_video_info)
        elif pending_download:
            QMessageBox.warning(self, "영상 정보 확인 필요", message)

    def _render_video_info(self, video_info: VideoInfo) -> None:
        self._set_video_info_visible(True)
        self.video_title.setText(video_info.title)
        self.video_metadata.setText(
            f"{video_info.channel}  ·  {format_duration(video_info.duration_seconds)}"
        )
        if video_info.duration_seconds is None:
            self.video_info_status.setText("길이 정보가 없어 구간 범위 검사를 생략합니다.")
        else:
            self.video_info_status.clear()

    def _set_video_info_visible(self, visible: bool) -> None:
        self.video_info_label.setVisible(visible)
        self.video_info_card.setVisible(visible)

    def _load_video_thumbnail(self, video_info: VideoInfo) -> None:
        """고정된 YouTube 정적 이미지 주소에서 크기가 제한된 썸네일을 받습니다."""
        self._cancel_thumbnail_request()
        request = QNetworkRequest(QUrl(video_info.thumbnail_url))
        request.setTransferTimeout(15_000)
        request.setMaximumRedirectsAllowed(0)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        reply = self._network_manager.get(request)
        self._thumbnail_reply = reply
        self._thumbnail_data = bytearray()
        self._thumbnail_too_large = False
        reply.readyRead.connect(lambda target=reply: self._read_thumbnail(target))
        reply.finished.connect(
            lambda target=reply, expected_id=video_info.video_id: self._thumbnail_finished(
                target, expected_id
            )
        )

    def _read_thumbnail(self, reply: QNetworkReply) -> None:
        if self._thumbnail_reply is not reply:
            return
        chunk = bytes(reply.readAll())
        if len(self._thumbnail_data) + len(chunk) > _MAX_THUMBNAIL_BYTES:
            self._thumbnail_too_large = True
            reply.abort()
            return
        self._thumbnail_data.extend(chunk)

    def _thumbnail_finished(self, reply: QNetworkReply, expected_id: str) -> None:
        if self._thumbnail_reply is not reply:
            reply.deleteLater()
            return
        self._read_thumbnail(reply)
        self._thumbnail_reply = None
        content_type = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or "").lower()
        valid_response = (
            not self._thumbnail_too_large
            and reply.error() == QNetworkReply.NetworkError.NoError
            and content_type.startswith("image/")
            and validate_thumbnail_url(reply.url().toString(), expected_id)
            and self._video_info is not None
            and self._video_info.video_id == expected_id
        )
        pixmap = QPixmap()
        if valid_response:
            valid_response = pixmap.loadFromData(bytes(self._thumbnail_data))
        if valid_response and pixmap.width() <= 4096 and pixmap.height() <= 4096:
            self.video_thumbnail.setPixmap(
                pixmap.scaled(
                    _THUMBNAIL_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.video_thumbnail.clear()
            self.video_thumbnail.setText("미리보기\n없음")
        self._thumbnail_data = bytearray()
        self._thumbnail_too_large = False
        reply.deleteLater()

    def _cancel_thumbnail_request(self) -> None:
        reply = self._thumbnail_reply
        self._thumbnail_reply = None
        self._thumbnail_data = bytearray()
        self._thumbnail_too_large = False
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    @Slot()
    def _show_segment_help(self) -> None:
        QMessageBox.information(self, "구간별 저장 사용법", _SEGMENT_HELP)

    @Slot()
    def _select_job_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "작업 파일 불러오기",
            self.output_edit.text(),
            "YTDownloader 작업 파일 (*.ytdjob)",
        )
        if selected:
            self._load_job_from_path(Path(selected))

    def _load_job_from_path(self, path: Path) -> bool:
        try:
            document = load_job_file(path)
        except JobFileError as error:
            QMessageBox.warning(self, "작업 파일 오류", str(error))
            return False

        if self.url_edit.text().strip() or self.segment_table.rowCount() > 0:
            answer = QMessageBox.question(
                self,
                "현재 입력 교체",
                "현재 YouTube 주소와 구간 목록을 작업 파일 내용으로 바꾸시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        self._apply_job_document(document)
        self.status_label.setText(f"작업 파일을 불러왔습니다: {path.name}")
        self._append_log(f"작업 파일 불러오기 완료: {path.name}")
        return True

    def _apply_job_document(self, document: JobDocument) -> None:
        self.url_edit.setText(document.url)
        self.segment_table.setRowCount(0)
        for segment in document.segments:
            self._add_segment_row()
            row = self.segment_table.rowCount() - 1
            title_edit = self.segment_table.cellWidget(row, 0)
            start_edit = self.segment_table.cellWidget(row, 1)
            end_edit = self.segment_table.cellWidget(row, 2)
            title_edit.setText(segment.title)
            start_edit.setText(segment.start)
            end_edit.setText(segment.end)
            start_edit.normalize_time()
            end_edit.normalize_time()
        self.segment_table.verticalScrollBar().setValue(0)
        self.url_edit.setFocus()

    @Slot()
    def _save_current_job(self) -> None:
        segments = [
            (
                self._segment_text(row, 0),
                self._segment_text(row, 1),
                self._segment_text(row, 2),
            )
            for row in range(self.segment_table.rowCount())
        ]
        try:
            document = create_job_document(self.url_edit.text(), segments)
        except JobFileError as error:
            QMessageBox.warning(self, "작업 파일 확인 필요", str(error))
            return

        output_directory = Path(self.output_edit.text())
        initial_directory = output_directory if output_directory.is_dir() else Path.home()
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "작업 파일 저장",
            str(initial_directory / f"작업 목록{JOB_FILE_EXTENSION}"),
            "YTDownloader 작업 파일 (*.ytdjob)",
        )
        if not selected:
            return
        try:
            saved_path = save_job_file(Path(selected), document)
        except JobFileError as error:
            QMessageBox.warning(self, "작업 파일 저장 오류", str(error))
            return
        self.status_label.setText(f"작업 파일을 저장했습니다: {saved_path.name}")
        self._append_log(f"작업 파일 저장 완료: {saved_path.name}")

    @Slot()
    def _add_segment_row(self) -> None:
        row = self.segment_table.rowCount()
        self.segment_table.insertRow(row)
        self.segment_table.setRowHeight(row, _SEGMENT_ROW_HEIGHT)

        title_edit = QLineEdit()
        title_edit.setAcceptDrops(False)
        title_edit.setPlaceholderText(f"예: 구간 {row + 1}")
        start_edit = _TimeEdit()
        end_edit = _TimeEdit()
        start_edit.setAcceptDrops(False)
        end_edit.setAcceptDrops(False)
        remove_button = QPushButton("삭제")
        remove_button.setObjectName("tableButton")
        remove_button.clicked.connect(lambda _checked=False, button=remove_button: self._remove_segment_row(button))

        self.segment_table.setCellWidget(row, 0, title_edit)
        self.segment_table.setCellWidget(row, 1, start_edit)
        self.segment_table.setCellWidget(row, 2, end_edit)
        self.segment_table.setCellWidget(row, 3, remove_button)
        self._renumber_segment_placeholders()
        title_edit.setFocus()

    def _remove_segment_row(self, button: QPushButton) -> None:
        for row in range(self.segment_table.rowCount()):
            if self.segment_table.cellWidget(row, 3) is button:
                self.segment_table.removeRow(row)
                self._renumber_segment_placeholders()
                return

    def _renumber_segment_placeholders(self) -> None:
        """현재 행 순서에 맞춰 비어 있는 제목 입력란의 예시 번호를 갱신합니다."""
        for row in range(self.segment_table.rowCount()):
            title_edit = self.segment_table.cellWidget(row, 0)
            if isinstance(title_edit, QLineEdit):
                title_edit.setPlaceholderText(f"예: 구간 {row + 1}")

    @Slot()
    def _sync_media_options(self) -> None:
        is_video = self.media_combo.currentData() is MediaKind.VIDEO
        self.quality_combo.setEnabled(is_video)

    def _start_update(self) -> None:
        self.status_label.setText("yt-dlp 최신 버전을 확인하고 있습니다…")
        self.progress.setRange(0, 0)
        self._append_log("공식 안정판 yt-dlp를 확인합니다.")

        thread = QThread(self)
        worker = _UpdateWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._finish_update)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(self._release_update_thread)
        self._update_thread = thread
        self._update_worker = worker
        thread.start()

    @Slot(object)
    def _finish_update(self, result: UpdateResult) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText(result.message)
        self._append_log(result.message)
        self._tools_ready = result.ready
        self.download_button.setEnabled(result.ready)
        self.video_info_button.setEnabled(result.ready)
        if result.ready and self.url_edit.text().strip():
            QTimer.singleShot(0, self._request_video_info)

    @Slot()
    def _release_update_thread(self) -> None:
        thread = self._update_thread
        self._update_thread = None
        self._update_worker = None
        if thread is not None:
            thread.deleteLater()
        if self._close_after_update:
            QApplication.quit()
        else:
            self._start_app_update_check()

    def _start_app_update_check(self) -> None:
        self._append_log("YTDownloader의 새 정식 버전을 확인합니다.")
        thread = QThread(self)
        worker = _AppUpdateWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._finish_app_update_check)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(self._release_app_update_thread)
        self._app_update_thread = thread
        self._app_update_worker = worker
        thread.start()

    @Slot(object)
    def _finish_app_update_check(self, result: AppUpdateCheckResult) -> None:
        if self._close_after_update:
            return
        if result.error is not None:
            self._append_log(f"앱 업데이트 확인을 건너뜁니다: {result.error}")
            return
        if result.release is None:
            self._append_log(f"YTDownloader {__version__} 최신 상태입니다.")
            return
        ignored_version = self._settings.value("ignoredAppUpdateVersion", "", str)
        if ignored_version == result.release.version:
            self._append_log(f"사용자가 제외한 앱 버전 {result.release.version}의 알림을 표시하지 않습니다.")
            return
        self._show_app_update(result.release)

    def _show_app_update(self, release: AppRelease) -> None:
        dialog = _AppUpdateDialog(release, self)
        dialog.exec()
        if dialog.suppress_checkbox.isChecked():
            self._settings.setValue("ignoredAppUpdateVersion", release.version)
            self._settings.sync()
        if dialog.clickedButton() is dialog.download_button:
            if not QDesktopServices.openUrl(QUrl(release.page_url)):
                QMessageBox.warning(self, "페이지 열기 실패", "기본 브라우저에서 GitHub 릴리스 페이지를 열지 못했습니다.")

    @Slot()
    def _release_app_update_thread(self) -> None:
        thread = self._app_update_thread
        self._app_update_thread = None
        self._app_update_worker = None
        if thread is not None:
            thread.deleteLater()
        if self._close_after_update:
            QApplication.quit()

    @Slot()
    def _start_download(self) -> None:
        try:
            requests = self._build_download_requests()
            tools = discover_tools()
        except (ValidationError, ToolError, OSError) as error:
            QMessageBox.warning(self, "확인 필요", str(error))
            return

        current_info = self._video_info
        if (
            current_info is None
            or current_info.url != requests[0].url
            or self._video_info_cookie != requests[0].cookie_file
        ):
            self._request_video_info(for_download=True)
            return
        try:
            validate_request_durations(requests, current_info)
        except ValidationError as error:
            QMessageBox.warning(self, "구간 확인 필요", str(error))
            return

        self._remember_output_directory()
        self._cancel_requested = False
        self._pending_requests = list(requests)
        self._active_tools = tools
        self._current_job_number = 0
        self._total_jobs = len(requests)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_detail.clear()
        if self._total_jobs > 1:
            self._append_log(f"구간 {self._total_jobs}개의 다운로드를 시작합니다.")
        else:
            self._append_log("다운로드 작업을 시작했습니다.")
        self._set_running(True)
        self._start_next_request()

    def _build_download_requests(self) -> list[DownloadRequest]:
        common = {
            "url": self.url_edit.text(),
            "output_directory": self.output_edit.text(),
            "media_kind": self.media_combo.currentData(),
            "max_height": self.quality_combo.currentData(),
            "cookie_file": self.cookie_edit.text(),
        }
        if self.segment_table.rowCount() == 0:
            return [build_request(**common, start_time="", end_time="")]

        requests: list[DownloadRequest] = []
        names: set[str] = set()
        for row in range(self.segment_table.rowCount()):
            try:
                request = build_request(
                    **common,
                    file_stem=self._segment_text(row, 0),
                    start_time=self._segment_text(row, 1),
                    end_time=self._segment_text(row, 2),
                )
            except ValidationError as error:
                raise ValidationError(f"{row + 1}번째 구간: {error}") from error
            name_key = request.file_stem.casefold() if request.file_stem is not None else ""
            if name_key in names:
                raise ValidationError(f"{row + 1}번째 구간의 파일 제목이 앞 구간과 중복됩니다.")
            names.add(name_key)
            requests.append(request)
        return requests

    def _segment_text(self, row: int, column: int) -> str:
        widget = self.segment_table.cellWidget(row, column)
        return widget.text() if isinstance(widget, QLineEdit) else ""

    def _start_next_request(self) -> None:
        if not self._pending_requests or self._active_tools is None:
            return
        request = self._pending_requests.pop(0)
        self._current_job_number += 1
        arguments = build_download_arguments(request, self._active_tools)
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self.progress.setValue(0)
        self.progress_detail.clear()

        if request.file_stem is None:
            self.status_label.setText("전체 영상을 다운로드합니다…")
        else:
            self.status_label.setText(f"구간 {self._current_job_number}/{self._total_jobs} · {request.file_stem}")
            self._append_log(f"구간 {self._current_job_number}/{self._total_jobs} 시작: {request.file_stem}")

        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("YTDLP_NO_PLUGINS", "1")
        process.setProcessEnvironment(environment)
        process.setProgram(str(self._active_tools.yt_dlp))
        process.setArguments(arguments)
        process.setWorkingDirectory(str(request.output_directory))
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._download_finished)
        process.errorOccurred.connect(self._process_error)
        self._process = process
        process.start()

    @Slot()
    def _read_stdout(self) -> None:
        if self._process is None:
            return
        self._stdout_buffer += bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self._stdout_buffer = self._consume_lines(self._stdout_buffer, is_error=False)

    @Slot()
    def _read_stderr(self) -> None:
        if self._process is None:
            return
        self._stderr_buffer += bytes(self._process.readAllStandardError()).decode("utf-8", "replace")
        self._stderr_buffer = self._consume_lines(self._stderr_buffer, is_error=True)

    def _consume_lines(self, buffer: str, *, is_error: bool) -> str:
        lines = buffer.splitlines(keepends=True)
        remainder = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            remainder = lines.pop()
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            progress = parse_progress_line(line)
            if progress is not None:
                percent, details = progress
                self.progress.setValue(percent)
                prefix = f"{self._current_job_number}/{self._total_jobs} · " if self._total_jobs > 1 else ""
                self.progress_detail.setText(prefix + details)
                if self._total_jobs == 1:
                    self.status_label.setText("다운로드 중입니다…")
            elif line.startswith(DONE_PREFIX):
                self._append_log(f"저장 완료: {line[len(DONE_PREFIX):]}")
            elif is_error or line.startswith("["):
                self._append_log(line)
        return remainder

    @Slot(int, QProcess.ExitStatus)
    def _download_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        if self._stdout_buffer.strip():
            self._consume_lines(self._stdout_buffer + "\n", is_error=False)
        if self._stderr_buffer.strip():
            self._consume_lines(self._stderr_buffer + "\n", is_error=True)
        process = self._process
        self._process = None
        if process is not None:
            process.deleteLater()

        if self._cancel_requested:
            self._pending_requests.clear()
            self._active_tools = None
            self.status_label.setText("다운로드를 취소했습니다.")
            self._append_log("사용자가 작업을 취소했습니다.")
        elif exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            if self._pending_requests:
                self._start_next_request()
                return
            self._active_tools = None
            self.progress.setValue(100)
            self.progress_detail.setText(f"{self._total_jobs}/{self._total_jobs} · 100%" if self._total_jobs > 1 else "100%")
            if self._total_jobs > 1:
                self.status_label.setText(f"구간 {self._total_jobs}개를 모두 저장했습니다.")
            else:
                self.status_label.setText("다운로드가 완료되었습니다.")
        else:
            self._pending_requests.clear()
            self._active_tools = None
            self.status_label.setText("다운로드에 실패했습니다.")
            if exit_status == QProcess.ExitStatus.CrashExit:
                self._append_log(f"{self._current_job_number}번째 작업의 프로세스가 비정상 종료되었습니다.")
            else:
                self._append_log(f"{self._current_job_number}번째 작업이 오류 코드 {exit_code}로 종료되었습니다.")
        self._set_running(False)

    @Slot(QProcess.ProcessError)
    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.status_label.setText("yt-dlp를 시작하지 못했습니다.")
            self._append_log("실행 파일이 이동되었거나 실행 권한이 없습니다.")
            process = self._process
            self._process = None
            self._pending_requests.clear()
            self._active_tools = None
            if process is not None:
                process.deleteLater()
            self._set_running(False)

    @Slot()
    def _cancel_download(self) -> None:
        if self._process is None:
            return
        process = self._process
        self._cancel_requested = True
        self._pending_requests.clear()
        self.status_label.setText("다운로드를 취소하고 있습니다…")
        self.cancel_button.setEnabled(False)
        if process.state() == QProcess.ProcessState.NotRunning:
            return
        if not self._stop_download_process(process, force=False):
            self._append_log("프로세스 트리 종료를 확인하지 못해 주 다운로드 프로세스만 종료했습니다.")

    def _stop_download_process(self, process: QProcess, *, force: bool) -> bool:
        """현재 작업만 대상으로 하여 다운로드 프로세스를 종료합니다."""
        if process.state() == QProcess.ProcessState.NotRunning:
            return True
        if os.name == "nt":
            if terminate_process_tree(int(process.processId())):
                return True
            if process.state() == QProcess.ProcessState.NotRunning:
                return True
            process.kill()
            return False
        if force:
            process.kill()
        else:
            process.terminate()
            QTimer.singleShot(3000, lambda target=process: self._kill_process_if_running(target))
        return True

    def _kill_process_if_running(self, process: QProcess) -> None:
        """예약 당시의 프로세스가 계속 실행 중일 때만 강제 종료합니다."""
        try:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
        except RuntimeError:
            return

    def _set_running(self, running: bool) -> None:
        self.download_button.setEnabled(self._tools_ready and not running)
        self.cancel_button.setEnabled(running)
        for widget in (
            self.url_edit,
            self.output_edit,
            self.output_button,
            self.media_combo,
            self.quality_combo,
            self.segment_table,
            self.add_segment_button,
            self.load_job_button,
            self.save_job_button,
            self.video_info_button,
            self.cookie_edit,
            self.cookie_button,
        ):
            widget.setEnabled(not running)
        if not running:
            self.video_info_button.setEnabled(
                self._tools_ready and self._video_info_process is None
            )
            self._sync_media_options()

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message.replace("\r", " ").replace("\n", " "))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            process = self._process
            self._cancel_requested = True
            self._stop_download_process(process, force=True)
            if not process.waitForFinished(3000):
                process.kill()
                process.waitForFinished(1000)
        if (
            self._video_info_process is not None
            and self._video_info_process.state() != QProcess.ProcessState.NotRunning
        ):
            video_info_process = self._video_info_process
            video_info_process.blockSignals(True)
            self._stop_download_process(video_info_process, force=True)
            if not video_info_process.waitForFinished(3000):
                video_info_process.kill()
                video_info_process.waitForFinished(1000)
            video_info_process.deleteLater()
            self._video_info_process = None
        self._download_after_video_info = False
        self._video_info_refresh_requested = False
        self._cancel_thumbnail_request()
        background_check_running = (
            self._update_thread is not None
            and self._update_thread.isRunning()
            or self._app_update_thread is not None
            and self._app_update_thread.isRunning()
        )
        if background_check_running:
            self._close_after_update = True
            self.hide()
            event.ignore()
            return
        event.accept()
