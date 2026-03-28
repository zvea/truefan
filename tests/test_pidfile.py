"""Tests for truefan.pidfile."""

import os
from pathlib import Path

import pytest

from truefan.pidfile import PidFile, PidFileError, is_locked


# ---------------------------------------------------------------------------
# #### PidFile
# ---------------------------------------------------------------------------

class TestPidFile:
    """Tests for PidFile context manager."""

    def test_writes_pid(self, tmp_path: Path) -> None:
        """PID file contains the current process PID."""
        pid_path = tmp_path / "test.pid"
        with PidFile(pid_path):
            content = pid_path.read_text()
            assert content.strip() == str(os.getpid())

    def test_second_acquire_raises(self, tmp_path: Path) -> None:
        """A second PidFile on the same path raises PidFileError."""
        pid_path = tmp_path / "test.pid"
        with PidFile(pid_path):
            with pytest.raises(PidFileError, match="already running"):
                with PidFile(pid_path):
                    pass

    def test_release_allows_reacquire(self, tmp_path: Path) -> None:
        """After exiting the context manager, the lock can be acquired again."""
        pid_path = tmp_path / "test.pid"
        with PidFile(pid_path):
            pass
        with PidFile(pid_path):
            content = pid_path.read_text()
            assert content.strip() == str(os.getpid())

    def test_removes_file_on_exit(self, tmp_path: Path) -> None:
        """PID file is removed when the context manager exits."""
        pid_path = tmp_path / "test.pid"
        with PidFile(pid_path):
            assert pid_path.exists()
        assert not pid_path.exists()

    def test_file_exists_during_context(self, tmp_path: Path) -> None:
        """PID file exists while the context manager is active."""
        pid_path = tmp_path / "test.pid"
        with PidFile(pid_path):
            assert pid_path.exists()


# ---------------------------------------------------------------------------
# #### is_locked
# ---------------------------------------------------------------------------

class TestIsLocked:
    """Tests for is_locked."""

    def test_not_locked_when_no_file(self, tmp_path: Path) -> None:
        """Returns False when PID file doesn't exist."""
        assert not is_locked(tmp_path / "nonexistent.pid")

    def test_not_locked_when_stale(self, tmp_path: Path) -> None:
        """Returns False when PID file exists but is not locked."""
        pid_path = tmp_path / "test.pid"
        pid_path.write_text("99999\n")
        assert not is_locked(pid_path)

    def test_locked_when_held(self, tmp_path: Path) -> None:
        """Returns True when PID file is locked by another PidFile."""
        pid_path = tmp_path / "test.pid"
        with PidFile(pid_path):
            assert is_locked(pid_path)

    def test_not_locked_after_release(self, tmp_path: Path) -> None:
        """Returns False after the PidFile context exits."""
        pid_path = tmp_path / "test.pid"
        with PidFile(pid_path):
            pass
        assert not is_locked(pid_path)


# ---------------------------------------------------------------------------
# #### PidFile (stale file handling)
# ---------------------------------------------------------------------------

class TestPidFileStale:
    """Tests for PidFile stale file handling."""

    def test_stale_pidfile_is_reacquired(self, tmp_path: Path) -> None:
        """A leftover PID file with no lock is successfully reacquired."""
        pid_path = tmp_path / "test.pid"
        pid_path.write_text("99999\n")
        with PidFile(pid_path):
            content = pid_path.read_text()
            assert content.strip() == str(os.getpid())
