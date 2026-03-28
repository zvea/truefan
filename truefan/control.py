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
    temp_high_override: float | None = None,
) -> float:
    """Compute demanded duty percentage for a temperature on a curve.

    Linearly interpolates between temp_low and temp_high.
    Clamps to duty_low below temp_low and duty_high above temp_high.
    Returns duty_high when temp_low == temp_high (degenerate curve).
    If temp_high_override is provided (e.g. from a sensor's hardware-reported
    temp_max), it replaces the curve's temp_high.
    """
    temp_high = temp_high_override if temp_high_override is not None else curve.temp_high
    if curve.temp_low == temp_high:
        return float(curve.duty_high)
    if temperature <= curve.temp_low:
        return float(curve.duty_low)
    if temperature >= temp_high:
        return float(curve.duty_high)
    fraction = (temperature - curve.temp_low) / (temp_high - curve.temp_low)
    return curve.duty_low + fraction * (curve.duty_high - curve.duty_low)


def snap_duty_to_setpoint(duty: float, setpoints: MappingProxyType[int, int]) -> int:
    """Snap a demanded duty to the nearest setpoint.

    Returns the setpoint whose duty % is closest to the demand.
    """
    duties = sorted(setpoints)
    return min(duties, key=lambda d: abs(d - duty))


def _apply_override(curve: Curve, override: SensorOverride) -> Curve:
    """Return a new Curve with override fields applied."""
    return Curve(
        temp_low=override.temp_low if override.temp_low is not None else curve.temp_low,
        temp_high=override.temp_high if override.temp_high is not None else curve.temp_high,
        duty_low=override.duty_low if override.duty_low is not None else curve.duty_low,
        duty_high=override.duty_high if override.duty_high is not None else curve.duty_high,
        fan_zones=override.fan_zones if override.fan_zones is not None else curve.fan_zones,
    )


def compute_thermal_load(
    reading: SensorReading,
    curve: Curve,
    override: SensorOverride | None = None,
) -> float:
    """Compute how far a sensor is between its effective temp_low and temp_high (0-100%).

    Resolves per-sensor overrides and hardware temp_max using the same
    precedence as compute_zone_duties: override fields replace curve fields,
    and hardware temp_max replaces temp_high only when no override sets it.
    """
    if override is not None:
        curve = _apply_override(curve, override)
    temp_low = curve.temp_low
    temp_high = curve.temp_high
    if reading.temp_max is not None and (override is None or override.temp_high is None):
        temp_high = reading.temp_max
    if temp_high == temp_low:
        return 100.0
    return max(0.0, min(100.0, (reading.temperature - temp_low) / (temp_high - temp_low) * 100))


def compute_zone_duties(
    readings: list[SensorReading],
    curves: MappingProxyType[SensorClass, Curve],
    fans: MappingProxyType[str, FanConfig],
    sensor_overrides: MappingProxyType[str, SensorOverride] | None = None,
) -> dict[str, ZoneDuty]:
    """Resolve sensor readings into a duty percentage per fan zone.

    For each sensor, computes demanded duty via its class's curve,
    with optional per-sensor overrides. If the sensor reports a temp_max
    and no override specifies temp_high, it overrides the curve's temp_high.
    Groups demands by fan zone, takes the max per zone, then snaps
    to the lowest setpoint that satisfies all fans in the zone.
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
        # Hardware temp_max only applies if no override set temp_high.
        temp_high_override = reading.temp_max
        if override is not None and override.temp_high is not None:
            temp_high_override = None  # override already baked into curve
        duty = interpolate_duty(curve, reading.temperature, temp_high_override)
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
