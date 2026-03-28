"""Fan calibration and stall recovery."""

from dataclasses import dataclass
from types import MappingProxyType

from truefan.config import FanConfig


@dataclass(frozen=True, kw_only=True)
class CalibrationResult:
    """Result of calibrating a single fan."""

    fan_name: str
    zone: str
    setpoints: MappingProxyType[int, int]


class CalibrationError(Exception):
    """Raised when calibration fails (fan never spins, IPMI errors, etc.)."""


def calibrate_fans(
    fan_names: list[str],
    fan_zones: dict[str, str],
) -> list[CalibrationResult]:
    """Run ramp-down calibration for the given fans.

    Steps through duty levels from high to low, recording RPM at each step.
    Builds a setpoint table per fan. Calibrates one zone at a time while
    keeping other zones at a safe speed.
    """
    raise NotImplementedError


def remove_lowest_setpoint(fan_config: FanConfig) -> FanConfig:
    """Return a new FanConfig with the lowest setpoint removed.

    Used during stall recovery to raise the effective minimum duty.
    Never removes the last setpoint.
    """
    raise NotImplementedError
