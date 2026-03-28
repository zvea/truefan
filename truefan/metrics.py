"""Statsd metrics for Netdata integration."""

import logging
import socket
from typing import Final

DEFAULT_STATSD_HOST: Final[str] = "127.0.0.1"
DEFAULT_STATSD_PORT: Final[int] = 8125

_log: logging.Logger = logging.getLogger(__name__)


def _send(
    msg: str,
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Send a statsd message over UDP. Fire-and-forget."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(msg.encode(), (host, port))
    except OSError:
        _log.warning("Failed to send statsd metric: %s", msg, exc_info=True)


def send_target_rpm(
    fan_name: str,
    target_rpm: int,
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Send a per-fan target RPM gauge."""
    _send(f"truefan.fan.{fan_name}.target_rpm:{target_rpm}|g", host, port)


def send_zone_duty(
    zone: str,
    duty: int,
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Send a per-zone duty cycle gauge."""
    _send(f"truefan.zone.{zone}.duty:{duty}|g", host, port)


def send_daemon_restart(
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Increment the daemon restart counter."""
    _send("truefan.daemon.restarts:1|c", host, port)
