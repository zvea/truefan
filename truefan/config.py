"""Configuration loading, saving, and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import tomlkit

from truefan.sensors import SensorClass

if TYPE_CHECKING:
    from truefan.bmc import BmcConnection
    from truefan.sensors import SensorReading

DEFAULT_CONFIG_FILENAME: Final[str] = "truefan.toml"

DEFAULT_POLL_INTERVAL_SECONDS: Final[int] = 15
DEFAULT_SPINDOWN_WINDOW_SECONDS: Final[int] = 180


@dataclass(frozen=True, kw_only=True)
class Curve:
    """Interpolation curve mapping a sensor class's temperature range to duty cycle range."""

    temp_low: int
    temp_high: int
    duty_low: int
    duty_high: int
    fan_zones: frozenset[str]


DEFAULT_CURVES: Final[MappingProxyType[SensorClass, Curve]] = MappingProxyType({
    SensorClass.CPU: Curve(
        temp_low=35, temp_high=80, duty_low=25, duty_high=100,
        fan_zones=frozenset({"cpu", "peripheral"}),
    ),
    SensorClass.AMBIENT: Curve(
        temp_low=25, temp_high=40, duty_low=25, duty_high=100,
        fan_zones=frozenset({"peripheral"}),
    ),
    SensorClass.DRIVE: Curve(
        temp_low=30, temp_high=45, duty_low=25, duty_high=100,
        fan_zones=frozenset({"peripheral"}),
    ),
    SensorClass.NVME: Curve(
        temp_low=30, temp_high=70, duty_low=25, duty_high=100,
        fan_zones=frozenset({"peripheral"}),
    ),
    SensorClass.OTHER: Curve(
        temp_low=30, temp_high=80, duty_low=25, duty_high=100,
        fan_zones=frozenset({"peripheral"}),
    ),
})


@dataclass(frozen=True, kw_only=True)
class SensorOverride:
    """Per-sensor curve override. None fields inherit from the class curve."""

    temp_low: int | None = None
    temp_high: int | None = None
    duty_low: int | None = None
    duty_high: int | None = None
    fan_zones: frozenset[str] | None = None


@dataclass(frozen=True, kw_only=True)
class FanConfig:
    """Calibrated state for a single fan."""

    zone: str
    setpoints: MappingProxyType[int, int]


@dataclass(frozen=True, kw_only=True)
class Config:
    """Complete in-memory configuration."""

    poll_interval_seconds: int
    curves: MappingProxyType[SensorClass, Curve]
    fans: MappingProxyType[str, FanConfig]
    spindown_window_seconds: int = DEFAULT_SPINDOWN_WINDOW_SECONDS
    sensor_overrides: MappingProxyType[str, SensorOverride] = field(
        default_factory=lambda: MappingProxyType({}),
    )


class ConfigError(Exception):
    """Raised when the config file is missing, malformed, or invalid."""


def _parse_curve(name: str, table: dict) -> tuple[SensorClass, Curve]:
    """Parse a curve section from TOML into a SensorClass and Curve."""
    try:
        sensor_class = SensorClass(name)
    except ValueError:
        raise ConfigError(f"Unknown sensor class: {name!r}")
    temp_low = int(table["temp_low"])
    temp_high = int(table["temp_high"])
    if temp_low > temp_high:
        raise ConfigError(
            f"Curve {name!r}: temp_low ({temp_low}) > temp_high ({temp_high})"
        )
    return sensor_class, Curve(
        temp_low=temp_low,
        temp_high=temp_high,
        duty_low=int(table["duty_low"]),
        duty_high=int(table["duty_high"]),
        fan_zones=frozenset(table["fan_zones"]),
    )


def _parse_sensor_override(table: dict) -> SensorOverride:
    """Parse a per-sensor override from TOML."""
    return SensorOverride(
        temp_low=int(table["temp_low"]) if "temp_low" in table else None,
        temp_high=int(table["temp_high"]) if "temp_high" in table else None,
        duty_low=int(table["duty_low"]) if "duty_low" in table else None,
        duty_high=int(table["duty_high"]) if "duty_high" in table else None,
        fan_zones=frozenset(table["fan_zones"]) if "fan_zones" in table else None,
    )


def _parse_fan(name: str, table: dict) -> FanConfig:
    """Parse a fan section from TOML into a FanConfig."""
    setpoints_raw = table.get("setpoints", {})
    setpoints = {int(k): int(v) for k, v in setpoints_raw.items()}
    return FanConfig(
        zone=str(table["zone"]),
        setpoints=MappingProxyType(setpoints),
    )


