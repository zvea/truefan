"""Tests for truefan.bmc."""

import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from truefan.bmc import BmcError, IpmitoolConnection, check_ipmi_access, ipmi_device_present


_FAN_CSV = (
    "CPU_FAN1,1300,RPM,ok\n"
    "CPU_FAN2,,,ns\n"
    "SYS_FAN1,900,RPM,ok\n"
    "SYS_FAN2,1100,RPM,ok\n"
    "SYS_FAN3,900,RPM,ok\n"
)

# Verbose CSV: name,value,unit,status,entity,entity_type,sensor_type,col7,col8,col9,unc,ucr,...
_TEMP_CSV_V = (
    "CPU Temp,31,degrees C,ok,3.1,Processor,Temperature,20.000,11.000,80.000,100.000,100.000,95.000,5.000,5.000,10.000,0.000,255.000\n"
    "PCH Temp,46,degrees C,ok,7.1,System Board,Temperature,20.000,11.000,84.000,105.000,90.000,85.000,5.000,5.000,10.000,0.000,255.000\n"
    "System Temp,33,degrees C,ok,7.2,System Board,Temperature,20.000,11.000,79.000,90.000,85.000,80.000,5.000,5.000,10.000,0.000,255.000\n"
    "M2NVMeSSD Temp1,,,ns,7.48,System Board,Temperature,20.000,11.000,79.000,90.000,85.000,80.000,5.000,5.000,10.000,0.000,255.000\n"
    "DIMMA1 Temp,34,degrees C,ok,32.1,Memory Device,Temperature,20.000,11.000,79.000,90.000,85.000,80.000,5.000,5.000,10.000,0.000,255.000\n"
)


