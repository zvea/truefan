"""NVMe temperature sensor backend."""

from truefan.sensors import SensorBackend, SensorReading


class NvmeSensorBackend(SensorBackend):
    """Read NVMe drive temperatures via nvme-cli."""

    def scan(self) -> list[SensorReading]:
        """Discover NVMe drives and return current temperature readings."""
        raise NotImplementedError
