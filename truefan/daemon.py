"""Main daemon poll loop."""

import logging
import signal
import time
from importlib.metadata import version
from collections import deque
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Callable

from truefan.bmc import BmcConnection, IpmitoolConnection, parse_fan_sel_events
from truefan.commands.netdata import check_netdata_config
from truefan.calibrate import remove_lowest_setpoint
from truefan.config import Config, FanConfig, load_config, save_config
from truefan.control import ZoneDuty, compute_thermal_load, compute_zone_duties
from truefan.fans import (
    ZONES,
    FanRpm,
    enable_manual_control,
    fan_zone,
    read_fan_rpms,
    reset_thresholds,
    set_full_speed,
    set_zone_duty,
)
from truefan.metrics import send_actual_rpm, send_min_setpoint_rpm, send_stalls, send_target_rpm, send_temperature, send_thermal_load, send_uptime, send_zone_duty
from truefan.sensors import SensorBackend, SensorReading, available_backends

_log: logging.Logger = logging.getLogger(__name__)


class _Shutdown(Exception):
    """Raised to cleanly exit the poll loop."""


class _Reload(Exception):
    """Raised to trigger config reload."""


class _DumpState(Exception):
    """Raised to log current daemon state."""


def _read_all_sensors(backends: list[SensorBackend]) -> list[SensorReading]:
    """Read from all backends, skipping individual failures."""
    readings: list[SensorReading] = []
    for backend in backends:
        try:
            readings.extend(backend.scan())
        except (_Shutdown, _Reload, _DumpState):
            raise
        except Exception as e:
            _log.warning("Sensor backend %s failed: %s", type(backend).__name__, e)
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


def _recover_fan(
    fan_name: str,
    fans: dict[str, FanConfig],
    reassert_zones: set[str],
) -> bool:
    """Remove the lowest setpoint for a fan and mark its zone for re-assertion.

    Returns True if a setpoint was removed.
    """
    fan_config = fans.get(fan_name)
    if fan_config is None:
        return False
    new_fan_config = remove_lowest_setpoint(fan_config)
    if new_fan_config is fan_config:
        return False
    _log.warning(
        "Removed lowest setpoint for %s, new min duty %d%%",
        fan_name, min(new_fan_config.setpoints),
    )
    fans[fan_name] = new_fan_config
    reassert_zones.add(fan_config.zone)
    return True


def _detect_stalls(
    rpms: list[FanRpm],
    fans: dict[str, FanConfig],
    reassert_zones: set[str],
) -> set[str]:
    """Detect fans with zero RPM (real-time stall detection).

    Returns the set of fan names that stalled.
    """
    stalled: set[str] = set()
    for fan_rpm in rpms:
        if fan_rpm.rpm > 0:
            continue
        if fan_rpm.name not in fans:
            continue
        _log.warning("Fan %s stalled (0 RPM)", fan_rpm.name)
        if _recover_fan(fan_rpm.name, fans, reassert_zones):
            stalled.add(fan_rpm.name)
    return stalled


def _check_sel_events(
    conn: BmcConnection,
    fans: dict[str, FanConfig],
    reassert_zones: set[str],
    last_sel_id: int,
    already_recovered: set[str],
) -> tuple[int, set[str]]:
    """Check IPMI SEL for fan assertions the daemon missed.

    Returns the updated last-seen SEL entry ID and the set of fan names
    that stalled via SEL.  Fans already handled by real-time stall
    detection (in *already_recovered*) are skipped.
    """
    stalled: set[str] = set()
    try:
        entries = conn.read_sel()
    except Exception as e:
        _log.warning("Failed to read IPMI SEL: %s", e)
        return last_sel_id, stalled

    events = parse_fan_sel_events(entries)
    new_last_id = last_sel_id

    for event in events:
        if event.entry_id <= last_sel_id:
            continue
        new_last_id = max(new_last_id, event.entry_id)
        if event.fan_name in already_recovered or event.fan_name in stalled:
            continue
        _log.warning(
            "Fan %s stall detected via BMC event log: %s",
            event.fan_name, event.detail,
        )
        if _recover_fan(event.fan_name, fans, reassert_zones):
            stalled.add(event.fan_name)

    return new_last_id, stalled


def _detect_fan_problems(
    rpms: list[FanRpm],
    config: Config,
    config_path: Path,
    conn: BmcConnection,
    prev_zone_duties: dict[str, int],
    last_sel_id: int,
) -> tuple[Config, int, dict[str, int]]:
    """Detect fan problems via RPM and IPMI SEL, recover bad setpoints.

    Two detection methods, same recovery:

    - **Real-time:** RPM reads zero during this poll — direct stall.
    - **IPMI SEL:** the BMC logged a fan assertion between polls that
      the daemon missed (the BMC recovered the fan before we noticed).

    In both cases: remove the fan's lowest setpoint, re-assert the
    intended duty for the zone, and persist the updated config.

    Returns the (possibly updated) config, the new last-seen SEL ID,
    and a dict mapping fan name to stall count for this cycle.
    """
    fans = dict(config.fans)
    reassert_zones: set[str] = set()

    # Real-time stall detection.
    rt_stalled = _detect_stalls(rpms, fans, reassert_zones)
    already_recovered = {
        name for name, cfg in fans.items()
        if cfg is not config.fans.get(name)
    }

    # SEL-based detection (catches stalls the BMC handled between polls).
    last_sel_id, sel_stalled = _check_sel_events(
        conn, fans, reassert_zones, last_sel_id, already_recovered,
    )

    # Build per-fan stall counts.
    stall_counts: dict[str, int] = {}
    for name in config.fans:
        count = (1 if name in rt_stalled else 0) + (1 if name in sel_stalled else 0)
        stall_counts[name] = count

    # Re-assert intended duty for affected zones to reclaim control.
    for zone in reassert_zones:
        intended_duty = prev_zone_duties.get(zone)
        if intended_duty is not None:
            set_zone_duty(conn, zone, intended_duty)
            send_zone_duty(zone, intended_duty)

    changed = any(fans[name] is not config.fans.get(name) for name in fans)
    if changed:
        config = replace(config, fans=MappingProxyType(fans))
        save_config(config_path, config)
        _log.info("Config saved after fan recovery")

    return config, last_sel_id, stall_counts


