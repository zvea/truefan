"""The status subcommand: check whether the daemon is running."""

import sys
from pathlib import Path

from truefan.pidfile import is_locked


def run_status(pid_path: Path) -> None:
    """Print whether the daemon is running and exit with appropriate code.

    Exits 0 if the daemon is running, 1 if not.
    """
    if not pid_path.exists():
        print("Not running.")
        sys.exit(1)

    if not is_locked(pid_path):
        print("Not running (stale PID file).")
        sys.exit(1)

    pid = int(pid_path.read_text().strip())
    print(f"Running (PID {pid}).")
