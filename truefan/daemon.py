"""Main daemon poll loop."""

from pathlib import Path


def run(config_path: Path) -> None:
    """Start the fan control loop.

    Loads config, enables manual fan control, enters the poll loop,
    handles SIGHUP for config reload, and restores automatic control
    on exit. Does not return under normal operation.
    """
    raise NotImplementedError
