"""Tests for truefan.commands.stop."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from truefan.commands.stop import run_stop
from truefan.pidfile import PidFile


# ---------------------------------------------------------------------------
# #### run_stop
# ---------------------------------------------------------------------------

class TestRunStop:
    """Tests for run_stop."""

    def test_no_pid_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits with error when PID file doesn't exist."""
        with pytest.raises(SystemExit) as exc_info:
            run_stop(tmp_path / "nonexistent.pid")
        assert exc_info.value.code == 1
        assert "No daemon is running" in capsys.readouterr().err

    def test_stale_pid_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits with error when PID file exists but lock is not held."""
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text("99999\n")
        with pytest.raises(SystemExit) as exc_info:
            run_stop(pid_path)
        assert exc_info.value.code == 1
        assert "stale" in capsys.readouterr().err

    @patch("truefan.commands.stop.is_locked")
    @patch("truefan.commands.stop.os.kill")
    def test_sends_sigterm_and_waits(
        self, mock_kill: MagicMock, mock_is_locked: MagicMock,
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Sends SIGTERM to the daemon PID and waits for lock release."""
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text(f"{os.getpid()}\n")
        # First call: locked (daemon running). Subsequent: unlocked (exited).
        mock_is_locked.side_effect = [True, False]
        run_stop(pid_path)
        mock_kill.assert_called_once()
        assert "stopped" in capsys.readouterr().out.lower()

    @patch("truefan.commands.stop.is_locked")
    @patch("truefan.commands.stop.os.kill", side_effect=ProcessLookupError)
    def test_process_already_gone(
        self, mock_kill: MagicMock, mock_is_locked: MagicMock,
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Succeeds if process disappears between lock check and kill."""
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text("99999\n")
        mock_is_locked.side_effect = [True, False]
        run_stop(pid_path)
        out = capsys.readouterr().out.lower()
        assert "stopped" in out

    @patch("truefan.commands.stop.is_locked")
    @patch("truefan.commands.stop.os.kill")
    def test_permission_denied(
        self, mock_kill: MagicMock, mock_is_locked: MagicMock,
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits with error when we lack permission to signal the daemon."""
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text("1\n")
        mock_is_locked.return_value = True
        mock_kill.side_effect = PermissionError
        with pytest.raises(SystemExit) as exc_info:
            run_stop(pid_path)
        assert exc_info.value.code == 1
        assert "Permission denied" in capsys.readouterr().err

    @patch("truefan.commands.stop.time.sleep")
    @patch("truefan.commands.stop.is_locked", return_value=True)
    @patch("truefan.commands.stop.os.kill")
    def test_timeout_waiting_for_exit(
        self, mock_kill: MagicMock, mock_is_locked: MagicMock,
        mock_sleep: MagicMock,
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits with error if daemon doesn't stop within the timeout."""
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text(f"{os.getpid()}\n")
        with pytest.raises(SystemExit) as exc_info:
            run_stop(pid_path, timeout=0.0)
        assert exc_info.value.code == 1
        assert "timed out" in capsys.readouterr().err.lower()
