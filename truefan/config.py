"""Configuration loading, saving, and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import tomlkit

from truefan.fans import detect_fans
from truefan.sensors import SensorClass

if TYPE_CHECKING:
    from truefan.bmc import BmcConnection
    from truefan.sensors import SensorReading

DEFAULT_CONFIG_FILENAME: Final[str] = "truefan.toml"

DEFAULT_POLL_INTERVAL_SECONDS: Final[int] = 15
DEFAULT_SPINDOWN_WINDOW_SECONDS: Final[int] = 180


@dataclass(frozen=True, kw_only=True)
class Curve:
    """Interpolation curve mapping a temperature range to 0-100% duty.

    no_cooling_temp: below this, the component needs no active cooling (0% duty).
    max_cooling_temp: at or above this, maximum cooling is needed (100% duty).
    """

    no_cooling_temp: int
    max_cooling_temp: int
    fan_zones: frozenset[str]


DEFAULT_CURVES: Final[MappingProxyType[SensorClass, Curve]] = MappingProxyType({
    SensorClass.CPU: Curve(
        no_cooling_temp=35, max_cooling_temp=80,
        fan_zones=frozenset({"cpu", "peripheral"}),
    ),
    SensorClass.AMBIENT: Curve(
        no_cooling_temp=25, max_cooling_temp=40,
        fan_zones=frozenset({"peripheral"}),
    ),
    SensorClass.DRIVE: Curve(
        no_cooling_temp=30, max_cooling_temp=45,
        fan_zones=frozenset({"peripheral"}),
    ),
    SensorClass.NVME: Curve(
        no_cooling_temp=30, max_cooling_temp=70,
        fan_zones=frozenset({"peripheral"}),
    ),
    SensorClass.OTHER: Curve(
        no_cooling_temp=30, max_cooling_temp=80,
        fan_zones=frozenset({"peripheral"}),
    ),
})


@dataclass(frozen=True, kw_only=True)
class SensorOverride:
    """Per-sensor curve override. None fields inherit from the class curve."""

    no_cooling_temp: int | None = None
    max_cooling_temp: int | None = None
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


def _parse_int(section: str, key: str, value: object) -> int:
    """Convert a config value to int, raising ConfigError on failure."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        raise ConfigError(f"{section} {key} must be an integer, got {value!r}")


_CURVE_REQUIRED_KEYS: Final[frozenset[str]] = frozenset({
    "no_cooling_temp", "max_cooling_temp", "fan_zones",
})


def _parse_curve(name: str, table: dict) -> tuple[SensorClass, Curve]:
    """Parse a thermal class section from TOML into a SensorClass and Curve."""
    try:
        sensor_class = SensorClass(name)
    except ValueError:
        raise ConfigError(f"Unknown sensor class: {name!r}")
    section = f"[thermal.class.{name}]"
    missing = _CURVE_REQUIRED_KEYS - set(table)
    if missing:
        raise ConfigError(
            f"{section} missing required keys: {', '.join(sorted(missing))}"
        )
    unknown = set(table) - _CURVE_REQUIRED_KEYS
    if unknown:
        raise ConfigError(
            f"{section} unrecognized keys: {', '.join(sorted(unknown))}"
        )
    no_cooling_temp = _parse_int(section, "no_cooling_temp", table["no_cooling_temp"])
    max_cooling_temp = _parse_int(section, "max_cooling_temp", table["max_cooling_temp"])
    if no_cooling_temp > max_cooling_temp:
        raise ConfigError(
            f"{section}: no_cooling_temp ({no_cooling_temp}) > max_cooling_temp ({max_cooling_temp})"
        )
    fan_zones = table["fan_zones"]
    if isinstance(fan_zones, str):
        raise ConfigError(
            f"{section} fan_zones must be a list, not a string"
        )
    return sensor_class, Curve(
        no_cooling_temp=no_cooling_temp,
        max_cooling_temp=max_cooling_temp,
        fan_zones=frozenset(fan_zones),
    )


_SENSOR_OVERRIDE_KEYS: Final[frozenset[str]] = frozenset({
    "no_cooling_temp", "max_cooling_temp", "fan_zones",
})


