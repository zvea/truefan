"""The reload subcommand: send SIGHUP to the running daemon."""

import os
import signal
import sys
from pathlib import Path

from truefan.pidfile import is_locked


def run_reload(pid_path: Path) -> None:
    """Send SIGHUP to the running daemon to reload its config."""
    if not pid_path.exists():
        print(f"No daemon is running ({pid_path} not found).", file=sys.stderr)
        sys.exit(1)

    if not is_locked(pid_path):
        print(f"No daemon is running ({pid_path} is stale).", file=sys.stderr)
        sys.exit(1)

    pid = int(pid_path.read_text().strip())
    try:
        os.kill(pid, signal.SIGHUP)
    except ProcessLookupError:
        print(f"No process with PID {pid}.", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Permission denied sending signal to PID {pid}.", file=sys.stderr)
        sys.exit(1)

    print(f"Sent SIGHUP to daemon (PID {pid}).")
