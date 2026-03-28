"""Tests for truefan.sensors.smart."""

import json
from unittest.mock import patch

from truefan.sensors import SensorClass
from truefan.sensors.smart import SmartSensorBackend, _read_temperature

# Canned smartctl -j -A output matching a real SATA drive.
_SMARTCTL_JSON = json.dumps({
    "json_format_version": [1, 0],
    "temperature": {"current": 29},
}).encode()

_SMARTCTL_JSON_NO_TEMP = json.dumps({
    "json_format_version": [1, 0],
}).encode()


def _mock_smartctl_run(args, **kwargs):  # noqa: ANN001, ANN003
    """Simulate smartctl -j -A /dev/sdX."""
    from unittest.mock import MagicMock
    result = MagicMock()
    result.stdout = _SMARTCTL_JSON
    return result


# ---------------------------------------------------------------------------
# #### _read_temperature
# ---------------------------------------------------------------------------

class TestReadTemperature:
    """Tests for _read_temperature."""

    @patch("truefan.sensors.smart.subprocess.run", side_effect=_mock_smartctl_run)
    def test_parses_temperature(self, mock_run) -> None:  # noqa: ANN001
        """Parses current temperature from smartctl JSON."""
        from pathlib import Path
        temp = _read_temperature(Path("/dev/sda"))
        assert temp == 29.0

    @patch("truefan.sensors.smart.subprocess.run")
    def test_returns_none_on_missing_key(self, mock_run) -> None:  # noqa: ANN001
        """Returns None when temperature key is missing."""
        from pathlib import Path
        from unittest.mock import MagicMock
        result = MagicMock()
        result.stdout = _SMARTCTL_JSON_NO_TEMP
        mock_run.return_value = result
        assert _read_temperature(Path("/dev/sda")) is None


# ---------------------------------------------------------------------------
# #### SmartSensorBackend.scan
# ---------------------------------------------------------------------------

class TestSmartSensorBackend:
    """Tests for SmartSensorBackend."""

    @patch("truefan.sensors.smart._list_drives")
    @patch("truefan.sensors.smart.subprocess.run", side_effect=_mock_smartctl_run)
    def test_returns_readings_for_all_drives(self, mock_run, mock_list) -> None:  # noqa: ANN001
        """Returns one reading per drive."""
        from pathlib import Path
        mock_list.return_value = [Path("/dev/sda"), Path("/dev/sdb"), Path("/dev/sdc")]
        backend = SmartSensorBackend()
        readings = backend.scan()
        assert len(readings) == 3
        assert all(r.sensor_class == SensorClass.DRIVE for r in readings)
        assert {r.name for r in readings} == {"smart-sda", "smart-sdb", "smart-sdc"}

    @patch("truefan.sensors.smart._list_drives")
    @patch("truefan.sensors.smart.subprocess.run", side_effect=_mock_smartctl_run)
    def test_names_contain_no_slashes_or_dots(self, mock_run, mock_list) -> None:  # noqa: ANN001
        """Sensor names must not contain / or . — both break statsd metric paths."""
        from pathlib import Path
        mock_list.return_value = [Path("/dev/sda")]
        backend = SmartSensorBackend()
        readings = backend.scan()
        for r in readings:
            assert "/" not in r.name, f"slash in sensor name: {r.name}"
            assert "." not in r.name, f"dot in sensor name: {r.name}"

    @patch("truefan.sensors.smart._list_drives")
    @patch("truefan.sensors.smart.subprocess.run")
    def test_skips_drives_without_temp(self, mock_run, mock_list) -> None:  # noqa: ANN001
        """Drives that fail to report temperature are skipped."""
        from pathlib import Path
        from unittest.mock import MagicMock
        mock_list.return_value = [Path("/dev/sda")]
        result = MagicMock()
        result.stdout = _SMARTCTL_JSON_NO_TEMP
        mock_run.return_value = result
        backend = SmartSensorBackend()
        assert backend.scan() == []
