"""Fan hardware interface via IPMI raw commands."""

from dataclasses import dataclass
from typing import Final

ZONES: Final[frozenset[str]] = frozenset({"cpu", "peripheral"})


@dataclass(frozen=True, kw_only=True)
class FanRpm:
    """A single fan's current RPM reading."""

    name: str
    rpm: int


class FanControlError(Exception):
    """Raised when IPMI fan control commands fail."""


def enable_manual_control() -> None:
    """Enable IPMI full manual fan mode."""
    raise NotImplementedError


def restore_automatic_control() -> None:
    """Restore IPMI automatic fan mode."""
    raise NotImplementedError


def set_zone_duty(zone: str, duty: int) -> None:
    """Set a fan zone's duty cycle percentage via IPMI."""
    raise NotImplementedError


def read_fan_rpms() -> list[FanRpm]:
    """Read current RPM for all fans via IPMI."""
    raise NotImplementedError


def detect_fans() -> dict[str, str]:
    """Discover which fans are present and their zone membership.

    Returns a mapping of fan name to zone name.
    """
    raise NotImplementedError
