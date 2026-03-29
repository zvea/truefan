"""Control algorithm: interpolation and demand resolution.

Pure functions with no I/O or side effects.
"""

from dataclasses import dataclass
from types import MappingProxyType

from truefan.config import Curve, FanConfig, SensorOverride
from truefan.sensors import SensorClass, SensorReading


@dataclass(frozen=True, kw_only=True)
class ZoneDuty:
    """Resolved duty for a fan zone, with the reason it was chosen."""

    duty: int
    sensor_name: str
    temperature: float
    raw_duty: float


def interpolate_duty(
    curve: Curve,
    temperature: float,
    max_cooling_temp_override: float | None = None,
) -> float:
    """Compute demanded duty (0-100%) for a temperature on a curve.

    Linearly interpolates between no_cooling_temp (0%) and max_cooling_temp (100%).
    Returns 100% when no_cooling_temp == max_cooling_temp (degenerate curve).
    If max_cooling_temp_override is provided (e.g. from a sensor's hardware-reported
    temp_max), it replaces the curve's max_cooling_temp.
    """
    max_cooling_temp = max_cooling_temp_override if max_cooling_temp_override is not None else curve.max_cooling_temp
    if curve.no_cooling_temp == max_cooling_temp:
        return 100.0
    if temperature <= curve.no_cooling_temp:
        return 0.0
    if temperature >= max_cooling_temp:
        return 100.0
    return (temperature - curve.no_cooling_temp) / (max_cooling_temp - curve.no_cooling_temp) * 100.0


def snap_duty_to_setpoint(duty: float, setpoints: MappingProxyType[int, int]) -> int:
    """Snap a demanded duty to the nearest setpoint.

    Returns the setpoint whose duty % is closest to the demand.
    """
    duties = sorted(setpoints)
    return min(duties, key=lambda d: abs(d - duty))


def _apply_override(curve: Curve, override: SensorOverride) -> Curve:
    """Return a new Curve with override fields applied."""
    return Curve(
        no_cooling_temp=override.no_cooling_temp if override.no_cooling_temp is not None else curve.no_cooling_temp,
        max_cooling_temp=override.max_cooling_temp if override.max_cooling_temp is not None else curve.max_cooling_temp,
        fan_zones=override.fan_zones if override.fan_zones is not None else curve.fan_zones,
    )


def compute_thermal_load(
    reading: SensorReading,
    curve: Curve,
    override: SensorOverride | None = None,
) -> float:
    """Compute how far a sensor is between its effective temp range (0-100%).

    Resolves per-sensor overrides and hardware temp_max, then delegates
    to interpolate_duty. The result is also the demanded duty percentage.
    """
    if override is not None:
        curve = _apply_override(curve, override)
    max_cooling_temp_override = None
    if reading.temp_max is not None and (override is None or override.max_cooling_temp is None):
        max_cooling_temp_override = reading.temp_max
    return interpolate_duty(curve, reading.temperature, max_cooling_temp_override)


def compute_zone_duties(
    readings: list[SensorReading],
    curves: MappingProxyType[SensorClass, Curve],
    fans: MappingProxyType[str, FanConfig],
    sensor_overrides: MappingProxyType[str, SensorOverride] | None = None,
) -> dict[str, ZoneDuty]:
    """Resolve sensor readings into a duty percentage per fan zone.

    For each sensor, computes demanded duty (0-100%) via its class's curve,
    with optional per-sensor overrides. If the sensor reports a temp_max
    and no override specifies max_cooling_temp, it overrides the curve's
    max_cooling_temp. Groups demands by fan zone, takes the max per zone,
    then snaps to the nearest setpoint that satisfies all fans in the zone.
    """
    # Track max demanded duty and which sensor caused it, per zone.
    zone_demands: dict[str, tuple[float, SensorReading]] = {}
    for reading in readings:
        curve = curves.get(reading.sensor_class)
        if curve is None:
            continue
        override = (sensor_overrides or {}).get(reading.name)
        if override is not None:
            curve = _apply_override(curve, override)
        # Hardware temp_max only applies if no override set max_cooling_temp.
        max_cooling_temp_override = reading.temp_max
        if override is not None and override.max_cooling_temp is not None:
            max_cooling_temp_override = None  # override already baked into curve
        duty = interpolate_duty(curve, reading.temperature, max_cooling_temp_override)
        for zone in curve.fan_zones:
            if zone not in zone_demands or duty > zone_demands[zone][0]:
                zone_demands[zone] = (duty, reading)

    # For each zone with demand, snap to setpoints considering all fans.
    result: dict[str, ZoneDuty] = {}
    for zone, (demand, reading) in zone_demands.items():
        zone_fans = [fc for fc in fans.values() if fc.zone == zone]
        if not zone_fans:
            continue
        max_snapped = max(
            snap_duty_to_setpoint(demand, fan.setpoints) for fan in zone_fans
        )
        result[zone] = ZoneDuty(
            duty=max_snapped,
            sensor_name=reading.name,
            temperature=reading.temperature,
            raw_duty=demand,
        )

    return result
