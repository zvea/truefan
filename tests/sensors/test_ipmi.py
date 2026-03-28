"""Tests for truefan.sensors.ipmi."""

from truefan.bmc import BmcConnection, TemperatureSensorData
from truefan.sensors import SensorClass
from truefan.sensors.ipmi import IpmiSensorBackend


class MockBmcConnection(BmcConnection):
    """Returns canned temperature data matching the X11SCA-F."""

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
        return [
            TemperatureSensorData(name="CPU Temp", temperature=31.0, upper_non_critical=80.0, upper_critical=100.0),
            TemperatureSensorData(name="PCH Temp", temperature=47.0, upper_non_critical=84.0, upper_critical=105.0),
            TemperatureSensorData(name="System Temp", temperature=33.0, upper_non_critical=79.0, upper_critical=90.0),
            TemperatureSensorData(name="Peripheral Temp", temperature=38.0, upper_non_critical=79.0, upper_critical=90.0),
            TemperatureSensorData(name="VcpuVRM Temp", temperature=33.0, upper_non_critical=94.0, upper_critical=105.0),
            TemperatureSensorData(name="M2NVMeSSD Temp1", temperature=None, upper_non_critical=79.0, upper_critical=90.0),
            TemperatureSensorData(name="M2NVMeSSD Temp2", temperature=None, upper_non_critical=79.0, upper_critical=90.0),
            TemperatureSensorData(name="U2NVMeSSD Temp", temperature=None, upper_non_critical=67.0, upper_critical=75.0),
            TemperatureSensorData(name="DIMMA1 Temp", temperature=34.0, upper_non_critical=79.0, upper_critical=90.0),
            TemperatureSensorData(name="DIMMA2 Temp", temperature=35.0, upper_non_critical=79.0, upper_critical=90.0),
            TemperatureSensorData(name="DIMMB1 Temp", temperature=35.0, upper_non_critical=79.0, upper_critical=90.0),
            TemperatureSensorData(name="DIMMB2 Temp", temperature=34.0, upper_non_critical=79.0, upper_critical=90.0),
        ]


# ---------------------------------------------------------------------------
# #### IpmiSensorBackend.scan
# ---------------------------------------------------------------------------

class TestIpmiSensorBackend:
    """Tests for IpmiSensorBackend."""

    def test_classifies_cpu_temp(self) -> None:
        """CPU Temp is classified as cpu."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        cpu = [r for r in readings if r.name == "ipmi/CPU Temp"]
        assert len(cpu) == 1
        assert cpu[0].sensor_class == SensorClass.CPU
        assert cpu[0].temperature == 31.0

    def test_classifies_ambient(self) -> None:
        """System Temp and Peripheral Temp are classified as ambient."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        ambient = [r for r in readings if r.sensor_class == SensorClass.AMBIENT]
        names = {r.name for r in ambient}
        assert "ipmi/System Temp" in names
        assert "ipmi/Peripheral Temp" in names

    def test_classifies_dimm_as_other(self) -> None:
        """DIMM temps are classified as other."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        dimm = [r for r in readings if "DIMM" in r.name]
        assert all(r.sensor_class == SensorClass.OTHER for r in dimm)

    def test_classifies_pch_as_other(self) -> None:
        """PCH Temp is classified as other."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        pch = [r for r in readings if r.name == "ipmi/PCH Temp"]
        assert len(pch) == 1
        assert pch[0].sensor_class == SensorClass.OTHER

    def test_skips_no_reading(self) -> None:
        """Sensors with no reading are skipped."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        names = {r.name for r in readings}
        assert "ipmi/M2NVMeSSD Temp1" not in names
        assert "ipmi/U2NVMeSSD Temp" not in names

    def test_sensor_names_prefixed(self) -> None:
        """All sensor names are prefixed with ipmi/."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        assert all(r.name.startswith("ipmi/") for r in readings)

    def test_nvme_classification(self) -> None:
        """M2NVMeSSD and U2NVMeSSD sensors are classified as nvme (when present)."""
        from truefan.sensors.ipmi import _classify
        assert _classify("M2NVMeSSD Temp1") == SensorClass.NVME
        assert _classify("U2NVMeSSD Temp") == SensorClass.NVME

    def test_carries_thresholds(self) -> None:
        """IPMI thresholds are passed through as temp_max and temp_crit."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        cpu = [r for r in readings if r.name == "ipmi/CPU Temp"][0]
        assert cpu.temp_max == 80.0
        assert cpu.temp_crit == 100.0

    def test_pch_thresholds(self) -> None:
        """PCH sensor carries its own thresholds."""
        backend = IpmiSensorBackend(MockBmcConnection())
        readings = backend.scan()
        pch = [r for r in readings if r.name == "ipmi/PCH Temp"][0]
        assert pch.temp_max == 84.0
        assert pch.temp_crit == 105.0
