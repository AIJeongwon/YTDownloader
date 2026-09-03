from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytdownloader.process_control import terminate_process_tree


class ProcessControlTests(unittest.TestCase):
    def test_windows_tree_termination_uses_trusted_system_taskkill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            system_directory = Path(directory)
            executable = system_directory / "taskkill.exe"
            executable.write_bytes(b"taskkill")
            completed = subprocess.CompletedProcess([], 0)
            with (
                patch("ytdownloader.process_control.os.name", "nt"),
                patch("ytdownloader.process_control._windows_system_directory", return_value=system_directory),
                patch("ytdownloader.process_control.subprocess.run", return_value=completed) as run,
            ):
                self.assertTrue(terminate_process_tree(1234))

            arguments = run.call_args.args[0]
            self.assertEqual(arguments, [str(executable), "/PID", "1234", "/T", "/F"])
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_invalid_process_id_is_rejected_without_starting_a_program(self) -> None:
        with patch("ytdownloader.process_control.os.name", "nt"), patch(
            "ytdownloader.process_control.subprocess.run"
        ) as run:
            self.assertFalse(terminate_process_tree(0))
            run.assert_not_called()

    def test_taskkill_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            system_directory = Path(directory)
            (system_directory / "taskkill.exe").write_bytes(b"taskkill")
            with (
                patch("ytdownloader.process_control.os.name", "nt"),
                patch("ytdownloader.process_control._windows_system_directory", return_value=system_directory),
                patch(
                    "ytdownloader.process_control.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 1),
                ),
            ):
                self.assertFalse(terminate_process_tree(1234))


if __name__ == "__main__":
    unittest.main()
