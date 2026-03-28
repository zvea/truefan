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
    OTHER = "other"


@dataclass(frozen=True, kw_only=True)
class SensorReading:
    """A single temperature reading from a sensor.

    The name is a unique id in the form <backend>/<device-path>,
    e.g. "smart/sda" or "lmsensors/coretemp-isa-0000/Core 0".
    If the hardware reports thermal limits, temp_max and temp_crit
    carry those values. A sensor's temp_max overrides the curve's
    temp_high when computing demanded duty.
    """

    name: str
    sensor_class: SensorClass
    temperature: float
    temp_max: float | None = None
    temp_crit: float | None = None


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


def available_backends(bmc: "BmcConnection | None" = None) -> list[SensorBackend]:
    """Probe the system and return backends for available sensor sources.

    If a BmcConnection is provided, the IPMI sensor backend is included.
    Subprocess-based backends (SMART, NVMe, lm-sensors) are included
    if their tools are found on PATH.
    """
    import shutil

    from truefan.sensors.ipmi import IpmiSensorBackend
    from truefan.sensors.lmsensors import LmSensorBackend
    from truefan.sensors.nvme import NvmeSensorBackend
    from truefan.sensors.smart import SmartSensorBackend

    backends: list[SensorBackend] = []
    if bmc is not None:
        backends.append(IpmiSensorBackend(bmc))
    if shutil.which("smartctl"):
        backends.append(SmartSensorBackend())
    if shutil.which("nvme"):
        backends.append(NvmeSensorBackend())
    if shutil.which("sensors"):
        backends.append(LmSensorBackend())
    return backends
