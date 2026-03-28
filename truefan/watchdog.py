"""Watchdog parent process that supervises the daemon."""

from pathlib import Path


def start(config_path: Path) -> None:
    """Spawn and monitor the daemon.

    If the daemon exits unexpectedly, sets all fans to 100% and restarts it.
    On SIGTERM, forwards the signal to the child, waits for clean exit,
    then exits. Does not return under normal operation.
    """
    raise NotImplementedError