def _parse_sensor_override(name: str, table: dict) -> SensorOverride:
    """Parse a per-sensor override from TOML."""
    unknown = set(table) - _SENSOR_OVERRIDE_KEYS
    if unknown:
        raise ConfigError(
            f"[thermal.sensor.{name}] unrecognized keys: {', '.join(sorted(unknown))}"
        )
    section = f"[thermal.sensor.{name}]"
    fan_zones = None
    if "fan_zones" in table:
        if isinstance(table["fan_zones"], str):
            raise ConfigError(f"{section} fan_zones must be a list, not a string")
        fan_zones = frozenset(table["fan_zones"])
    return SensorOverride(
        no_cooling_temp=_parse_int(section, "no_cooling_temp", table["no_cooling_temp"]) if "no_cooling_temp" in table else None,
        max_cooling_temp=_parse_int(section, "max_cooling_temp", table["max_cooling_temp"]) if "max_cooling_temp" in table else None,
        fan_zones=fan_zones,
    )


_FAN_KNOWN_KEYS: Final = frozenset({"zone", "setpoints"})


def _parse_fan(name: str, table: dict) -> FanConfig:
    """Parse a fan section from TOML into a FanConfig."""
    if "zone" not in table:
        if set(table) == {"setpoints"}:
            raise ConfigError(
                f"[fans.{name}] has setpoints but no zone "
                f"(is the [fans.{name}] section header missing or misspelled?)"
            )
        raise ConfigError(f"[fans.{name}] missing required key: zone")
    unknown = set(table) - _FAN_KNOWN_KEYS
    if unknown:
        raise ConfigError(
            f"[fans.{name}] unrecognized keys: {', '.join(sorted(unknown))}"
        )
    setpoints_raw = table.get("setpoints", {})
    setpoints = {int(k): int(v) for k, v in setpoints_raw.items()}
    return FanConfig(
        zone=str(table["zone"]),
        setpoints=MappingProxyType(setpoints),
    )


def load_config(path: Path) -> Config:
    """Read and parse the TOML config file."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")

    try:
        doc = tomlkit.parse(text)
    except tomlkit.exceptions.TOMLKitError as e:
        lines = text.splitlines()
        context = ""
        line_no = getattr(e, "line", 0)
        col = getattr(e, "col", 0)
        if isinstance(line_no, int) and 1 <= line_no <= len(lines):
            line_text = lines[line_no - 1]
            pointer = " " * (col - 1) + "^" if isinstance(col, int) and col >= 1 else ""
            context = f"\n  {line_text}\n  {pointer}"
        raise ConfigError(f"Malformed TOML in {path}: {e}{context}")

    _KNOWN_KEYS: set[str] = {
        "poll_interval_seconds", "spindown_window_seconds", "thermal", "fans",
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
    thermal = doc.get("thermal", {})
    for name, table in thermal.get("class", {}).items():
        sensor_class, curve = _parse_curve(name, table)
        curves[sensor_class] = curve
    for sensor_name, override_table in thermal.get("sensor", {}).items():
        sensor_overrides[sensor_name] = _parse_sensor_override(sensor_name, override_table)

    fans: dict[str, FanConfig] = {}
    for name, table in doc.get("fans", {}).items():
        fans[name] = _parse_fan(name, table)

    # Cross-validate zone names between thermal classes and fans.
    if curves and fans:
        curve_zones: set[str] = set()
        for curve in curves.values():
            curve_zones.update(curve.fan_zones)
        fan_zones: set[str] = {fc.zone for fc in fans.values()}
        for zone in sorted(curve_zones - fan_zones):
            raise ConfigError(
                f"Zone {zone!r} is referenced by a thermal class but no fan is assigned to it"
            )
        for zone in sorted(fan_zones - curve_zones):
            raise ConfigError(
                f"Zone {zone!r} has fans but no thermal class drives it"
            )

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

    # Write thermal class sections.
    if config.curves:
        thermal_in_doc = doc.get("thermal")
        if thermal_in_doc is None:
            thermal_in_doc = tomlkit.table(is_super_table=True)
            doc["thermal"] = thermal_in_doc
        class_in_doc = thermal_in_doc.get("class")
        if class_in_doc is None:
            class_in_doc = tomlkit.table(is_super_table=True)
            thermal_in_doc["class"] = class_in_doc
        for cls in sorted(config.curves, key=lambda c: c.value):
            curve = config.curves[cls]
            curve_table = class_in_doc.get(cls.value)
            if curve_table is None:
                curve_table = tomlkit.table()
                class_in_doc[cls.value] = curve_table
            curve_table["no_cooling_temp"] = curve.no_cooling_temp
            curve_table["max_cooling_temp"] = curve.max_cooling_temp
            curve_table["fan_zones"] = sorted(curve.fan_zones)
        # Remove classes no longer in config.
        for name in list(class_in_doc):
            try:
                SensorClass(name)
            except ValueError:
                continue
            if SensorClass(name) not in config.curves:
                del class_in_doc[name]

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
