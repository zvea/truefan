"""Main daemon poll loop."""

import logging
import signal
import sys
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from truefan.bmc import BmcConnection, IpmitoolConnection
from truefan.calibrate import remove_lowest_setpoint
from truefan.config import Config, ConfigError, FanConfig, load_config, save_config
from truefan.control import ZoneDuty, compute_thermal_load, compute_zone_duties
from truefan.fans import (
    FanRpm,
    enable_manual_control,
    fan_zone,
    read_fan_rpms,
    reset_thresholds,
    set_full_speed,
    set_zone_duty,
)
from truefan.metrics import send_target_rpm, send_thermal_load, send_zone_duty
from truefan.sensors import SensorBackend, SensorReading, available_backends

_log: logging.Logger = logging.getLogger(__name__)


class _Shutdown(Exception):
    """Raised to cleanly exit the poll loop."""


class _Reload(Exception):
    """Raised to trigger config reload."""


def _read_all_sensors(backends: list[SensorBackend]) -> list[SensorReading]:
    """Read from all backends, skipping individual failures."""
    readings: list[SensorReading] = []
    for backend in backends:
        try:
            readings.extend(backend.scan())
        except Exception:
            _log.warning("Sensor backend %s failed", type(backend).__name__, exc_info=True)
    return readings


def _check_class_failures(
    readings: list[SensorReading],
    config: Config,
    zone_duties: dict[str, ZoneDuty],
) -> dict[str, ZoneDuty]:
    """Set zones to 100% if all sensors in a configured class are missing.

    Returns the updated zone_duties dict.
    """
    classes_with_readings = {r.sensor_class for r in readings}
    for sensor_class, curve in config.curves.items():
        if sensor_class not in classes_with_readings:
            _log.warning(
                "All %s sensors failed — setting zones %s to 100%%",
                sensor_class, ", ".join(curve.fan_zones),
            )
            for zone in curve.fan_zones:
                zone_duties[zone] = ZoneDuty(
                    duty=100,
                    sensor_name=f"[all {sensor_class} sensors failed]",
                    temperature=0.0,
                    raw_duty=100.0,
                )
    return zone_duties


def _detect_stalls(
    rpms: list[FanRpm],
    config: Config,
    config_path: Path,
    conn: BmcConnection,
) -> Config:
    """Check fan RPMs for stalls, handle recovery, return possibly-updated config."""
    fans = dict(config.fans)
    changed = False

    for fan_rpm in rpms:
        fan_config = fans.get(fan_rpm.name)
        if fan_config is None:
            continue
        if fan_rpm.rpm > 0:
            continue

        # Fan stalled — kick zone to 100%.
        zone = fan_config.zone
        _log.warning("Fan %s stalled (0 RPM), setting zone %s to 100%%", fan_rpm.name, zone)
        print(f"STALL: {fan_rpm.name} at 0 RPM, zone {zone} set to 100%", file=sys.stderr)
        set_zone_duty(conn, zone, 100)

        # Remove lowest setpoint.
        new_fan_config = remove_lowest_setpoint(fan_config)
        if new_fan_config is not fan_config:
            _log.warning(
                "Removed lowest setpoint for %s, new min duty %d%%",
                fan_rpm.name, min(new_fan_config.setpoints),
            )
            fans[fan_rpm.name] = new_fan_config
            changed = True

    if changed:
        config = replace(config, fans=MappingProxyType(fans))
        save_config(config_path, config)
        _log.info("Config saved after stall recovery")

    return config


def run(
    config_path: Path,
    conn: BmcConnection | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Start the fan control loop.

    Loads config, enables manual fan control, enters the poll loop,
    handles SIGHUP for config reload, and sets fans to full speed on exit.
    Does not return under normal operation.
    """
    config = load_config(config_path)

    if conn is None:
        conn = IpmitoolConnection()

    # Set up signal handlers.
    def _handle_sigterm(signum: int, frame: object) -> None:
        raise _Shutdown()

    def _handle_sighup(signum: int, frame: object) -> None:
        raise _Reload()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, _handle_sighup)

    # Take over fan control.
    _log.info("Resetting BMC thresholds")
    reset_thresholds(conn)
    _log.info("Enabling manual fan control")
    enable_manual_control(conn)

    backends = available_backends(conn)

    # Validate sensor overrides against detected sensors.
    if config.sensor_overrides:
        initial_readings = _read_all_sensors(backends)
        known_sensors = {r.name for r in initial_readings}
        unknown = set(config.sensor_overrides) - known_sensors
        if unknown:
            raise ConfigError(
                f"Sensor overrides reference unknown sensors: {', '.join(sorted(unknown))}"
            )

    prev_zone_duties: dict[str, int] = {}
    # Sliding window of (timestamp, duty) per zone for conservative spindown.
    duty_history: dict[str, deque[tuple[float, int]]] = {}
    now = time.monotonic

    try:
        while True:
            try:
                # Read sensors.
                readings = _read_all_sensors(backends)

                # Push per-sensor thermal load metrics.
                for reading in readings:
                    curve = config.curves.get(reading.sensor_class)
                    if curve is None:
                        continue
                    override = config.sensor_overrides.get(reading.name)
                    send_thermal_load(
                        reading.name,
                        compute_thermal_load(reading, curve, override),
                    )

                # Compute target duties.
                zone_duties = compute_zone_duties(
                    readings, config.curves, config.fans, config.sensor_overrides,
                )
                zone_duties = _check_class_failures(readings, config, zone_duties)

                # Apply spindown window: track recent duties and use the max.
                t = now()
                window = config.spindown_window_seconds
                for zone, zd in zone_duties.items():
                    if zone not in duty_history:
                        duty_history[zone] = deque()
                    duty_history[zone].append((t, zd.duty))
                    # Evict entries older than the window.
                    while duty_history[zone] and duty_history[zone][0][0] < t - window:
                        duty_history[zone].popleft()
                    # Effective duty is the max in the window.
                    effective = max(d for _, d in duty_history[zone])
                    zone_duties[zone] = ZoneDuty(
                        duty=effective,
                        sensor_name=zd.sensor_name,
                        temperature=zd.temperature,
                        raw_duty=zd.raw_duty,
                    )

                # Apply duties (only if changed).
                for zone, zd in zone_duties.items():
                    if prev_zone_duties.get(zone) != zd.duty:
                        _log.info(
                            "Setting zone %s to %d%% (%s at %.1f°C → %.0f%% demand)",
                            zone, zd.duty, zd.sensor_name, zd.temperature, zd.raw_duty,
                        )
                        set_zone_duty(conn, zone, zd.duty)
                        prev_zone_duties[zone] = zd.duty
                    send_zone_duty(zone, zd.duty)

                # Read fan RPMs and push metrics.
                rpms = read_fan_rpms(conn)
                for fan_rpm in rpms:
                    fan_config = config.fans.get(fan_rpm.name)
                    if fan_config is None:
                        continue
                    current_duty = prev_zone_duties.get(fan_config.zone)
                    if current_duty is not None:
                        target = fan_config.setpoints.get(current_duty)
                        if target is not None:
                            send_target_rpm(fan_rpm.name, target)

                # Check for stalls.
                config = _detect_stalls(rpms, config, config_path, conn)

                sleep(config.poll_interval_seconds)

            except _Reload:
                _log.info("SIGHUP received, reloading config")
                config = load_config(config_path)
                backends = available_backends(conn)
                prev_zone_duties.clear()
                duty_history.clear()

    except (_Shutdown, KeyboardInterrupt):
        _log.info("Shutting down")
    finally:
        _log.info("Setting fans to full speed")
        set_full_speed(conn)
