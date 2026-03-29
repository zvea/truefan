"""The reload subcommand: send SIGHUP to the running daemon."""

import os
import signal
import sys
from pathlib import Path

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.commands import load_and_validate
from truefan.pidfile import is_locked


def run_reload(
    config_path: Path,
    pid_path: Path,
    conn: BmcConnection | None = None,
) -> None:
    """Validate config, then send SIGHUP to the running daemon.

    Refuses to reload if the config is broken or doesn't match hardware.
    """
    if not pid_path.exists():
        print(f"No daemon is running ({pid_path} not found).", file=sys.stderr)
        sys.exit(1)

    if not is_locked(pid_path):
        print(f"No daemon is running ({pid_path} is stale).", file=sys.stderr)
        sys.exit(1)

    if conn is None:
        conn = IpmitoolConnection()

    load_and_validate(config_path, conn)

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
