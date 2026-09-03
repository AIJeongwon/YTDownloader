from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ytdownloader.job_files import JobFileError, create_job_document, load_job_file, save_job_file


class JobFileTests(unittest.TestCase):
    def test_utf8_job_file_round_trip_preserves_commas_in_titles(self) -> None:
        document = create_job_document(
            "https://youtu.be/abcdefghijk",
            [
                ("도입, 인사", "123", "230"),
                ("핵심 장면", "13033", "01:35:00"),
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            saved_path = save_job_file(Path(directory) / "작업 목록", document)
            self.assertEqual(saved_path.suffix, ".ytdjob")
            loaded = load_job_file(saved_path)

            self.assertEqual(loaded, document)
            raw_document = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(raw_document["segments"][0]["title"], "도입, 인사")
            self.assertEqual(raw_document["segments"][0]["start"], "00:01:23")
            self.assertEqual(raw_document["segments"][1]["start"], "01:30:33")

    def test_invalid_segment_is_rejected_before_document_is_created(self) -> None:
        with self.assertRaisesRegex(JobFileError, "종료 시간"):
            create_job_document(
                "https://youtu.be/abcdefghijk",
                [("잘못된 구간", "00:02:00", "00:01:00")],
            )

    def test_excessively_long_time_is_reported_as_a_job_file_error(self) -> None:
        with self.assertRaisesRegex(JobFileError, "1000시간 미만"):
            create_job_document(
                "https://youtu.be/abcdefghijk",
                [("긴 시간", "9" * 5000, "10")],
            )

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "중복.ytdjob"
            path.write_text(
                '{"version":1,"url":"https://youtu.be/abcdefghijk",'
                '"url":"https://youtu.be/abcdefghijk","segments":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(JobFileError, "중복"):
                load_job_file(path)

    def test_unknown_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "알 수 없는 항목.ytdjob"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "url": "https://youtu.be/abcdefghijk",
                        "segments": [],
                        "cookie": "포함하면 안 됨",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(JobFileError, "항목만"):
                load_job_file(path)


if __name__ == "__main__":
    unittest.main()
