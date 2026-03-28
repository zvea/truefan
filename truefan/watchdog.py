"""Watchdog parent process that supervises the daemon."""

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Callable

from truefan.bmc import BmcConnection
from truefan.fans import set_full_speed
from truefan.metrics import send_daemon_restart

_log: logging.Logger = logging.getLogger(__name__)


def start(
    daemon_fn: Callable[[], None],
    conn: BmcConnection,
    restart_delay: float = 2.0,
) -> None:
    """Spawn and monitor the daemon.

    Forks a child to run daemon_fn. If the child exits unexpectedly,
    sets all fans to 100% and restarts. On SIGTERM or SIGHUP, forwards
    the signal to the child.
    """
    child_pid: int = 0

    def _forward_signal(signum: int, frame: object) -> None:
        """Forward a signal to the child process."""
        nonlocal child_pid
        if child_pid > 0:
            try:
                os.kill(child_pid, signum)
            except ProcessLookupError:
                pass
        if signum == signal.SIGTERM:
            # Wait for child to exit, then exit ourselves.
            if child_pid > 0:
                try:
                    os.waitpid(child_pid, 0)
                except ChildProcessError:
                    pass
            sys.exit(0)

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGHUP, _forward_signal)

    while True:
        child_pid = os.fork()
        if child_pid == 0:
            # Child process — run the daemon.
            try:
                daemon_fn()
                os._exit(0)
            except SystemExit as e:
                os._exit(e.code if isinstance(e.code, int) else 0)
            except Exception:
                _log.exception("Daemon crashed")
                os._exit(1)

        # Parent process — wait for child.
        _log.info("Daemon started (PID %d)", child_pid)
        _, status = os.waitpid(child_pid, 0)
        child_pid = 0

        if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
            _log.info("Daemon exited cleanly")
            return

        _log.warning(
            "Daemon exited unexpectedly (status %d), setting fans to 100%%",
            status,
        )
        set_full_speed(conn)
        send_daemon_restart()
        _log.info("Restarting daemon in %.0fs...", restart_delay)
        time.sleep(restart_delay)
