"""Tests for truefan.sensors.nvme."""

import json
from unittest.mock import MagicMock, patch

from truefan.sensors import SensorClass
from truefan.sensors.nvme import NvmeSensorBackend, _read_temperature

# Canned nvme smart-log -o json output.
_NVME_JSON = json.dumps({
    "critical_warning": 0,
    "temperature": 311,  # 311 Kelvin = ~37.85°C
    "avail_spare": 100,
}).encode()


# ---------------------------------------------------------------------------
# #### _read_temperature
# ---------------------------------------------------------------------------

class TestReadTemperature:
    """Tests for _read_temperature."""

    @patch("truefan.sensors.nvme.subprocess.run")
    def test_converts_kelvin_to_celsius(self, mock_run) -> None:  # noqa: ANN001
        """Converts Kelvin temperature to Celsius."""
        from pathlib import Path
        result = MagicMock()
        result.stdout = _NVME_JSON
        mock_run.return_value = result
        temp = _read_temperature(Path("/dev/nvme0"))
        assert temp == 37.9  # 311 - 273.15 = 37.85, rounded to 37.9

    @patch("truefan.sensors.nvme.subprocess.run")
    def test_returns_none_on_bad_json(self, mock_run) -> None:  # noqa: ANN001
        """Returns None on unparseable output."""
        from pathlib import Path
        result = MagicMock()
        result.stdout = b"not json"
        mock_run.return_value = result
        assert _read_temperature(Path("/dev/nvme0")) is None


# ---------------------------------------------------------------------------
# #### NvmeSensorBackend.scan
# ---------------------------------------------------------------------------

class TestNvmeSensorBackend:
    """Tests for NvmeSensorBackend."""

    @patch("truefan.sensors.nvme._list_devices")
    @patch("truefan.sensors.nvme.subprocess.run")
    def test_returns_readings(self, mock_run, mock_list) -> None:  # noqa: ANN001
        """Returns one reading per NVMe device."""
        from pathlib import Path
        mock_list.return_value = [Path("/dev/nvme0")]
        result = MagicMock()
        result.stdout = _NVME_JSON
        mock_run.return_value = result
        backend = NvmeSensorBackend()
        readings = backend.scan()
        assert len(readings) == 1
        assert readings[0].name == "nvme-nvme0"
        assert readings[0].sensor_class == SensorClass.NVME
        assert readings[0].temperature == 37.9

    @patch("truefan.sensors.nvme._list_devices")
    def test_empty_when_no_devices(self, mock_list) -> None:  # noqa: ANN001
        """Returns empty list when no NVMe devices exist."""
        mock_list.return_value = []
        backend = NvmeSensorBackend()
        assert backend.scan() == []
