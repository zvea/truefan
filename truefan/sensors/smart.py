"""SMART temperature sensor backend for SATA/SAS drives."""

from truefan.sensors import SensorBackend, SensorReading


class SmartSensorBackend(SensorBackend):
    """Read SATA/SAS drive temperatures via pySMART or smartctl."""

    def scan(self) -> list[SensorReading]:
        """Discover SATA/SAS drives and return current temperature readings."""
        raise NotImplementedError
