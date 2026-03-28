"""SMART temperature sensor backend for SATA/SAS drives."""

import json
import logging
import subprocess
from pathlib import Path

from truefan.sensors import SensorBackend, SensorClass, SensorReading, sensor_name

_log: logging.Logger = logging.getLogger(__name__)


def _list_drives() -> list[Path]:
    """List block devices that look like SATA/SAS drives."""
    return sorted(Path("/dev").glob("sd[a-z]"))


def _read_temperature(dev: Path) -> float | None:
    """Read temperature from a single drive via smartctl JSON output."""
    try:
        result = subprocess.run(
            ["smartctl", "-j", "-A", str(dev)],
            capture_output=True, check=False,
        )
        data = json.loads(result.stdout)
        return float(data["temperature"]["current"])
    except (json.JSONDecodeError, KeyError, ValueError):
        _log.warning("Failed to read temperature from %s", dev)
        return None


class SmartSensorBackend(SensorBackend):
    """Read SATA/SAS drive temperatures via smartctl."""

    def scan(self) -> list[SensorReading]:
        """Discover SATA/SAS drives and return current temperature readings."""
        readings: list[SensorReading] = []
        for dev in _list_drives():
            temp = _read_temperature(dev)
            if temp is None:
                continue
            readings.append(SensorReading(
                name=sensor_name("smart", dev.name),
                sensor_class=SensorClass.DRIVE,
                temperature=temp,
            ))
        return readings
