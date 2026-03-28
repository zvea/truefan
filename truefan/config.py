"""Configuration loading, saving, and data structures."""

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import tomlkit

from truefan.sensors import SensorClass

DEFAULT_CONFIG_FILENAME: Final[str] = "truefan.toml"

DEFAULT_POLL_INTERVAL_SECONDS: Final[int] = 15


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
class FanConfig:
    """Calibrated state for a single fan."""

    zone: str
    setpoints: MappingProxyType[int, int]


@dataclass(frozen=True, kw_only=True)
class Config:
    """Complete in-memory configuration.

    Curves are merged from built-in defaults and user overrides.
    """

    poll_interval_seconds: int
    curves: MappingProxyType[SensorClass, Curve]
    fans: MappingProxyType[str, FanConfig]


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

    poll_interval = int(doc.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS))

    curves = dict(DEFAULT_CURVES)
    for name, table in doc.get("curves", {}).items():
        sensor_class, curve = _parse_curve(name, table)
        curves[sensor_class] = curve

    fans: dict[str, FanConfig] = {}
    for name, table in doc.get("fans", {}).items():
        fans[name] = _parse_fan(name, table)

    return Config(
        poll_interval_seconds=poll_interval,
        curves=MappingProxyType(curves),
        fans=MappingProxyType(fans),
    )


def save_config(path: Path, config: Config) -> None:
    """Write config back to TOML, preserving comments and formatting.

    Only daemon-managed sections (fans/setpoints) are updated.
    """
    try:
        text = path.read_text()
        doc = tomlkit.parse(text)
    except FileNotFoundError:
        doc = tomlkit.document()

    doc["poll_interval_seconds"] = config.poll_interval_seconds

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
