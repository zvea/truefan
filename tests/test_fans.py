"""Tests for truefan.fans."""

import pytest

from truefan.bmc import BmcConnection, TemperatureSensorData
from truefan.fans import (
    FanControlError,
    FanRpm,
    detect_fans,
    enable_manual_control,
    fan_zone,
    read_fan_rpms,
    reset_thresholds,
    set_full_speed,
    set_zone_duty,
)


# ---------------------------------------------------------------------------
# Mock IPMI connection
# ---------------------------------------------------------------------------

class MockBmcConnection(BmcConnection):
    """Records commands and returns canned data matching the X11SCA-F."""

    def __init__(self) -> None:
        self.raw_commands: list[tuple[int, int, bytes]] = []
        self.threshold_calls: list[tuple[str, tuple[int, int, int], tuple[int, int, int]]] = []

    def raw_command(self, netfn: int, command: int, data: bytes = b"") -> bytes:
        """Record the command and return empty (success)."""
        self.raw_commands.append((netfn, command, data))
        return b""

    def set_sensor_thresholds(
        self,
        sensor_name: str,
        lower: tuple[int, int, int],
        upper: tuple[int, int, int],
    ) -> None:
        """Record the threshold call."""
        self.threshold_calls.append((sensor_name, lower, upper))

    def list_fans(self) -> list[tuple[str, int | None]]:
        """Return data matching X11SCA-F with CPU_FAN2 absent."""
        return [
            ("CPU_FAN1", 1300),
            ("CPU_FAN2", None),
            ("SYS_FAN1", 900),
            ("SYS_FAN2", 1100),
            ("SYS_FAN3", 900),
        ]

    def list_temperature_sensors(self) -> list[TemperatureSensorData]:
        """Not used by fans.py tests."""
        return []

    def read_sel(self, last_n: int = 20) -> list:
        """No-op for tests."""
        return []


# ---------------------------------------------------------------------------
# #### fan_zone
# ---------------------------------------------------------------------------

class TestFanZone:
    """Tests for fan_zone."""

    def test_cpu_fan(self) -> None:
        """CPU_ prefix maps to cpu zone."""
        assert fan_zone("CPU_FAN1") == "cpu"

    def test_sys_fan(self) -> None:
        """SYS_ prefix maps to peripheral zone."""
        assert fan_zone("SYS_FAN3") == "peripheral"

    def test_unknown_prefix(self) -> None:
        """Unknown prefix raises FanControlError."""
        with pytest.raises(FanControlError):
            fan_zone("UNKNOWN_FAN1")


# ---------------------------------------------------------------------------
# #### detect_fans
# ---------------------------------------------------------------------------

class TestDetectFans:
    """Tests for detect_fans."""

    def test_returns_active_fans_only(self) -> None:
        """Only fans with an RPM reading are returned."""
        conn = MockBmcConnection()
        fans = detect_fans(conn)
        assert "CPU_FAN1" in fans
        assert "CPU_FAN2" not in fans
        assert "SYS_FAN1" in fans

    def test_correct_zone_mapping(self) -> None:
        """Fans are mapped to the correct zones."""
        conn = MockBmcConnection()
        fans = detect_fans(conn)
        assert fans["CPU_FAN1"] == "cpu"
        assert fans["SYS_FAN1"] == "peripheral"
        assert fans["SYS_FAN2"] == "peripheral"
        assert fans["SYS_FAN3"] == "peripheral"


# ---------------------------------------------------------------------------
# #### reset_thresholds
# ---------------------------------------------------------------------------

class TestResetThresholds:
    """Tests for reset_thresholds."""

    def test_sets_thresholds_for_all_fans(self) -> None:
        """Calls set_sensor_thresholds for every fan (including inactive)."""
        conn = MockBmcConnection()
        reset_thresholds(conn)
        fan_names = [name for name, _, _ in conn.threshold_calls]
        assert "CPU_FAN1" in fan_names
        assert "CPU_FAN2" in fan_names
        assert "SYS_FAN1" in fan_names

    def test_threshold_values(self) -> None:
        """Lower thresholds are 100 RPM, upper are 25000 RPM."""
        conn = MockBmcConnection()
        reset_thresholds(conn)
        for _, lower, upper in conn.threshold_calls:
            assert lower == (100, 100, 100)
            assert upper == (25000, 25000, 25000)


