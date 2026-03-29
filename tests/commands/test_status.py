"""Tests for truefan.commands.status."""

from pathlib import Path

import pytest

from truefan.commands.status import run_status
from truefan.pidfile import PidFile


# ---------------------------------------------------------------------------
# #### run_status
# ---------------------------------------------------------------------------

class TestRunStatus:
    """Tests for run_status."""

    def test_no_pid_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 with 'Not running' when PID file doesn't exist."""
        with pytest.raises(SystemExit) as exc_info:
            run_status(tmp_path / "nonexistent.pid")
        assert exc_info.value.code == 1
        assert "Not running" in capsys.readouterr().out

    def test_stale_pid_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 1 with 'stale' when PID file exists but lock not held."""
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text("99999\n")
        with pytest.raises(SystemExit) as exc_info:
            run_status(pid_path)
        assert exc_info.value.code == 1
        assert "stale" in capsys.readouterr().out

    def test_running(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Exits 0 with PID when daemon is running."""
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            run_status(pid_path)
        out = capsys.readouterr().out
        assert "Running" in out
        assert "PID" in out
