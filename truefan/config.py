"""Configuration loading, saving, and data structures."""

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from truefan.sensors import SensorClass

DEFAULT_CONFIG_FILENAME: Final[str] = "truefan.toml"

DEFAULT_POLL_INTERVAL_SECONDS: Final[int] = 5


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


def load_config(path: Path) -> Config:
    """Read and parse the TOML config file.

    Merges user-specified curve overrides with DEFAULT_CURVES.
    """
    raise NotImplementedError


def save_config(path: Path, config: Config) -> None:
    """Write config back to TOML, preserving comments and formatting.

    Only daemon-managed sections (fans/setpoints) are updated.
    """
    raise NotImplementedError
