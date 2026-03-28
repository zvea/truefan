"""PID file with OS-level locking for single-instance enforcement."""

import fcntl
import os
from pathlib import Path
from typing import Final

PID_PATH: Final[Path] = Path("/var/run/truefan.pid")


class PidFileError(Exception):
    """Raised when the PID file is already locked by another process."""


def is_locked(path: Path = PID_PATH) -> bool:
    """Check whether the PID file is currently locked by another process."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


class PidFile:
    """Context manager that acquires an exclusive lock on a PID file.

    The OS releases the lock automatically on process exit, including
    kill -9. The PID file is written to /var/run by default.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> "PidFile":
        """Acquire the lock and write the current PID."""
        self._fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._fd)
            self._fd = None
            raise PidFileError(
                f"Another instance is already running (lock held on {self._path})"
            )
        os.ftruncate(self._fd, 0)
        os.write(self._fd, f"{os.getpid()}\n".encode())
        os.fsync(self._fd)
        return self

    def __exit__(self, *args: object) -> None:
        """Release the lock and remove the PID file."""
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
            self._path.unlink(missing_ok=True)
