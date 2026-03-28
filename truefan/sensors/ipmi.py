"""IPMI temperature sensor backend (CPU, ambient, chipset)."""

from truefan.sensors import SensorBackend, SensorReading


class IpmiSensorBackend(SensorBackend):
    """Read board-level temperatures via pyghmi."""

    def scan(self) -> list[SensorReading]:
        """Discover IPMI temperature sensors and return current readings."""
        raise NotImplementedError
