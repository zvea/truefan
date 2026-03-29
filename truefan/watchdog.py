"""Watchdog parent process that supervises the daemon."""

import ctypes
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Callable, Final

from truefan.bmc import BmcConnection
from truefan.fans import set_full_speed
from truefan.metrics import send_daemon_restart

_log: logging.Logger = logging.getLogger(__name__)

_PR_SET_PDEATHSIG: Final = 1
_libc = ctypes.CDLL("libc.so.6", use_errno=True)


def start(
    daemon_fn: Callable[[], None],
    conn: BmcConnection,
    restart_delay: float = 2.0,
    close_fds: list[int] | None = None,
) -> None:
    """Spawn and monitor the daemon.

    Forks a child to run daemon_fn. If the child exits unexpectedly,
    sets all fans to 100% and restarts. Forwards SIGTERM, SIGHUP, and
    SIGUSR1 to the child. The child sets PR_SET_PDEATHSIG so it receives
    SIGTERM if the watchdog dies. Any file descriptors in close_fds are
    closed in the child after fork (e.g. the PID file lock fd).
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
    signal.signal(signal.SIGUSR1, _forward_signal)

    while True:
        child_pid = os.fork()
        if child_pid == 0:
            # Child process — close inherited fds and request SIGTERM on parent death.
            for fd in close_fds or ():
                try:
                    os.close(fd)
                except OSError:
                    pass
            _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
            try:
                daemon_fn()
                os._exit(0)
            except SystemExit as e:
                os._exit(e.code if isinstance(e.code, int) else 0)
            except Exception as e:
                _log.error("Daemon crashed: %s", e)
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
