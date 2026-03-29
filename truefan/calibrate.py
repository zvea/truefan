"""Fan calibration and stall recovery."""

import time
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Final

from truefan.bmc import BmcConnection
from truefan.config import FanConfig
from truefan.fans import read_fan_rpms, set_full_speed, set_zone_duty

SETTLE_SECONDS: Final[float] = 10.0

DUTY_TEST_POINTS: Final[tuple[int, ...]] = (100, 90, 80, 70, 60, 50, 40, 30, 20, 10)

_TEMP_CRIT_MARGIN: Final[float] = 10.0
_TEMP_DEFAULT_ABORT: Final[float] = 80.0


@dataclass(frozen=True, kw_only=True)
class CalibrationResult:
    """Result of calibrating a single fan."""

    fan_name: str
    zone: str
    setpoints: MappingProxyType[int, int]


class CalibrationError(Exception):
    """Raised when calibration fails (fan never spins, thermal abort, etc.)."""


def _check_temps(conn: BmcConnection) -> None:
    """Abort if any IPMI temperature sensor is dangerously high.

    A sensor is considered dangerous if it's within 10°C of its
    upper_critical threshold, or above 80°C if no threshold is known.
    Sets fans to 100% before raising.
    """
    for sensor in conn.list_temperature_sensors():
        if sensor.temperature is None:
            continue
        if sensor.upper_critical is not None:
            limit = sensor.upper_critical - _TEMP_CRIT_MARGIN
        else:
            limit = _TEMP_DEFAULT_ABORT
        if sensor.temperature >= limit:
            set_full_speed(conn)
            raise CalibrationError(
                f"THERMAL ABORT: {sensor.name} is at {sensor.temperature}°C "
                f"(limit {limit}°C). Fans set to 100%. "
                f"Do not run calibration while the system is under load."
            )


def calibrate_fans(
    conn: BmcConnection,
    fan_zones: dict[str, str],
    sleep: Callable[[float], None] = time.sleep,
) -> list[CalibrationResult]:
    """Run ramp-down calibration for the given fans.

    Steps through duty levels from 100% down, recording RPM at each step.
    Builds a setpoint table per fan. Calibrates one zone at a time while
    keeping other zones at 100%. Monitors IPMI temperatures and aborts
    if any sensor approaches its critical threshold.
    """
    # Group fans by zone.
    zones_to_fans: dict[str, list[str]] = defaultdict(list)
    for fan_name, zone in fan_zones.items():
        zones_to_fans[zone].append(fan_name)

    # Check temps before starting.
    _check_temps(conn)

    results: list[CalibrationResult] = []

    for zone, zone_fan_names in zones_to_fans.items():
        print(f"Calibrating zone {zone} ({', '.join(zone_fan_names)})...")
        # Set all zones to 100% before calibrating this one.
        set_full_speed(conn)
        sleep(SETTLE_SECONDS)

        # Per-fan state for this zone.
        setpoints: dict[str, dict[int, int]] = {name: {} for name in zone_fan_names}
        prev_rpm: dict[str, int] = {}
        stalled_fans: set[str] = set()

        for duty in DUTY_TEST_POINTS:
            set_zone_duty(conn, zone, duty)
            sleep(SETTLE_SECONDS)

            _check_temps(conn)

            rpms = {r.name: r.rpm for r in read_fan_rpms(conn)}

            all_stalled = True
            for fan_name in zone_fan_names:
                if fan_name in stalled_fans:
                    continue
                rpm = rpms.get(fan_name)
                if rpm is None or rpm == 0:
                    print(f"  {fan_name} @ {duty}% = STALLED (zero RPM)")
                    stalled_fans.add(fan_name)
                    continue
                if fan_name in prev_rpm and rpm > prev_rpm[fan_name]:
                    print(f"  {fan_name} @ {duty}% = STALLED (RPM spike)")
                    stalled_fans.add(fan_name)
                    continue
                print(f"  {fan_name} @ {duty}% = {rpm} RPM")
                setpoints[fan_name][duty] = rpm
                prev_rpm[fan_name] = rpm
                all_stalled = False

            if all_stalled:
                break

        # Build results.
        for fan_name in zone_fan_names:
            fan_setpoints = setpoints[fan_name]
            if not fan_setpoints:
                raise CalibrationError(
                    f"Fan {fan_name} never produced a valid RPM reading"
                )
            results.append(CalibrationResult(
                fan_name=fan_name,
                zone=zone,
                setpoints=MappingProxyType(fan_setpoints),
            ))

    # Restore full speed after calibration.
    set_full_speed(conn)

    return results


def remove_lowest_setpoint(fan_config: FanConfig) -> FanConfig:
    """Return a new FanConfig with the lowest setpoint removed.

    Used during stall recovery to raise the effective minimum duty.
    Never removes the last setpoint, and never removes the 100% setpoint.
    """
    if len(fan_config.setpoints) <= 1:
        return fan_config
    duties = sorted(fan_config.setpoints)
    lowest = duties[0]
    if lowest == 100:
        return fan_config
    new_setpoints = {d: r for d, r in fan_config.setpoints.items() if d != lowest}
    return FanConfig(
        zone=fan_config.zone,
        setpoints=MappingProxyType(new_setpoints),
    )
