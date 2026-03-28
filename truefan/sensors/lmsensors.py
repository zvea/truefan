"""lm-sensors temperature sensor backend."""

from truefan.sensors import SensorBackend, SensorReading


class LmSensorBackend(SensorBackend):
    """Read kernel-exposed sensors via sensors -j."""

    def scan(self) -> list[SensorReading]:
        """Discover lm-sensors and return current temperature readings."""
        raise NotImplementedError
