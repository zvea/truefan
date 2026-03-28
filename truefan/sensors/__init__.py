"""Sensor backend interface and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class SensorClass(StrEnum):
    """Classification of a temperature sensor."""

    CPU = "cpu"
    AMBIENT = "ambient"
    DRIVE = "drive"
    NVME = "nvme"


@dataclass(frozen=True, kw_only=True)
class SensorReading:
    """A single temperature reading from a sensor."""

    name: str
    sensor_class: SensorClass
    temperature: float


class SensorError(Exception):
    """Base exception for sensor-related failures."""


class SensorBackend(ABC):
    """Interface for a temperature sensor backend.

    Each backend discovers and reads sensors every poll cycle.
    If no sensors are available, scan() returns an empty list.
    """

    @abstractmethod
    def scan(self) -> list[SensorReading]:
        """Discover sensors and return current readings."""


def available_backends() -> list[SensorBackend]:
    """Probe the system and return backends for available sensor sources."""
    raise NotImplementedError
