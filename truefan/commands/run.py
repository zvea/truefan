"""The run subcommand: start the fan control daemon."""

import logging
import sys
from logging.handlers import SysLogHandler
from pathlib import Path

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.commands import load_and_validate
from truefan.daemon import run as daemon_run
from truefan.pidfile import PidFile, PidFileError


def run_daemon(
    config_path: Path,
    pid_path: Path | None = None,
    conn: BmcConnection | None = None,
) -> None:
    """Validate config, acquire the PID lock, and start the daemon.

    Checks config exists, acquires the PID lock, validates the config
    against live hardware, then starts the watchdog. Prints errors to
    stderr and exits if any step fails.
    """
    if not config_path.exists():
        print(
            f"Config not found: {config_path}\n"
            f"Run 'truefan init' to generate one.",
            file=sys.stderr,
        )
        sys.exit(1)

    if conn is None:
        conn = IpmitoolConnection()

    if pid_path is not None:
        try:
            with PidFile(pid_path):
                load_and_validate(config_path, conn)
                _start(config_path, conn)
        except PidFileError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
    else:
        load_and_validate(config_path, conn)
        _start(config_path, conn)


def _start(config_path: Path, conn: BmcConnection) -> None:
    """Start the watchdog which supervises the daemon."""
    handler = SysLogHandler(address="/dev/log", facility=SysLogHandler.LOG_DAEMON)
    handler.ident = "truefan: "
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    from truefan.watchdog import start

    start(
        daemon_fn=lambda: daemon_run(config_path, conn=conn),
        conn=conn,
    )
