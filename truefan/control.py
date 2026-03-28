"""Control algorithm: interpolation and demand resolution.

Pure functions with no I/O or side effects.
"""

from types import MappingProxyType

from truefan.config import Curve, FanConfig
from truefan.sensors import SensorClass, SensorReading


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
    """Round a demanded duty up to the lowest setpoint that meets or exceeds it.

    Returns the highest setpoint if duty exceeds all of them.
    """
    duties = sorted(setpoints)
    for d in duties:
        if d >= duty:
            return d
    return duties[-1]


def compute_zone_duties(
    readings: list[SensorReading],
    curves: MappingProxyType[SensorClass, Curve],
    fans: MappingProxyType[str, FanConfig],
) -> dict[str, int]:
    """Resolve sensor readings into a duty percentage per fan zone.

    For each sensor, computes demanded duty via its class's curve.
    If the sensor reports a temp_max, it overrides the curve's temp_high.
    Groups demands by fan zone, takes the max per zone, then snaps
    to the lowest setpoint that satisfies all fans in the zone.
    """
    # Compute max demanded duty per zone from sensor readings.
    zone_demands: dict[str, float] = {}
    for reading in readings:
        curve = curves.get(reading.sensor_class)
        if curve is None:
            continue
        duty = interpolate_duty(curve, reading.temperature, reading.temp_max)
        for zone in curve.fan_zones:
            if zone in zone_demands:
                zone_demands[zone] = max(zone_demands[zone], duty)
            else:
                zone_demands[zone] = duty

    # For each zone with demand, snap to setpoints considering all fans.
    result: dict[str, int] = {}
    for zone, demand in zone_demands.items():
        zone_fans = [fc for fc in fans.values() if fc.zone == zone]
        if not zone_fans:
            continue
        max_snapped = max(
            snap_duty_to_setpoint(demand, fan.setpoints) for fan in zone_fans
        )
        result[zone] = max_snapped

    return result