def load_config(path: Path) -> Config:
    """Read and parse the TOML config file.

    Merges user-specified curve overrides with DEFAULT_CURVES.
    """
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")

    try:
        doc = tomlkit.parse(text)
    except tomlkit.exceptions.ParseError as e:
        raise ConfigError(f"Malformed TOML in {path}: {e}")

    _KNOWN_KEYS: set[str] = {
        "poll_interval_seconds", "spindown_window_seconds", "curves", "fans",
    }
    unknown = sorted(k for k in doc if k not in _KNOWN_KEYS)
    if unknown:
        raise ConfigError(
            f"Unrecognized config keys: {', '.join(unknown)}"
        )

    poll_interval = int(doc.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS))
    spindown_window = int(doc.get("spindown_window_seconds", DEFAULT_SPINDOWN_WINDOW_SECONDS))

    curves: dict[SensorClass, Curve] = {}
    sensor_overrides: dict[str, SensorOverride] = {}
    for name, table in doc.get("curves", {}).items():
        if name == "sensor":
            for sensor_name, override_table in table.items():
                sensor_overrides[sensor_name] = _parse_sensor_override(override_table)
        else:
            sensor_class, curve = _parse_curve(name, table)
            curves[sensor_class] = curve

    fans: dict[str, FanConfig] = {}
    for name, table in doc.get("fans", {}).items():
        fans[name] = _parse_fan(name, table)

    return Config(
        poll_interval_seconds=poll_interval,
        spindown_window_seconds=spindown_window,
        curves=MappingProxyType(curves),
        sensor_overrides=MappingProxyType(sensor_overrides),
        fans=MappingProxyType(fans),
    )


def save_config(path: Path, config: Config) -> None:
    """Write config back to TOML, preserving comments and formatting."""
    try:
        text = path.read_text()
        doc = tomlkit.parse(text)
    except FileNotFoundError:
        doc = tomlkit.document()

    doc["poll_interval_seconds"] = config.poll_interval_seconds
    doc["spindown_window_seconds"] = config.spindown_window_seconds

    # Write curves.
    if config.curves:
        curves_in_doc = doc.get("curves")
        if curves_in_doc is None:
            curves_in_doc = tomlkit.table(is_super_table=True)
            doc["curves"] = curves_in_doc
        for cls, curve in config.curves.items():
            curve_table = curves_in_doc.get(cls.value)
            if curve_table is None:
                curve_table = tomlkit.table()
                curves_in_doc[cls.value] = curve_table
            curve_table["temp_low"] = curve.temp_low
            curve_table["temp_high"] = curve.temp_high
            curve_table["duty_low"] = curve.duty_low
            curve_table["duty_high"] = curve.duty_high
            curve_table["fan_zones"] = sorted(curve.fan_zones)
        # Remove curves no longer in config.
        for name in list(curves_in_doc):
            try:
                SensorClass(name)
            except ValueError:
                continue
            if SensorClass(name) not in config.curves:
                del curves_in_doc[name]

    fans_in_doc = doc.get("fans")
    if fans_in_doc is None:
        fans_in_doc = tomlkit.table(is_super_table=True)
        doc["fans"] = fans_in_doc

    for fan_name, fan_config in config.fans.items():
        fan_table = fans_in_doc.get(fan_name)
        if fan_table is None:
            fan_table = tomlkit.table()
            fans_in_doc[fan_name] = fan_table

        fan_table["zone"] = fan_config.zone

        setpoints_table = tomlkit.table()
        for duty in sorted(fan_config.setpoints):
            setpoints_table[str(duty)] = fan_config.setpoints[duty]
        fan_table["setpoints"] = setpoints_table

    # Remove fans no longer in config.
    for name in list(fans_in_doc):
        if name not in config.fans:
            del fans_in_doc[name]

    path.write_text(tomlkit.dumps(doc))


def validate_config(
    config: Config,
    conn: BmcConnection,
    readings: list[SensorReading],
) -> list[str]:
    """Check config against live hardware state.

    Returns a list of error messages. Empty means valid.
    Checks fan set membership, zone agreement, and sensor override targets.
    """
    from truefan.fans import detect_fans

    errors: list[str] = []

    # Fan checks: config fans vs hardware fans.
    hw_fans = detect_fans(conn)
    config_names = set(config.fans)
    hw_names = set(hw_fans)

    for name in sorted(config_names - hw_names):
        errors.append(f"Fan {name} is in config but not detected in hardware")
    for name in sorted(hw_names - config_names):
        errors.append(f"Fan {name} is detected in hardware but not in config")
    for name in sorted(config_names & hw_names):
        config_zone = config.fans[name].zone
        hw_zone = hw_fans[name]
        if config_zone != hw_zone:
            errors.append(
                f"Fan {name} zone mismatch: config says {config_zone!r}, "
                f"hardware says {hw_zone!r}"
            )

    # Sensor override checks.
    if config.sensor_overrides:
        known_sensors = {r.name for r in readings}
        for name in sorted(set(config.sensor_overrides) - known_sensors):
            errors.append(f"Sensor override references unknown sensor: {name}")

    return errors