def _make_result(stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.stdout = stdout.encode()
    return result


# ---------------------------------------------------------------------------
# #### ipmi_device_present
# ---------------------------------------------------------------------------

class TestIpmiDevicePresent:
    """Tests for ipmi_device_present."""

    @patch("truefan.bmc.os.path.exists", return_value=False)
    def test_no_device(self, mock_exists) -> None:  # noqa: ANN001
        """Returns False when no IPMI device nodes exist."""
        assert ipmi_device_present() is False

    @patch("truefan.bmc.os.path.exists", side_effect=lambda p: p == "/dev/ipmi0")
    def test_ipmi0_exists(self, mock_exists) -> None:  # noqa: ANN001
        """Returns True when /dev/ipmi0 exists."""
        assert ipmi_device_present() is True

    @patch("truefan.bmc.os.path.exists", side_effect=lambda p: p == "/dev/ipmidev/0")
    def test_ipmidev0_exists(self, mock_exists) -> None:  # noqa: ANN001
        """Returns True when an alternate device path exists."""
        assert ipmi_device_present() is True


# ---------------------------------------------------------------------------
# #### check_ipmi_access
# ---------------------------------------------------------------------------

class TestCheckIpmiAccess:
    """Tests for check_ipmi_access."""

    @patch("truefan.bmc.os.path.exists", return_value=False)
    def test_no_device(self, mock_exists) -> None:  # noqa: ANN001
        """Returns error about missing device when none exist."""
        result = check_ipmi_access()
        assert result is not None
        assert "No IPMI device" in result

    @patch("truefan.bmc.os.access", return_value=False)
    @patch("truefan.bmc.os.path.exists", side_effect=lambda p: p == "/dev/ipmi0")
    def test_no_permission(self, mock_exists, mock_access) -> None:  # noqa: ANN001
        """Returns error about permissions when device exists but is not accessible."""
        result = check_ipmi_access()
        assert result is not None
        assert "Permission denied" in result
        assert "root" in result

    @patch("truefan.bmc.os.access", return_value=True)
    @patch("truefan.bmc.os.path.exists", side_effect=lambda p: p == "/dev/ipmi0")
    def test_accessible(self, mock_exists, mock_access) -> None:  # noqa: ANN001
        """Returns None when device exists and is accessible."""
        assert check_ipmi_access() is None


# ---------------------------------------------------------------------------
# #### IpmitoolConnection.list_fans
# ---------------------------------------------------------------------------

class TestListFans:
    """Tests for IpmitoolConnection.list_fans."""

    @patch("truefan.bmc.subprocess.run")
    def test_parses_active_fans(self, mock_run) -> None:  # noqa: ANN001
        """Active fans return their RPM."""
        mock_run.return_value = _make_result(_FAN_CSV)
        conn = IpmitoolConnection()
        fans = conn.list_fans()
        rpm_map = {name: rpm for name, rpm in fans}
        assert rpm_map["CPU_FAN1"] == 1300
        assert rpm_map["SYS_FAN1"] == 900
        assert rpm_map["SYS_FAN2"] == 1100

    @patch("truefan.bmc.subprocess.run")
    def test_inactive_fans_return_none(self, mock_run) -> None:  # noqa: ANN001
        """Fans with no reading return None."""
        mock_run.return_value = _make_result(_FAN_CSV)
        conn = IpmitoolConnection()
        fans = conn.list_fans()
        rpm_map = {name: rpm for name, rpm in fans}
        assert rpm_map["CPU_FAN2"] is None

    @patch("truefan.bmc.subprocess.run")
    def test_calls_correct_command(self, mock_run) -> None:  # noqa: ANN001
        """Calls ipmitool sdr type fan -c."""
        mock_run.return_value = _make_result(_FAN_CSV)
        conn = IpmitoolConnection()
        conn.list_fans()
        args = mock_run.call_args[0][0]
        assert args == ["/usr/bin/ipmitool", "sdr", "type", "fan", "-c"]


# ---------------------------------------------------------------------------
# #### IpmitoolConnection.list_temperature_sensors
# ---------------------------------------------------------------------------

class TestListTemperatureSensors:
    """Tests for IpmitoolConnection.list_temperature_sensors."""

    @patch("truefan.bmc.subprocess.run")
    def test_parses_active_sensors(self, mock_run) -> None:  # noqa: ANN001
        """Active sensors return their temperature."""
        mock_run.return_value = _make_result(_TEMP_CSV_V)
        conn = IpmitoolConnection()
        temps = conn.list_temperature_sensors()
        temp_map = {s.name: s.temperature for s in temps}
        assert temp_map["CPU Temp"] == 31.0
        assert temp_map["PCH Temp"] == 46.0
        assert temp_map["DIMMA1 Temp"] == 34.0

    @patch("truefan.bmc.subprocess.run")
    def test_inactive_sensors_return_none(self, mock_run) -> None:  # noqa: ANN001
        """Sensors with no reading return None temperature."""
        mock_run.return_value = _make_result(_TEMP_CSV_V)
        conn = IpmitoolConnection()
        temps = conn.list_temperature_sensors()
        temp_map = {s.name: s.temperature for s in temps}
        assert temp_map["M2NVMeSSD Temp1"] is None

    @patch("truefan.bmc.subprocess.run")
    def test_calls_correct_command(self, mock_run) -> None:  # noqa: ANN001
        """Calls ipmitool sdr type temperature -c -v."""
        mock_run.return_value = _make_result(_TEMP_CSV_V)
        conn = IpmitoolConnection()
        conn.list_temperature_sensors()
        args = mock_run.call_args[0][0]
        assert args == ["/usr/bin/ipmitool", "sdr", "type", "temperature", "-c", "-v"]

    @patch("truefan.bmc.subprocess.run")
    def test_parses_thresholds(self, mock_run) -> None:  # noqa: ANN001
        """Upper non-critical and upper critical thresholds are parsed."""
        mock_run.return_value = _make_result(_TEMP_CSV_V)
        conn = IpmitoolConnection()
        temps = conn.list_temperature_sensors()
        cpu = [s for s in temps if s.name == "CPU Temp"][0]
        assert cpu.upper_non_critical == 80.0
        assert cpu.upper_critical == 100.0
        pch = [s for s in temps if s.name == "PCH Temp"][0]
        assert pch.upper_non_critical == 84.0
        assert pch.upper_critical == 105.0


# ---------------------------------------------------------------------------
# #### IpmitoolConnection.raw_command
# ---------------------------------------------------------------------------

class TestRawCommand:
    """Tests for IpmitoolConnection.raw_command."""

    @patch("truefan.bmc.subprocess.run")
    def test_builds_correct_command(self, mock_run) -> None:  # noqa: ANN001
        """Builds correct ipmitool raw command line."""
        mock_run.return_value = _make_result("")
        conn = IpmitoolConnection()
        conn.raw_command(0x30, 0x45, bytes([0x01, 0x01]))
        args = mock_run.call_args[0][0]
        assert args == ["/usr/bin/ipmitool", "raw", "0x30", "0x45", "0x01", "0x01"]

    @patch("truefan.bmc.subprocess.run")
    def test_returns_empty_on_no_output(self, mock_run) -> None:  # noqa: ANN001
        """Returns empty bytes when ipmitool returns no output."""
        mock_run.return_value = _make_result("")
        conn = IpmitoolConnection()
        result = conn.raw_command(0x30, 0x45, bytes([0x01, 0x01]))
        assert result == b""

    @patch("truefan.bmc.subprocess.run")
    def test_parses_hex_response(self, mock_run) -> None:  # noqa: ANN001
        """Parses hex byte response from ipmitool."""
        mock_run.return_value = _make_result(" 01 02 ff\n")
        conn = IpmitoolConnection()
        result = conn.raw_command(0x06, 0x01)
        assert result == bytes([0x01, 0x02, 0xFF])


# ---------------------------------------------------------------------------
# #### IpmitoolConnection.set_sensor_thresholds
# ---------------------------------------------------------------------------

class TestSetSensorThresholds:
    """Tests for IpmitoolConnection.set_sensor_thresholds."""

    @patch("truefan.bmc.subprocess.run")
    def test_calls_lower_and_upper(self, mock_run) -> None:  # noqa: ANN001
        """Calls ipmitool sensor thresh with lower and upper separately."""
        mock_run.return_value = _make_result("")
        conn = IpmitoolConnection()
        conn.set_sensor_thresholds("CPU_FAN1", (100, 100, 100), (25000, 25000, 25000))
        assert mock_run.call_count == 2
        lower_args = mock_run.call_args_list[0][0][0]
        upper_args = mock_run.call_args_list[1][0][0]
        assert lower_args == [
            "/usr/bin/ipmitool", "sensor", "thresh", "CPU_FAN1",
            "lower", "100", "100", "100",
        ]
        assert upper_args == [
            "/usr/bin/ipmitool", "sensor", "thresh", "CPU_FAN1",
            "upper", "25000", "25000", "25000",
        ]


# ---------------------------------------------------------------------------
# #### IpmitoolConnection._run error reporting
# ---------------------------------------------------------------------------

class TestRunErrorMessage:
    """Tests for error messages when ipmitool fails."""

    @patch("truefan.bmc.subprocess.run")
    def test_error_contains_full_command(self, mock_run) -> None:  # noqa: ANN001
        """BmcError message includes the exact command as a readable string."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["/usr/bin/ipmitool", "sensor", "thresh", "CPU_FAN2",
                 "lower", "100", "100", "100"],
            stderr=b"Error setting threshold: Unspecified error",
        )
        conn = IpmitoolConnection()
        with pytest.raises(BmcError, match=(
            r"/usr/bin/ipmitool sensor thresh CPU_FAN2 lower 100 100 100"
        )):
            conn.set_sensor_thresholds("CPU_FAN2", (100, 100, 100), (25000, 25000, 25000))

    @patch("truefan.bmc.subprocess.run")
    def test_error_contains_stderr(self, mock_run) -> None:  # noqa: ANN001
        """BmcError message includes ipmitool's stderr output."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["/usr/bin/ipmitool", "raw", "0x30", "0x45"],
            stderr=b"Unable to send RAW command",
        )
        conn = IpmitoolConnection()
        with pytest.raises(BmcError, match=r"Unable to send RAW command"):
            conn.raw_command(0x30, 0x45)


