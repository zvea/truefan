"""IPMI temperature sensor backend (CPU, ambient, chipset)."""

from typing import Final

from truefan.bmc import BmcConnection
from truefan.sensors import SensorBackend, SensorClass, SensorReading, sensor_name

_NAME_TO_CLASS: Final[dict[str, SensorClass]] = {
    "CPU Temp": SensorClass.CPU,
    "System Temp": SensorClass.AMBIENT,
    "Peripheral Temp": SensorClass.AMBIENT,
}

_NVME_PREFIXES: Final[tuple[str, ...]] = ("M2NVMeSSD", "U2NVMeSSD")


def _classify(name: str) -> SensorClass:
    """Classify an IPMI temperature sensor by its name."""
    if name in _NAME_TO_CLASS:
        return _NAME_TO_CLASS[name]
    for prefix in _NVME_PREFIXES:
        if name.startswith(prefix):
            return SensorClass.NVME
    return SensorClass.OTHER


class IpmiSensorBackend(SensorBackend):
    """Read board-level temperatures via IPMI."""

    def __init__(self, conn: BmcConnection) -> None:
        self._conn = conn

    def scan(self) -> list[SensorReading]:
        """Discover IPMI temperature sensors and return current readings."""
        readings: list[SensorReading] = []
        for sensor_data in self._conn.list_temperature_sensors():
            if sensor_data.temperature is None:
                continue
            readings.append(SensorReading(
                name=sensor_name("ipmi", sensor_data.name),
                sensor_class=_classify(sensor_data.name),
                temperature=sensor_data.temperature,
                temp_max=sensor_data.upper_non_critical,
                temp_crit=sensor_data.upper_critical,
            ))
        return readings
