from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QProcess, QSize, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox

from ytdownloader.gui import MainWindow, _initial_window_size
from ytdownloader.job_files import create_job_document, save_job_file
from ytdownloader.validation import ValidationError
from ytdownloader.video_info import VideoInfo


class GuiSegmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.timer_patch = patch("ytdownloader.gui.QTimer.singleShot")
        self.timer_patch.start()

    def tearDown(self) -> None:
        self.timer_patch.stop()

    def _window_with_two_rows(self, directory: str) -> MainWindow:
        window = MainWindow()
        window.url_edit.setText("https://youtu.be/abcdefghijk")
        window.output_edit.setText(directory)
        window._add_segment_row()
        window._add_segment_row()
        values = (("인트로", "00:00", "00:30"), ("핵심 장면", "00:30", "01:30"))
        for row, row_values in enumerate(values):
            for column, value in enumerate(row_values):
                window.segment_table.cellWidget(row, column).setText(value)
        return window

    def test_rows_become_independent_named_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self._window_with_two_rows(directory)
            requests = window._build_download_requests()
            self.assertEqual([request.file_stem for request in requests], ["인트로", "핵심 장면"])
            self.assertEqual(
                [(request.start_seconds, request.end_seconds) for request in requests],
                [(0.0, 30.0), (30.0, 90.0)],
            )
            window.close()

    def test_duplicate_titles_are_rejected_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self._window_with_two_rows(directory)
            window.segment_table.cellWidget(1, 0).setText("인트로")
            with self.assertRaisesRegex(ValidationError, "중복"):
                window._build_download_requests()
            window.close()

    def test_delete_button_removes_its_own_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self._window_with_two_rows(directory)
            second_button = window.segment_table.cellWidget(1, 3)
            window._remove_segment_row(second_button)
            self.assertEqual(window.segment_table.rowCount(), 1)
            self.assertEqual(window.segment_table.cellWidget(0, 0).text(), "인트로")
            window.close()

    def test_delete_renumbers_remaining_title_placeholders(self) -> None:
        window = MainWindow()
        for _ in range(4):
            window._add_segment_row()
        second_button = window.segment_table.cellWidget(1, 3)
        window._remove_segment_row(second_button)
        placeholders = [
            window.segment_table.cellWidget(row, 0).placeholderText()
            for row in range(window.segment_table.rowCount())
        ]
        self.assertEqual(placeholders, ["예: 구간 1", "예: 구간 2", "예: 구간 3"])
        window.close()

    def test_segment_table_has_expanded_smooth_scroll_area(self) -> None:
        window = MainWindow()
        self.assertEqual(
            window.segment_table.verticalScrollMode(),
            QAbstractItemView.ScrollMode.ScrollPerPixel,
        )
        expected_height = (
            window.segment_table.horizontalHeader().height()
            + (6 * 40)
            + (window.segment_table.frameWidth() * 2)
        )
        self.assertEqual(window.segment_table.height(), expected_height)
        self.assertGreaterEqual(window.segment_table.columnWidth(1), 132)
        self.assertGreaterEqual(window.segment_table.columnWidth(2), 132)
        window.close()

    def test_time_cells_normalize_compact_hhmmss(self) -> None:
        window = MainWindow()
        window._add_segment_row()
        start_edit = window.segment_table.cellWidget(0, 1)
        end_edit = window.segment_table.cellWidget(0, 2)
        start_edit.setText("123")
        end_edit.setText("13033")
        start_edit.normalize_time()
        end_edit.normalize_time()
        self.assertEqual(start_edit.text(), "00:01:23")
        self.assertEqual(end_edit.text(), "01:30:33")
        window.close()

    def test_digits_can_be_appended_after_time_is_normalized(self) -> None:
        window = MainWindow()
        window._add_segment_row()
        time_edit = window.segment_table.cellWidget(0, 1)

        time_edit.setText("123")
        time_edit.normalize_time()
        self.assertEqual(time_edit.text(), "00:01:23")

        time_edit.setText(time_edit.text() + "4")
        time_edit.normalize_time()
        self.assertEqual(time_edit.text(), "00:12:34")

        time_edit.setText(time_edit.text() + "5")
        time_edit.normalize_time()
        self.assertEqual(time_edit.text(), "01:23:45")
        window.close()

    def test_sixth_row_is_fully_visible_without_scrolling(self) -> None:
        window = MainWindow()
        window.resize(window.minimumSize())
        for _ in range(6):
            window._add_segment_row()
        window.show()
        self.application.processEvents()
        visible_height = window.segment_table.viewport().height()
        rows_height = sum(window.segment_table.rowHeight(row) for row in range(6))
        self.assertGreaterEqual(visible_height, rows_height)
        self.assertEqual(window.segment_table.verticalScrollBar().maximum(), 0)
        table_bottom = window.segment_table.mapTo(window, window.segment_table.rect().bottomLeft()).y()
        cookie_top = window.cookie_edit.mapTo(window, window.cookie_edit.rect().topLeft()).y()
        self.assertGreater(cookie_top, table_bottom)
        self.assertGreater(window.root_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(window.page.width(), window.root_scroll.viewport().width())
        window.root_scroll.verticalScrollBar().setValue(
            window.root_scroll.verticalScrollBar().maximum()
        )
        self.application.processEvents()
        button_bottom = window.download_button.mapTo(
            window.root_scroll.viewport(),
            window.download_button.rect().bottomLeft(),
        ).y()
        self.assertLess(button_bottom, window.root_scroll.viewport().height())
        window.close()

    def test_default_size_shows_the_download_button_without_outer_scrolling(self) -> None:
        window = MainWindow()
        window.resize(880, 980)
        window.show()
        self.application.processEvents()
        button_bottom = window.download_button.mapTo(
            window.root_scroll.viewport(),
            window.download_button.rect().bottomLeft(),
        ).y()
        self.assertEqual(window.minimumSize().width(), 760)
        self.assertEqual(window.minimumSize().height(), 640)
        self.assertEqual(window.root_scroll.verticalScrollBar().maximum(), 0)
        self.assertLess(button_bottom, window.root_scroll.viewport().height())
        window.close()

    def test_video_info_preview_appears_after_metadata_is_applied(self) -> None:
        window = MainWindow()
        info = VideoInfo(
            "https://youtu.be/abcdefghijk",
            "abcdefghijk",
            "미리보기 제목",
            "테스트 채널",
            123,
            "not_live",
        )
        self.assertTrue(window.video_info_card.isHidden())
        with patch.object(window, "_load_video_thumbnail"):
            window._render_video_info(info)
        self.assertFalse(window.video_info_card.isHidden())
        self.assertEqual(window.video_title.text(), "미리보기 제목")
        self.assertIn("테스트 채널", window.video_metadata.text())
        self.assertIn("00:02:03", window.video_metadata.text())
        window.close()

    def test_download_waits_for_matching_video_info(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self._window_with_two_rows(directory)
            window._tools_ready = True
            with (
                patch("ytdownloader.gui.discover_tools", return_value=Mock()),
                patch.object(window, "_request_video_info") as request_info,
            ):
                window._start_download()
            request_info.assert_called_once_with(for_download=True)
            self.assertIsNone(window._process)
            window.close()

    def test_initial_size_is_limited_to_the_available_screen(self) -> None:
        self.assertEqual(_initial_window_size(QSize(1920, 1080)), QSize(880, 980))
        self.assertEqual(_initial_window_size(QSize(800, 720)), QSize(760, 656))
        self.assertEqual(_initial_window_size(QSize(700, 600)), QSize(760, 640))

    def test_wheel_at_segment_table_boundary_scrolls_the_outer_page(self) -> None:
        window = MainWindow()
        window.resize(window.minimumSize())
        for _ in range(12):
            window._add_segment_row()
        window.show()
        self.application.processEvents()
        inner_scroll = window.segment_table.verticalScrollBar()
        outer_scroll = window.root_scroll.verticalScrollBar()
        inner_scroll.setValue(inner_scroll.maximum())
        outer_scroll.setValue(0)
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(window.segment_table.viewport(), event)
        self.application.processEvents()
        self.assertGreater(outer_scroll.value(), 0)
        window.close()

    def test_delayed_kill_only_targets_the_cancelled_process(self) -> None:
        window = MainWindow()
        cancelled_process = Mock()
        cancelled_process.state.return_value = QProcess.ProcessState.Running
        current_process = Mock()
        window._process = current_process

        window._kill_process_if_running(cancelled_process)

        cancelled_process.kill.assert_called_once_with()
        current_process.kill.assert_not_called()
        window._process = None
        window.close()

    def test_cancel_at_process_boundary_stops_the_pending_queue(self) -> None:
        window = MainWindow()
        process = Mock()
        process.state.return_value = QProcess.ProcessState.NotRunning
        process.readAllStandardOutput.return_value = b""
        process.readAllStandardError.return_value = b""
        window._process = process
        window._pending_requests = [Mock()]
        window._active_tools = Mock()
        window._current_job_number = 1
        window._total_jobs = 2

        window._cancel_download()

        self.assertTrue(window._cancel_requested)
        self.assertEqual(window._pending_requests, [])
        with patch.object(window, "_start_next_request") as start_next:
            window._download_finished(0, QProcess.ExitStatus.NormalExit)
        start_next.assert_not_called()
        self.assertEqual(window.status_label.text(), "다운로드를 취소했습니다.")
        window.close()

    def test_crashed_process_is_not_reported_as_success_with_zero_exit_code(self) -> None:
        window = MainWindow()
        process = Mock()
        process.readAllStandardOutput.return_value = b""
        process.readAllStandardError.return_value = b""
        window._process = process
        window._active_tools = Mock()
        window._current_job_number = 1
        window._total_jobs = 1

        window._download_finished(0, QProcess.ExitStatus.CrashExit)

        self.assertEqual(window.status_label.text(), "다운로드에 실패했습니다.")
        self.assertIn("비정상 종료", window.log.toPlainText())
        window.close()

    def test_child_editors_do_not_intercept_job_file_drop(self) -> None:
        window = MainWindow()
        window._add_segment_row()
        editors = [
            window.url_edit,
            window.output_edit,
            window.cookie_edit,
            window.log,
            window.segment_table.cellWidget(0, 0),
            window.segment_table.cellWidget(0, 1),
            window.segment_table.cellWidget(0, 2),
        ]
        self.assertTrue(window.acceptDrops())
        self.assertTrue(all(not editor.acceptDrops() for editor in editors))
        window.close()

    def test_valid_output_directory_is_remembered_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow()
            window._settings = Mock()
            window.output_edit.setText(directory)
            window._remember_output_directory()
            window._settings.setValue.assert_called_once_with(
                "outputDirectory",
                str(Path(directory).resolve()),
            )
            window.close()

    def test_job_file_populates_url_and_segment_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "불러오기.ytdjob"
            document = create_job_document(
                "https://youtu.be/abcdefghijk",
                [("도입, 인사", "123", "230"), ("핵심", "13033", "13500")],
            )
            save_job_file(path, document)
            window = MainWindow()

            self.assertTrue(window._load_job_from_path(path))
            self.assertEqual(window.url_edit.text(), "https://youtu.be/abcdefghijk")
            self.assertEqual(window.segment_table.rowCount(), 2)
            self.assertEqual(window._segment_text(0, 0), "도입, 인사")
            self.assertEqual(window._segment_text(0, 1), "00:01:23")
            self.assertEqual(window._segment_text(1, 1), "01:30:33")
            window.close()

    def test_declining_import_preserves_existing_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "교체.ytdjob"
            document = create_job_document("https://youtu.be/abcdefghijk", [("새 구간", "10", "20")])
            save_job_file(path, document)
            window = MainWindow()
            window.url_edit.setText("https://youtube.com/watch?v=기존주소")
            window._add_segment_row()
            window.segment_table.cellWidget(0, 0).setText("기존 구간")

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                self.assertFalse(window._load_job_from_path(path))

            self.assertEqual(window.url_edit.text(), "https://youtube.com/watch?v=기존주소")
            self.assertEqual(window._segment_text(0, 0), "기존 구간")
            window.close()

    def test_only_one_local_ytdjob_file_is_accepted_for_drop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job_path = Path(directory) / "작업.ytdjob"
            job_path.write_text("{}", encoding="utf-8")
            text_path = Path(directory) / "작업.txt"
            text_path.write_text("{}", encoding="utf-8")
            window = MainWindow()

            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(str(job_path))])
            self.assertEqual(window._job_path_from_mime_data(mime_data), job_path)
            mime_data.setUrls([QUrl.fromLocalFile(str(text_path))])
            self.assertIsNone(window._job_path_from_mime_data(mime_data))
            mime_data.setUrls([QUrl.fromLocalFile(str(job_path)), QUrl.fromLocalFile(str(job_path))])
            self.assertIsNone(window._job_path_from_mime_data(mime_data))
            window.close()

    def test_drop_event_loads_a_ytdjob_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job_path = Path(directory) / "드래그.ytdjob"
            job_path.write_text("{}", encoding="utf-8")
            mime_data = QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(str(job_path))])
            window = MainWindow()

            drag_event = QDragEnterEvent(
                QPoint(10, 10),
                Qt.DropAction.CopyAction,
                mime_data,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            window.dragEnterEvent(drag_event)
            self.assertTrue(drag_event.isAccepted())
            self.assertTrue(window.form_card.property("jobDropActive"))

            drop_event = QDropEvent(
                QPointF(10, 10),
                Qt.DropAction.CopyAction,
                mime_data,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            with patch.object(window, "_load_job_from_path", return_value=True) as load_job:
                window.dropEvent(drop_event)
            self.assertTrue(drop_event.isAccepted())
            self.assertFalse(window.form_card.property("jobDropActive"))
            load_job.assert_called_once_with(job_path)
            window.close()

    def test_segment_help_is_available_from_question_mark(self) -> None:
        window = MainWindow()
        self.assertEqual(window.segment_help_button.text(), "?")
        self.assertIn("13033 → 01:30:33", window.segment_help_button.toolTip())
        self.assertIn(".ytdjob", window.segment_help_button.toolTip())
        window.close()


if __name__ == "__main__":
    unittest.main()
