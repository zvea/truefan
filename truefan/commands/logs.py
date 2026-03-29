"""The logs subcommand: show daemon logs via journalctl."""

import os


def run_logs(extra_args: list[str]) -> None:
    """Replace the current process with journalctl filtered to truefan.

    All extra_args are forwarded verbatim to journalctl.
    """
    cmd = ["journalctl", "-t", "truefan", *extra_args]
    os.execvp("journalctl", cmd)
