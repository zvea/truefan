"""The stop subcommand: stop the running daemon."""

import os
import signal
import sys
import time
from pathlib import Path
from typing import Final

from truefan.pidfile import is_locked

_POLL_INTERVAL: Final = 0.1


def run_stop(pid_path: Path, timeout: float = 5.0) -> None:
    """Send SIGTERM to the running daemon and wait for it to exit.

    Reads the PID from the file, verifies the lock is held, sends
    SIGTERM, then polls until the lock is released or the timeout
    expires.
    """
    if not pid_path.exists():
        print(f"No daemon is running ({pid_path} not found).", file=sys.stderr)
        sys.exit(1)

    if not is_locked(pid_path):
        print(f"No daemon is running ({pid_path} is stale).", file=sys.stderr)
        sys.exit(1)

    pid = int(pid_path.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        # Process already gone — treat as success.
        print(f"Daemon (PID {pid}) already stopped.")
        return
    except PermissionError:
        print(f"Permission denied sending signal to PID {pid}.", file=sys.stderr)
        sys.exit(1)

    # Wait for the lock to be released.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_locked(pid_path):
            print(f"Daemon (PID {pid}) stopped.")
            return
        time.sleep(_POLL_INTERVAL)

    print(
        f"Timed out waiting for daemon (PID {pid}) to exit.",
        file=sys.stderr,
    )
    sys.exit(1)
