"""Control algorithm: interpolation and demand resolution.

Pure functions with no I/O or side effects.
"""

from types import MappingProxyType

from truefan.config import Curve, FanConfig
from truefan.sensors import SensorClass, SensorReading


def interpolate_duty(curve: Curve, temperature: float) -> float:
    """Compute demanded duty percentage for a temperature on a curve.

    Linearly interpolates between temp_low and temp_high.
    Clamps to duty_low below temp_low and duty_high above temp_high.
    """
    raise NotImplementedError


def snap_duty_to_setpoint(duty: float, setpoints: MappingProxyType[int, int]) -> int:
    """Round a demanded duty up to the lowest setpoint that meets or exceeds it.

    Returns the highest setpoint if duty exceeds all of them.
    """
    raise NotImplementedError


def compute_zone_duties(
    readings: list[SensorReading],
    curves: MappingProxyType[SensorClass, Curve],
    fans: MappingProxyType[str, FanConfig],
) -> dict[str, int]:
    """Resolve sensor readings into a duty percentage per fan zone.

    For each sensor, computes demanded duty via its class's curve.
    Groups demands by fan zone, takes the max per zone, then snaps
    to the lowest setpoint that satisfies all fans in the zone.
    """
    raise NotImplementedError
