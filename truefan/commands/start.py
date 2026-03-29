"""The start subcommand: daemonize and start the fan control daemon."""

import logging
import os
import sys
from logging.handlers import SysLogHandler
from pathlib import Path

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.commands import load_and_validate
from truefan.daemon import run as daemon_run
from truefan.pidfile import PidFile, PidFileError, is_locked


def run_start(
    config_path: Path,
    pid_path: Path | None = None,
    conn: BmcConnection | None = None,
    foreground: bool = False,
) -> None:
    """Validate config, optionally daemonize, acquire the PID lock, and start.

    In daemon mode (the default), double-forks to detach from the terminal,
    prints the daemon PID, and returns. In foreground mode, runs the watchdog
    in the current process with logging to stderr.
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

    # Fail fast if another instance is already running.
    if pid_path is not None and is_locked(pid_path):
        print(
            f"Another instance is already running (lock held on {pid_path})",
            file=sys.stderr,
        )
        sys.exit(1)

    load_and_validate(config_path, conn)

    if not foreground:
        _daemonize()
        # Only the daemon (grandchild) reaches this point.

    _post_daemonize(config_path, conn, pid_path=pid_path, foreground=foreground)


def _daemonize() -> None:
    """Double-fork to detach from the terminal and become a daemon.

    The original process prints the daemon PID (received via pipe) and
    exits. The intermediate child exits after the second fork. The
    grandchild (the daemon) continues with stdin/stdout/stderr
    redirected to /dev/null.
    """
    r_fd, w_fd = os.pipe()

    # First fork — parent waits for daemon PID, prints it, and exits.
    if os.fork() > 0:
        os.close(w_fd)
        data = b""
        while True:
            chunk = os.read(r_fd, 32)
            if not chunk:
                break
            data += chunk
        os.close(r_fd)
        if data:
            print(f"Daemon started (PID {data.decode().strip()}).")
        os._exit(0)

    # First child — become session leader.
    os.close(r_fd)
    os.setsid()

    # Second fork — intermediate exits, grandchild continues.
    if os.fork() > 0:
        os.close(w_fd)
        os._exit(0)

    # Grandchild (daemon) — send PID back to original process.
    os.write(w_fd, f"{os.getpid()}\n".encode())
    os.close(w_fd)

    # Redirect stdin/stdout/stderr to /dev/null.
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    if devnull > 2:
        os.close(devnull)


def _configure_syslog() -> None:
    """Set up logging to syslog with LOG_DAEMON facility."""
    handler = SysLogHandler(address="/dev/log", facility=SysLogHandler.LOG_DAEMON)
    handler.ident = "truefan: "
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _configure_stderr() -> None:
    """Set up logging to stderr for foreground mode."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _post_daemonize(
    config_path: Path,
    conn: BmcConnection,
    pid_path: Path | None,
    foreground: bool,
) -> None:
    """Acquire the PID lock and start the watchdog.

    Called after daemonizing (or directly in foreground mode). The PID
    file is written here so it contains the daemon's actual PID.
    """
    if foreground:
        _configure_stderr()
    else:
        _configure_syslog()

    # Lazy import: only pull in watchdog when actually starting.
    from truefan.watchdog import start

    if pid_path is not None:
        try:
            with PidFile(pid_path) as pf:
                start(
                    daemon_fn=lambda: daemon_run(config_path, conn=conn),
                    conn=conn,
                    close_fds=[pf.fileno()],
                )
        except PidFileError as e:
            # In daemon mode stderr is closed; log to syslog.
            logging.getLogger(__name__).error(str(e))
            sys.exit(1)
    else:
        start(
            daemon_fn=lambda: daemon_run(config_path, conn=conn),
            conn=conn,
        )
