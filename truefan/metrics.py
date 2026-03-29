"""Statsd metrics for Netdata integration."""

import logging
import socket
from typing import Final

DEFAULT_STATSD_HOST: Final = "127.0.0.1"
DEFAULT_STATSD_PORT: Final = 8125

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
    except OSError as e:
        _log.warning("Failed to send statsd metric: %s: %s", msg, e)


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


def send_thermal_load(
    sensor_name: str,
    load_pct: float,
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Send a per-sensor thermal load gauge (0-100%)."""
    _send(f"truefan.sensor.{sensor_name}.thermal_load:{load_pct:.0f}|g", host, port)


def send_temperature(
    sensor_name: str,
    temp_c: float,
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Send a per-sensor temperature gauge in °C."""
    _send(f"truefan.sensor.{sensor_name}.temperature:{temp_c:.0f}|g", host, port)


def send_uptime(
    seconds: int,
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Send the daemon uptime gauge in seconds."""
    _send(f"truefan.daemon.uptime:{seconds}|g", host, port)


def send_daemon_restart(
    host: str = DEFAULT_STATSD_HOST,
    port: int = DEFAULT_STATSD_PORT,
) -> None:
    """Increment the daemon restart counter."""
    _send("truefan.daemon.restarts:1|c", host, port)