# ---------------------------------------------------------------------------
# #### enable_manual_control
# ---------------------------------------------------------------------------

class TestEnableManualControl:
    """Tests for enable_manual_control."""

    def test_sends_correct_raw_command(self) -> None:
        """Sends netfn=0x30, cmd=0x45, data=0x01 0x01."""
        conn = MockBmcConnection()
        enable_manual_control(conn)
        assert (0x30, 0x45, bytes([0x01, 0x01])) in conn.raw_commands


# ---------------------------------------------------------------------------
# #### set_full_speed
# ---------------------------------------------------------------------------

class TestSetFullSpeed:
    """Tests for set_full_speed."""

    def test_enables_manual_and_sets_both_zones(self) -> None:
        """Enables manual mode and sets cpu and peripheral to 100%."""
        conn = MockBmcConnection()
        set_full_speed(conn)
        assert (0x30, 0x45, bytes([0x01, 0x01])) in conn.raw_commands
        # cpu zone (0x00) at 100%
        assert (0x30, 0x70, bytes([0x66, 0x01, 0x00, 0x64])) in conn.raw_commands
        # peripheral zone (0x01) at 100%
        assert (0x30, 0x70, bytes([0x66, 0x01, 0x01, 0x64])) in conn.raw_commands


# ---------------------------------------------------------------------------
# #### set_zone_duty
# ---------------------------------------------------------------------------

class TestSetZoneDuty:
    """Tests for set_zone_duty."""

    def test_cpu_zone(self) -> None:
        """CPU zone sends zone id 0x00."""
        conn = MockBmcConnection()
        set_zone_duty(conn, "cpu", 50)
        assert (0x30, 0x70, bytes([0x66, 0x01, 0x00, 0x32])) in conn.raw_commands

    def test_peripheral_zone(self) -> None:
        """Peripheral zone sends zone id 0x01."""
        conn = MockBmcConnection()
        set_zone_duty(conn, "peripheral", 75)
        assert (0x30, 0x70, bytes([0x66, 0x01, 0x01, 0x4B])) in conn.raw_commands

    def test_unknown_zone(self) -> None:
        """Unknown zone raises FanControlError."""
        conn = MockBmcConnection()
        with pytest.raises(FanControlError):
            set_zone_duty(conn, "unknown", 50)

    def test_duty_out_of_range(self) -> None:
        """Duty outside 0-100 raises FanControlError."""
        conn = MockBmcConnection()
        with pytest.raises(FanControlError):
            set_zone_duty(conn, "cpu", 101)
        with pytest.raises(FanControlError):
            set_zone_duty(conn, "cpu", -1)


# ---------------------------------------------------------------------------
# #### read_fan_rpms
# ---------------------------------------------------------------------------

class TestReadFanRpms:
    """Tests for read_fan_rpms."""

    def test_returns_active_fans(self) -> None:
        """Returns FanRpm for fans with readings."""
        conn = MockBmcConnection()
        rpms = read_fan_rpms(conn)
        names = {r.name for r in rpms}
        assert "CPU_FAN1" in names
        assert "SYS_FAN1" in names
        assert "SYS_FAN2" in names

    def test_skips_inactive_fans(self) -> None:
        """Fans without readings are not included."""
        conn = MockBmcConnection()
        rpms = read_fan_rpms(conn)
        names = {r.name for r in rpms}
        assert "CPU_FAN2" not in names

    def test_correct_rpm_values(self) -> None:
        """RPM values match the mock data."""
        conn = MockBmcConnection()
        rpms = read_fan_rpms(conn)
        rpm_map = {r.name: r.rpm for r in rpms}
        assert rpm_map["CPU_FAN1"] == 1300
        assert rpm_map["SYS_FAN1"] == 900
        assert rpm_map["SYS_FAN2"] == 1100
