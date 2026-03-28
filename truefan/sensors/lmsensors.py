"""lm-sensors temperature sensor backend."""

import json
import logging
import subprocess
from typing import Final

from truefan.sensors import SensorBackend, SensorClass, SensorReading, sensor_name

_log: logging.Logger = logging.getLogger(__name__)

_CHIP_PREFIX_TO_CLASS: Final[dict[str, SensorClass]] = {
    "coretemp": SensorClass.CPU,
    "acpitz": SensorClass.AMBIENT,
}


def _classify_chip(chip_name: str) -> SensorClass:
    """Classify a chip by its name prefix."""
    for prefix, cls in _CHIP_PREFIX_TO_CLASS.items():
        if chip_name.startswith(prefix):
            return cls
    return SensorClass.OTHER


def _read_sensors_json() -> dict:
    """Run sensors -j and return parsed JSON."""
    try:
        result = subprocess.run(
            ["sensors", "-j"],
            capture_output=True, check=False,
        )
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        _log.warning("Failed to parse sensors -j output")
        return {}


class LmSensorBackend(SensorBackend):
    """Read kernel-exposed sensors via sensors -j."""

    def scan(self) -> list[SensorReading]:
        """Discover lm-sensors and return current temperature readings."""
        data = _read_sensors_json()
        readings: list[SensorReading] = []
        for chip_name, chip_data in data.items():
            if not isinstance(chip_data, dict):
                continue
            sensor_class = _classify_chip(chip_name)
            for feature_name, feature_data in chip_data.items():
                if not isinstance(feature_data, dict):
                    continue
                # Find the temp_input field (temp1_input, temp2_input, etc.)
                temp_input = None
                temp_max = None
                temp_crit = None
                for key, value in feature_data.items():
                    if key.endswith("_input"):
                        temp_input = float(value)
                    elif key.endswith("_max"):
                        temp_max = float(value)
                    elif key.endswith("_crit") and not key.endswith("_crit_alarm"):
                        temp_crit = float(value)
                if temp_input is None:
                    continue
                readings.append(SensorReading(
                    name=sensor_name("lmsensors", chip_name, feature_name),
                    sensor_class=sensor_class,
                    temperature=temp_input,
                    temp_max=temp_max,
                    temp_crit=temp_crit,
                ))
        return readings
