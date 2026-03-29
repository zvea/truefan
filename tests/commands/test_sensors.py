"""Tests for truefan.commands.sensors."""

from unittest.mock import patch

from truefan.bmc import BmcConnection, TemperatureSensorData
from truefan.commands.sensors import run_sensors
from truefan.sensors import SensorClass, SensorReading
from truefan.sensors.ipmi import IpmiSensorBackend


class MockBmc(BmcConnection):
    """Canned BMC data for the sensors command."""

    def raw_command(self, netfn: int, command: int, data: bytes = b"") -> bytes:
        return b""

    def set_sensor_thresholds(
        self, sensor_name: str,
        lower: tuple[int, int, int], upper: tuple[int, int, int],
    ) -> None:
        pass

    def list_fans(self) -> list[tuple[str, int | None]]:
        return [
            ("CPU_FAN1", 1300),
            ("CPU_FAN2", None),
            ("SYS_FAN1", 900),
        ]

    def list_temperature_sensors(self) -> list[TemperatureSensorData]:
        return [
            TemperatureSensorData(name="CPU Temp", temperature=31.0, upper_non_critical=80.0, upper_critical=100.0),
            TemperatureSensorData(name="System Temp", temperature=33.0),
        ]


def _mock_backends(bmc):  # noqa: ANN001, ANN202
    """Return only the IPMI backend with our mock."""
    return [IpmiSensorBackend(bmc)]


class TestRunSensors:
    """Tests for the sensors subcommand output."""

    @patch("truefan.commands.sensors.available_backends", side_effect=_mock_backends)
    def test_prints_temperature_header(self, mock_backends, capsys) -> None:  # noqa: ANN001
        """Output includes the temperature sensors header."""
        run_sensors(conn=MockBmc())
        out = capsys.readouterr().out
        assert "Temperature sensors" in out
        assert "CLASS" in out
        assert "SENSOR" in out

    @patch("truefan.commands.sensors.available_backends", side_effect=_mock_backends)
    def test_prints_temperature_readings(self, mock_backends, capsys) -> None:  # noqa: ANN001
        """Output includes temperature readings with thresholds."""
        run_sensors(conn=MockBmc())
        out = capsys.readouterr().out
        assert "ipmi_CPU_Temp" in out
        assert "31.0" in out
        assert "80.0" in out
        assert "100.0" in out

    @patch("truefan.commands.sensors.available_backends", side_effect=_mock_backends)
    def test_prints_fan_header(self, mock_backends, capsys) -> None:  # noqa: ANN001
        """Output includes the fan sensors header."""
        run_sensors(conn=MockBmc())
        out = capsys.readouterr().out
        assert "Fan sensors" in out
        assert "FAN" in out
        assert "ZONE" in out
        assert "RPM" in out

    @patch("truefan.commands.sensors.available_backends", side_effect=_mock_backends)
    def test_prints_fan_readings(self, mock_backends, capsys) -> None:  # noqa: ANN001
        """Output includes fan RPMs and zone mappings."""
        run_sensors(conn=MockBmc())
        out = capsys.readouterr().out
        assert "CPU_FAN1" in out
        assert "1300" in out
        assert "cpu" in out

    @patch("truefan.commands.sensors.available_backends", side_effect=_mock_backends)
    def test_inactive_fan_shows_dash(self, mock_backends, capsys) -> None:  # noqa: ANN001
        """Fans without readings show a dash."""
        run_sensors(conn=MockBmc())
        out = capsys.readouterr().out
        # CPU_FAN2 line should have a dash for RPM
        lines = [l for l in out.splitlines() if "CPU_FAN2" in l]
        assert len(lines) == 1
        assert "-" in lines[0]

    @patch("truefan.commands.sensors.available_backends", side_effect=_mock_backends)
    def test_missing_threshold_shows_dash(self, mock_backends, capsys) -> None:  # noqa: ANN001
        """Sensors without thresholds show dashes."""
        run_sensors(conn=MockBmc())
        out = capsys.readouterr().out
        # System Temp has no thresholds in our mock
        lines = [l for l in out.splitlines() if "System_Temp" in l]
        assert len(lines) == 1
        # Should have dashes for MAX and CRIT
        assert lines[0].count("-") >= 2

    def test_unknown_fan_prefix_shows_question_mark(self, capsys) -> None:
        """Fans with unknown prefixes show '?' for zone."""

        class MockBmcWithUnknownFan(MockBmc):
            def list_fans(self) -> list[tuple[str, int | None]]:
                return [("WEIRD_FAN1", 500)]

        with patch("truefan.commands.sensors.available_backends", side_effect=_mock_backends):
            run_sensors(conn=MockBmcWithUnknownFan())
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if "WEIRD_FAN1" in l]
        assert len(lines) == 1
        assert "?" in lines[0]

    def test_no_bmc_shows_available_sensors(self, capsys) -> None:
        """Without IPMI, shows non-IPMI sensors and a message about fans."""
        readings = [
            SensorReading(name="smart_sda", sensor_class=SensorClass.DRIVE, temperature=35.0),
        ]

        def _non_ipmi_backends(bmc):  # noqa: ANN001, ANN202
            from truefan.sensors import SensorBackend

            class FakeBackend(SensorBackend):
                def scan(self) -> list[SensorReading]:
                    return readings

            return [FakeBackend()]

        with patch("truefan.commands.sensors.ipmi_device_present", return_value=False), \
             patch("truefan.commands.sensors.available_backends", side_effect=_non_ipmi_backends):
            run_sensors()

        out = capsys.readouterr().out
        assert "smart_sda" in out
        assert "35.0" in out
        assert "No IPMI device" in out
        assert "Fan sensors" not in out