# ---------------------------------------------------------------------------
# #### IpmitoolConnection._run retry behaviour
# ---------------------------------------------------------------------------

class TestRunRetry:
    """Tests for ipmitool command retry on transient failures."""

    @patch("truefan.bmc.time.sleep")
    @patch("truefan.bmc.subprocess.run")
    def test_succeeds_first_try(self, mock_run, mock_sleep) -> None:  # noqa: ANN001
        """No retry or warning when the command succeeds immediately."""
        mock_run.return_value = _make_result("ok\n")
        conn = IpmitoolConnection()
        conn.list_fans()
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    @patch("truefan.bmc.time.sleep")
    @patch("truefan.bmc.subprocess.run")
    def test_retries_once_then_succeeds(self, mock_run, mock_sleep, caplog) -> None:  # noqa: ANN001
        """Retries after one failure, returns result, logs one warning."""
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "ipmitool", stderr=b"SDR error"),
            _make_result(_FAN_CSV),
        ]
        conn = IpmitoolConnection()
        with caplog.at_level(logging.WARNING, logger="truefan.bmc"):
            fans = conn.list_fans()
        assert len(fans) == 5
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once_with(1)
        assert sum("attempt 1/3 failed" in r.message for r in caplog.records) == 1

    @patch("truefan.bmc.time.sleep")
    @patch("truefan.bmc.subprocess.run")
    def test_retries_twice_then_succeeds(self, mock_run, mock_sleep, caplog) -> None:  # noqa: ANN001
        """Retries after two failures, returns result, logs two warnings."""
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "ipmitool", stderr=b"SDR error"),
            subprocess.CalledProcessError(1, "ipmitool", stderr=b"SDR error"),
            _make_result(_FAN_CSV),
        ]
        conn = IpmitoolConnection()
        with caplog.at_level(logging.WARNING, logger="truefan.bmc"):
            fans = conn.list_fans()
        assert len(fans) == 5
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2
        assert sum("attempt 1/3 failed" in r.message for r in caplog.records) == 1
        assert sum("attempt 2/3 failed" in r.message for r in caplog.records) == 1

    @patch("truefan.bmc.time.sleep")
    @patch("truefan.bmc.subprocess.run")
    def test_all_attempts_fail(self, mock_run, mock_sleep, caplog) -> None:  # noqa: ANN001
        """Raises BmcError after three failures, logs only two warnings (not the last)."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "ipmitool", stderr=b"SDR error",
        )
        conn = IpmitoolConnection()
        with caplog.at_level(logging.WARNING, logger="truefan.bmc"):
            with pytest.raises(BmcError):
                conn.list_fans()
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2
        warning_count = sum("failed" in r.message for r in caplog.records
                           if r.levelno == logging.WARNING)
        assert warning_count == 2
