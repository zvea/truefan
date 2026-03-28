"""Tests for truefan.sensors.available_backends."""

from unittest.mock import patch

from truefan.bmc import BmcConnection, TemperatureSensorData
from truefan.sensors import available_backends
from truefan.sensors.ipmi import IpmiSensorBackend
from truefan.sensors.lmsensors import LmSensorBackend
from truefan.sensors.nvme import NvmeSensorBackend
from truefan.sensors.smart import SmartSensorBackend


class StubBmc(BmcConnection):
    """Minimal BmcConnection for testing."""

    def raw_command(self, netfn: int, command: int, data: bytes = b"") -> bytes:
        return b""

    def set_sensor_thresholds(
        self, sensor_name: str,
        lower: tuple[int, int, int], upper: tuple[int, int, int],
    ) -> None:
        pass

    def list_fans(self) -> list[tuple[str, int | None]]:
        return []

    def list_temperature_sensors(self) -> list[TemperatureSensorData]:
        return []


def _which(tools: set[str]):  # noqa: ANN202
    """Return a shutil.which mock that finds only the given tools."""
    def _mock_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in tools else None
    return _mock_which


# ---------------------------------------------------------------------------
# #### available_backends
# ---------------------------------------------------------------------------

class TestAvailableBackends:
    """Tests for available_backends."""

    @patch("shutil.which", side_effect=_which({"smartctl", "nvme", "sensors"}))
    def test_includes_ipmi_when_bmc_provided(self, mock_which) -> None:  # noqa: ANN001
        """IPMI backend is included when a BmcConnection is provided."""
        backends = available_backends(StubBmc())
        assert any(isinstance(b, IpmiSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which({"smartctl", "nvme", "sensors"}))
    def test_excludes_ipmi_when_no_bmc(self, mock_which) -> None:  # noqa: ANN001
        """IPMI backend is excluded when no BmcConnection is provided."""
        backends = available_backends(None)
        assert not any(isinstance(b, IpmiSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which({"smartctl"}))
    def test_includes_smart_when_available(self, mock_which) -> None:  # noqa: ANN001
        """SMART backend is included when smartctl is on PATH."""
        backends = available_backends(None)
        assert any(isinstance(b, SmartSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which(set()))
    def test_excludes_smart_when_missing(self, mock_which) -> None:  # noqa: ANN001
        """SMART backend is excluded when smartctl is not on PATH."""
        backends = available_backends(None)
        assert not any(isinstance(b, SmartSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which({"nvme"}))
    def test_includes_nvme_when_available(self, mock_which) -> None:  # noqa: ANN001
        """NVMe backend is included when nvme is on PATH."""
        backends = available_backends(None)
        assert any(isinstance(b, NvmeSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which(set()))
    def test_excludes_nvme_when_missing(self, mock_which) -> None:  # noqa: ANN001
        """NVMe backend is excluded when nvme is not on PATH."""
        backends = available_backends(None)
        assert not any(isinstance(b, NvmeSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which({"sensors"}))
    def test_includes_lmsensors_when_available(self, mock_which) -> None:  # noqa: ANN001
        """lm-sensors backend is included when sensors is on PATH."""
        backends = available_backends(None)
        assert any(isinstance(b, LmSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which(set()))
    def test_excludes_lmsensors_when_missing(self, mock_which) -> None:  # noqa: ANN001
        """lm-sensors backend is excluded when sensors is not on PATH."""
        backends = available_backends(None)
        assert not any(isinstance(b, LmSensorBackend) for b in backends)

    @patch("shutil.which", side_effect=_which(set()))
    def test_empty_when_nothing_available(self, mock_which) -> None:  # noqa: ANN001
        """Returns empty list when no tools and no BMC."""
        backends = available_backends(None)
        assert backends == []
