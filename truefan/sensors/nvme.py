"""NVMe temperature sensor backend."""

import json
import logging
import subprocess
from pathlib import Path

from truefan.sensors import SensorBackend, SensorClass, SensorReading

_log: logging.Logger = logging.getLogger(__name__)

_KELVIN_OFFSET: float = 273.15


def _list_devices() -> list[Path]:
    """List NVMe character devices."""
    return sorted(Path("/dev").glob("nvme[0-9]"))


def _read_temperature(dev: Path) -> float | None:
    """Read temperature from an NVMe device via nvme smart-log JSON output."""
    try:
        result = subprocess.run(
            ["nvme", "smart-log", str(dev), "-o", "json"],
            capture_output=True, check=False,
        )
        data = json.loads(result.stdout)
        kelvin = int(data["temperature"])
        return round(kelvin - _KELVIN_OFFSET, 1)
    except (json.JSONDecodeError, KeyError, ValueError):
        _log.warning("Failed to read temperature from %s", dev)
        return None


class NvmeSensorBackend(SensorBackend):
    """Read NVMe drive temperatures via nvme-cli."""

    def scan(self) -> list[SensorReading]:
        """Discover NVMe drives and return current temperature readings."""
        readings: list[SensorReading] = []
        for dev in _list_devices():
            temp = _read_temperature(dev)
            if temp is None:
                continue
            readings.append(SensorReading(
                name=f"nvme/{dev.name}",
                sensor_class=SensorClass.NVME,
                temperature=temp,
            ))
        return readings
