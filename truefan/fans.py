"""Fan hardware interface via IPMI raw commands."""

from dataclasses import dataclass
from typing import Final

from truefan.bmc import BmcConnection

ZONES: Final[frozenset[str]] = frozenset({"cpu", "peripheral"})

_ZONE_IDS: Final[dict[str, int]] = {"cpu": 0x00, "peripheral": 0x01}

_FAN_PREFIX_TO_ZONE: Final[dict[str, str]] = {
    "CPU_": "cpu",
    "SYS_": "peripheral",
}

_THRESHOLD_LOWER: Final[tuple[int, int, int]] = (100, 100, 100)
_THRESHOLD_UPPER: Final[tuple[int, int, int]] = (25000, 25000, 25000)


@dataclass(frozen=True, kw_only=True)
class FanRpm:
    """A single fan's current RPM reading."""

    name: str
    rpm: int


class FanControlError(Exception):
    """Raised when IPMI fan control commands fail."""


def fan_zone(fan_name: str) -> str:
    """Determine which zone a fan belongs to based on its name prefix."""
    for prefix, zone in _FAN_PREFIX_TO_ZONE.items():
        if fan_name.startswith(prefix):
            return zone
    raise FanControlError(f"Unknown fan name prefix: {fan_name!r}")


def detect_fans(conn: BmcConnection) -> dict[str, str]:
    """Discover which fans are present and their zone membership.

    Returns a mapping of fan name to zone name. Only fans with
    an active RPM reading are included.
    """
    result: dict[str, str] = {}
    for name, rpm in conn.list_fans():
        if rpm is not None:
            result[name] = fan_zone(name)
    return result


def reset_thresholds(conn: BmcConnection) -> None:
    """Reset BMC fan sensor thresholds to prevent automatic overrides.

    Sets lower thresholds to 100 RPM and upper thresholds to 25000 RPM
    for all fans (including inactive ones).
    """
    for name, _ in conn.list_fans():
        conn.set_sensor_thresholds(name, _THRESHOLD_LOWER, _THRESHOLD_UPPER)


def enable_manual_control(conn: BmcConnection) -> None:
    """Enable IPMI full manual fan mode (full-speed mode command)."""
    conn.raw_command(0x30, 0x45, bytes([0x01, 0x01]))


def set_full_speed(conn: BmcConnection) -> None:
    """Set all fan zones to 100% duty and enable full-speed mode."""
    enable_manual_control(conn)
    for zone in ZONES:
        set_zone_duty(conn, zone, 100)


def set_zone_duty(conn: BmcConnection, zone: str, duty: int) -> None:
    """Set a fan zone's duty cycle percentage via IPMI raw command."""
    if zone not in _ZONE_IDS:
        raise FanControlError(f"Unknown zone: {zone!r}")
    if not 0 <= duty <= 100:
        raise FanControlError(f"Duty must be 0-100, got {duty}")
    zone_id = _ZONE_IDS[zone]
    conn.raw_command(0x30, 0x70, bytes([0x66, 0x01, zone_id, duty]))


def read_fan_rpms(conn: BmcConnection) -> list[FanRpm]:
    """Read current RPM for all fans via IPMI.

    Only fans with an active reading are returned.
    """
    result: list[FanRpm] = []
    for name, rpm in conn.list_fans():
        if rpm is not None:
            result.append(FanRpm(name=name, rpm=rpm))
    return result