def run(
    config_path: Path,
    conn: BmcConnection | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Start the fan control loop.

    Loads config, enables manual fan control, enters the poll loop,
    and sets fans to full speed on exit. Handles SIGHUP (config reload),
    SIGUSR1 (state dump to syslog). Does not return under normal operation.
    """
    config = load_config(config_path)

    if conn is None:
        conn = IpmitoolConnection()

    # Set up signal handlers.
    def _handle_sigterm(signum: int, frame: object) -> None:
        raise _Shutdown()

    def _handle_sighup(signum: int, frame: object) -> None:
        raise _Reload()

    def _handle_sigusr1(signum: int, frame: object) -> None:
        raise _DumpState()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, _handle_sighup)
    signal.signal(signal.SIGUSR1, _handle_sigusr1)

    _log.info("truefan %s starting", version("truefan"))

    # Check Netdata config (advisory — never blocks startup).
    netdata_warnings = check_netdata_config()
    if netdata_warnings:
        for warning in netdata_warnings:
            _log.warning("%s", warning)
    else:
        _log.info("Netdata config check passed")

    # Take over fan control.
    _log.info("Resetting BMC thresholds")
    reset_thresholds(conn)
    _log.info("Enabling manual fan control")
    enable_manual_control(conn)

    backends = available_backends(conn)

    prev_zone_duties: dict[str, int] = {}
    # Sliding window of (timestamp, duty) per zone for conservative spindown.
    duty_history: dict[str, deque[tuple[float, int]]] = {}
    now = time.monotonic
    start_time = now()
    # Seed last_sel_id so we only process SEL events that occur after startup.
    # Without this, all historical events would be reprocessed on every start.
    try:
        existing_entries = conn.read_sel()
        last_sel_id = max((e.entry_id for e in existing_entries), default=0)
    except Exception:
        last_sel_id = 0

    # Last poll state, used by SIGUSR1 state dump.
    last_readings: list[SensorReading] = []
    last_zone_duties: dict[str, ZoneDuty] = {}

    try:
        while True:
            try:
                # Read sensors.
                readings = _read_all_sensors(backends)

                # Push per-sensor metrics.
                for reading in readings:
                    send_temperature(reading.name, reading.temperature)
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
                    send_actual_rpm(fan_rpm.name, fan_rpm.rpm)
                    fan_config = config.fans.get(fan_rpm.name)
                    if fan_config is None:
                        continue
                    if fan_config.setpoints:
                        min_duty = min(fan_config.setpoints)
                        send_min_setpoint_rpm(fan_rpm.name, fan_config.setpoints[min_duty])
                    current_duty = prev_zone_duties.get(fan_config.zone)
                    if current_duty is not None:
                        target = fan_config.setpoints.get(current_duty)
                        if target is not None:
                            send_target_rpm(fan_rpm.name, target)

                # Check for stalls (real-time) and BMC events (SEL).
                config, last_sel_id, stall_counts = _detect_fan_problems(
                    rpms, config, config_path, conn, prev_zone_duties,
                    last_sel_id,
                )
                for fan_name, count in stall_counts.items():
                    send_stalls(fan_name, count)

                last_readings = readings
                last_zone_duties = zone_duties

                send_uptime(int(now() - start_time))
                sleep(config.poll_interval_seconds)

            except _DumpState:
                _log.info("State dump — SIGUSR1 received")
                _log.info(
                    "Config: poll_interval=%ds, spindown_window=%ds",
                    config.poll_interval_seconds, config.spindown_window_seconds,
                )
                for reading in last_readings:
                    curve = config.curves.get(reading.sensor_class)
                    if curve is None:
                        continue
                    override = config.sensor_overrides.get(reading.name)
                    load = compute_thermal_load(reading, curve, override)
                    _log.info(
                        "Sensor %s (%s): %.1f°C, %.0f%% load",
                        reading.name, reading.sensor_class, reading.temperature, load,
                    )
                for zone, zd in last_zone_duties.items():
                    _log.info(
                        "Zone %s: %d%% duty (driven by %s at %.1f°C, %.0f%% demand)",
                        zone, zd.duty, zd.sensor_name, zd.temperature, zd.raw_duty,
                    )

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
        for zone in ZONES:
            send_zone_duty(zone, 100)
