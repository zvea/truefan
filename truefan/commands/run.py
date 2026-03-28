"""The run subcommand: start the fan control daemon."""

import logging
import sys
from pathlib import Path

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.daemon import run as daemon_run
from truefan.pidfile import PidFile, PidFileError


def run_daemon(config_path: Path, pid_path: Path | None = None) -> None:
    """Acquire the PID lock and start the watchdog + daemon."""
    if not config_path.exists():
        print(
            f"Config not found: {config_path}\n"
            f"Run 'truefan init' to generate one.",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = IpmitoolConnection()

    if pid_path is not None:
        try:
            with PidFile(pid_path):
                _start(config_path, conn)
        except PidFileError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
    else:
        _start(config_path, conn)


def _start(config_path: Path, conn: BmcConnection) -> None:
    """Start the watchdog which supervises the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    from truefan.watchdog import start

    start(
        daemon_fn=lambda: daemon_run(config_path, conn=conn),
        conn=conn,
    )
