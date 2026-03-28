"""Tests for truefan.commands.reload."""

import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

from truefan.commands.reload import run_reload
from truefan.pidfile import PidFile


# ---------------------------------------------------------------------------
# #### run_reload
# ---------------------------------------------------------------------------

class TestRunReload:
    """Tests for run_reload."""

    def test_no_pid_file(self, tmp_path: Path) -> None:
        """Exits with error when PID file doesn't exist."""
        with pytest.raises(SystemExit):
            run_reload(tmp_path / "nonexistent.pid")

    def test_stale_pid_file(self, tmp_path: Path) -> None:
        """Exits with error when PID file exists but is not locked."""
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text("99999\n")
        with pytest.raises(SystemExit):
            run_reload(pid_path)

    def test_sends_sighup(self, tmp_path: Path) -> None:
        """Sends SIGHUP to the PID in the file."""
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with patch("truefan.commands.reload.os.kill") as mock_kill:
                run_reload(pid_path)
                mock_kill.assert_called_once_with(os.getpid(), signal.SIGHUP)

    def test_process_not_found(self, tmp_path: Path) -> None:
        """Exits with error when the PID doesn't correspond to a process."""
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with patch("truefan.commands.reload.os.kill", side_effect=ProcessLookupError):
                with pytest.raises(SystemExit):
                    run_reload(pid_path)

    def test_permission_denied(self, tmp_path: Path) -> None:
        """Exits with error when we can't signal the process."""
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with patch("truefan.commands.reload.os.kill", side_effect=PermissionError):
                with pytest.raises(SystemExit):
                    run_reload(pid_path)
