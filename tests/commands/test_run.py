"""Tests for truefan.commands.run."""

from pathlib import Path

import pytest

from truefan.commands.run import run_daemon
from truefan.pidfile import PidFile


# ---------------------------------------------------------------------------
# #### run_daemon
# ---------------------------------------------------------------------------

class TestRunDaemon:
    """Tests for run_daemon."""

    def test_refuses_missing_config(self, tmp_path: Path) -> None:
        """Exits with error when config file doesn't exist."""
        with pytest.raises(SystemExit):
            run_daemon(tmp_path / "nonexistent.toml")

    def test_refuses_when_locked(self, tmp_path: Path) -> None:
        """Exits with error when PID file is already locked."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("poll_interval_seconds = 5\n")
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with pytest.raises(SystemExit):
                run_daemon(cfg, pid_path=pid_path)
