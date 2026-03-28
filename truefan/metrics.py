"""Statsd metrics for Netdata integration."""

from typing import Final

DEFAULT_STATSD_HOST: Final[str] = "127.0.0.1"
DEFAULT_STATSD_PORT: Final[int] = 8125


def send_target_rpm(
    fan_name: str,
    target_rpm: int,
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Send a target RPM gauge to Netdata's statsd listener over UDP.

    Fire-and-forget: errors are logged but never raised.
    """
    raise NotImplementedError
