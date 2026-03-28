"""Tests for truefan.sensors.lmsensors."""

import json
from unittest.mock import MagicMock, patch

from truefan.sensors import SensorClass
from truefan.sensors.lmsensors import LmSensorBackend

# Canned sensors -j output matching the real X11SCA-F system.
_SENSORS_JSON = json.dumps({
    "coretemp-isa-0000": {
        "Adapter": "ISA adapter",
        "Package id 0": {
            "temp1_input": 42.0,
            "temp1_max": 80.0,
            "temp1_crit": 100.0,
            "temp1_crit_alarm": 0.0,
        },
        "Core 0": {
            "temp2_input": 31.0,
            "temp2_max": 80.0,
            "temp2_crit": 100.0,
            "temp2_crit_alarm": 0.0,
        },
    },
    "mlx5-pci-0201": {
        "Adapter": "PCI adapter",
        "sensor0": {
            "temp1_input": 58.0,
            "temp1_crit": 105.0,
            "temp1_highest": 91.0,
        },
    },
    "acpitz-acpi-0": {
        "Adapter": "ACPI interface",
        "temp1": {
            "temp1_input": 27.8,
        },
    },
    "pch_cannonlake-virtual-0": {
        "Adapter": "Virtual device",
        "temp1": {
            "temp1_input": 45.0,
        },
    },
}).encode()


def _mock_sensors_run(args, **kwargs):  # noqa: ANN001, ANN003
    result = MagicMock()
    result.stdout = _SENSORS_JSON
    return result


# ---------------------------------------------------------------------------
# #### LmSensorBackend.scan
# ---------------------------------------------------------------------------

class TestLmSensorBackend:
    """Tests for LmSensorBackend."""

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_classifies_coretemp_as_cpu(self, mock_run) -> None:  # noqa: ANN001
        """coretemp sensors are classified as cpu."""
        backend = LmSensorBackend()
        readings = backend.scan()
        coretemp = [r for r in readings if "coretemp" in r.name]
        assert len(coretemp) == 2
        assert all(r.sensor_class == SensorClass.CPU for r in coretemp)

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_classifies_acpitz_as_ambient(self, mock_run) -> None:  # noqa: ANN001
        """acpitz sensors are classified as ambient."""
        backend = LmSensorBackend()
        readings = backend.scan()
        acpi = [r for r in readings if "acpitz" in r.name]
        assert len(acpi) == 1
        assert acpi[0].sensor_class == SensorClass.AMBIENT
        assert acpi[0].temperature == 27.8

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_classifies_mlx5_as_other(self, mock_run) -> None:  # noqa: ANN001
        """Mellanox NIC sensors are classified as other."""
        backend = LmSensorBackend()
        readings = backend.scan()
        mlx = [r for r in readings if "mlx5" in r.name]
        assert len(mlx) == 1
        assert mlx[0].sensor_class == SensorClass.OTHER

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_classifies_pch_as_other(self, mock_run) -> None:  # noqa: ANN001
        """PCH sensors are classified as other."""
        backend = LmSensorBackend()
        readings = backend.scan()
        pch = [r for r in readings if "pch" in r.name]
        assert len(pch) == 1
        assert pch[0].sensor_class == SensorClass.OTHER

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_carries_temp_max_and_crit(self, mock_run) -> None:  # noqa: ANN001
        """Hardware-reported temp_max and temp_crit are carried on the reading."""
        backend = LmSensorBackend()
        readings = backend.scan()
        pkg = [r for r in readings if "Package" in r.name][0]
        assert pkg.temp_max == 80.0
        assert pkg.temp_crit == 100.0

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_no_thresholds_when_absent(self, mock_run) -> None:  # noqa: ANN001
        """Sensors without max/crit report None."""
        backend = LmSensorBackend()
        readings = backend.scan()
        acpi = [r for r in readings if "acpitz" in r.name][0]
        assert acpi.temp_max is None
        assert acpi.temp_crit is None

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_sensor_names_are_unique(self, mock_run) -> None:  # noqa: ANN001
        """Each sensor has a unique name."""
        backend = LmSensorBackend()
        readings = backend.scan()
        names = [r.name for r in readings]
        assert len(names) == len(set(names))

    @patch("truefan.sensors.lmsensors.subprocess.run", side_effect=_mock_sensors_run)
    def test_name_format(self, mock_run) -> None:  # noqa: ANN001
        """Names follow lmsensors_<chip>_<feature> format."""
        backend = LmSensorBackend()
        readings = backend.scan()
        for r in readings:
            assert r.name.startswith("lmsensors_")
            assert " " not in r.name
            assert "/" not in r.name
            assert "-" not in r.name

    @patch("truefan.sensors.lmsensors.subprocess.run")
    def test_empty_on_bad_json(self, mock_run) -> None:  # noqa: ANN001
        """Returns empty list on unparseable output."""
        result = MagicMock()
        result.stdout = b"not json"
        mock_run.return_value = result
        backend = LmSensorBackend()
        assert backend.scan() == []
