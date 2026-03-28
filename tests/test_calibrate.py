"""Tests for truefan.calibrate."""

from types import MappingProxyType

import pytest

from tests.mocks import FanSimulator, noop_sleep
from truefan.bmc import TemperatureSensorData
from truefan.calibrate import (
    CalibrationError,
    CalibrationResult,
    calibrate_fans,
    remove_lowest_setpoint,
)
from truefan.config import FanConfig


# ---------------------------------------------------------------------------
# #### remove_lowest_setpoint
# ---------------------------------------------------------------------------

class TestRemoveLowestSetpoint:
    """Tests for remove_lowest_setpoint."""

    def test_removes_lowest(self) -> None:
        """Removes the lowest duty setpoint."""
        fc = FanConfig(
            zone="peripheral",
            setpoints=MappingProxyType({20: 300, 40: 600, 60: 900, 100: 1500}),
        )
        result = remove_lowest_setpoint(fc)
        assert 20 not in result.setpoints
        assert dict(result.setpoints) == {40: 600, 60: 900, 100: 1500}

    def test_two_setpoints(self) -> None:
        """With two setpoints, removes the lower one."""
        fc = FanConfig(
            zone="cpu",
            setpoints=MappingProxyType({30: 450, 100: 1500}),
        )
        result = remove_lowest_setpoint(fc)
        assert dict(result.setpoints) == {100: 1500}

    def test_single_setpoint_unchanged(self) -> None:
        """Single setpoint is never removed."""
        fc = FanConfig(
            zone="cpu",
            setpoints=MappingProxyType({50: 800}),
        )
        result = remove_lowest_setpoint(fc)
        assert dict(result.setpoints) == {50: 800}

    def test_never_removes_100(self) -> None:
        """The 100% setpoint is never removed even if it's the lowest."""
        fc = FanConfig(
            zone="cpu",
            setpoints=MappingProxyType({100: 1500}),
        )
        result = remove_lowest_setpoint(fc)
        assert dict(result.setpoints) == {100: 1500}

    def test_preserves_zone(self) -> None:
        """Zone value is preserved."""
        fc = FanConfig(
            zone="peripheral",
            setpoints=MappingProxyType({20: 300, 100: 1500}),
        )
        result = remove_lowest_setpoint(fc)
        assert result.zone == "peripheral"


# ---------------------------------------------------------------------------
# #### calibrate_fans
# ---------------------------------------------------------------------------

class TestCalibrateFans:
    """Tests for calibrate_fans."""

    def test_normal_ramp_down(self) -> None:
        """Full ramp-down with no stall produces setpoints at every test point."""
        sim = FanSimulator(fans={
            "CPU_FAN1": {"max_rpm": 1500, "stall_below": 0},
        })
        sim.set_fan_zone("CPU_FAN1", "cpu")
        results = calibrate_fans(
            sim, {"CPU_FAN1": "cpu"}, sleep=noop_sleep,
        )
        assert len(results) == 1
        r = results[0]
        assert r.fan_name == "CPU_FAN1"
        assert r.zone == "cpu"
        # Should have a setpoint for every test point
        assert set(r.setpoints.keys()) == {100, 90, 80, 70, 60, 50, 40, 30, 20, 10}
        # RPMs should decrease with duty
        duties = sorted(r.setpoints.keys())
        for i in range(1, len(duties)):
            assert r.setpoints[duties[i]] > r.setpoints[duties[i - 1]]

    def test_stall_at_duty_zero_rpm(self) -> None:
        """Fan stalls (zero RPM) partway down — minimum setpoint is last good duty."""
        sim = FanSimulator(fans={
            "SYS_FAN1": {"max_rpm": 1200, "stall_below": 40},
        })
        sim.set_fan_zone("SYS_FAN1", "peripheral")
        results = calibrate_fans(
            sim, {"SYS_FAN1": "peripheral"}, sleep=noop_sleep,
        )
        r = results[0]
        # Should have setpoints for 100, 90, 80, 70, 60, 50, 40 — not 30, 20, 10
        assert min(r.setpoints.keys()) == 40
        assert 30 not in r.setpoints
        assert 20 not in r.setpoints

    def test_stall_bmc_reset(self) -> None:
        """Fan stalls and BMC resets to full speed (RPM increases) — detected as stall."""
        sim = FanSimulator(fans={
            "SYS_FAN2": {"max_rpm": 1100, "stall_below": 50, "bmc_reset": True},
        })
        sim.set_fan_zone("SYS_FAN2", "peripheral")
        results = calibrate_fans(
            sim, {"SYS_FAN2": "peripheral"}, sleep=noop_sleep,
        )
        r = results[0]
        # Below 50%, BMC resets → RPM spikes → detected as stall
        assert min(r.setpoints.keys()) == 50
        assert 40 not in r.setpoints

    def test_fan_never_spins(self) -> None:
        """Fan that never produces RPM raises CalibrationError."""
        sim = FanSimulator(fans={
            "CPU_FAN1": {"max_rpm": 1500, "stall_below": 999},
        })
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(CalibrationError, match="CPU_FAN1"):
            calibrate_fans(sim, {"CPU_FAN1": "cpu"}, sleep=noop_sleep)

    def test_other_zones_at_100_during_calibration(self) -> None:
        """Zones not being calibrated stay at 100%."""
        sim = FanSimulator(fans={
            "CPU_FAN1": {"max_rpm": 1500, "stall_below": 0},
            "SYS_FAN1": {"max_rpm": 1200, "stall_below": 0},
        })
        sim.set_fan_zone("CPU_FAN1", "cpu")
        sim.set_fan_zone("SYS_FAN1", "peripheral")
        calibrate_fans(
            sim,
            {"CPU_FAN1": "cpu", "SYS_FAN1": "peripheral"},
            sleep=noop_sleep,
        )
        # Both zones should have results
        assert len(sim.raw_commands) > 0
        # set_full_speed is called before each zone calibration
        full_speed_cmds = [
            c for c in sim.raw_commands
            if c == (0x30, 0x45, bytes([0x01, 0x01]))
        ]
        # At least 3: before zone 1, before zone 2, and after calibration
        assert len(full_speed_cmds) >= 3

    def test_multiple_fans_same_zone(self) -> None:
        """Multiple fans in the same zone are calibrated together."""
        sim = FanSimulator(fans={
            "SYS_FAN1": {"max_rpm": 1200, "stall_below": 30},
            "SYS_FAN2": {"max_rpm": 1100, "stall_below": 40},
        })
        sim.set_fan_zone("SYS_FAN1", "peripheral")
        sim.set_fan_zone("SYS_FAN2", "peripheral")
        results = calibrate_fans(
            sim,
            {"SYS_FAN1": "peripheral", "SYS_FAN2": "peripheral"},
            sleep=noop_sleep,
        )
        assert len(results) == 2
        r1 = [r for r in results if r.fan_name == "SYS_FAN1"][0]
        r2 = [r for r in results if r.fan_name == "SYS_FAN2"][0]
        # SYS_FAN1 stalls below 30, SYS_FAN2 stalls below 40
        assert min(r1.setpoints.keys()) == 30
        assert min(r2.setpoints.keys()) == 40

    def test_sleep_called_between_steps(self) -> None:
        """Sleep is called with SETTLE_SECONDS between duty changes."""
        sleep_calls: list[float] = []

        def _record_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        sim = FanSimulator(fans={
            "CPU_FAN1": {"max_rpm": 1500, "stall_below": 0},
        })
        sim.set_fan_zone("CPU_FAN1", "cpu")
        calibrate_fans(sim, {"CPU_FAN1": "cpu"}, sleep=_record_sleep)
        assert all(s == 10.0 for s in sleep_calls)
        # At least one sleep per test point + initial settle
        assert len(sleep_calls) >= len((100, 90, 80, 70, 60, 50, 40, 30, 20, 10))

    def test_thermal_abort_before_start(self) -> None:
        """Aborts before calibration if temps are already dangerous."""
        sim = FanSimulator(
            fans={"CPU_FAN1": {"max_rpm": 1500, "stall_below": 0}},
            temps=[
                TemperatureSensorData(
                    name="CPU Temp", temperature=92.0, upper_critical=100.0,
                ),
            ],
        )
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(CalibrationError, match="THERMAL ABORT"):
            calibrate_fans(sim, {"CPU_FAN1": "cpu"}, sleep=noop_sleep)

    def test_thermal_abort_during_ramp(self) -> None:
        """Aborts mid-calibration if a sensor gets too hot."""

        class WarmingSimulator(FanSimulator):
            """Simulates temps rising as fans slow down."""

            def __init__(self) -> None:
                super().__init__(
                    fans={"CPU_FAN1": {"max_rpm": 1500, "stall_below": 0}},
                    temps=[
                        TemperatureSensorData(
                            name="CPU Temp", temperature=40.0,
                            upper_critical=100.0,
                        ),
                    ],
                )
                self._call_count = 0

            def list_temperature_sensors(self) -> list[TemperatureSensorData]:
                """Temps rise with each call, eventually hitting the limit."""
                self._call_count += 1
                temp = 40.0 + self._call_count * 10.0
                return [
                    TemperatureSensorData(
                        name="CPU Temp", temperature=temp,
                        upper_critical=100.0,
                    ),
                ]

        sim = WarmingSimulator()
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(CalibrationError, match="THERMAL ABORT"):
            calibrate_fans(sim, {"CPU_FAN1": "cpu"}, sleep=noop_sleep)

    def test_thermal_abort_uses_default_when_no_crit(self) -> None:
        """Uses 80°C as the abort threshold when no upper_critical is known."""
        sim = FanSimulator(
            fans={"CPU_FAN1": {"max_rpm": 1500, "stall_below": 0}},
            temps=[
                TemperatureSensorData(name="Unknown Sensor", temperature=82.0),
            ],
        )
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(CalibrationError, match="THERMAL ABORT"):
            calibrate_fans(sim, {"CPU_FAN1": "cpu"}, sleep=noop_sleep)

    def test_thermal_check_skips_none_temperature(self) -> None:
        """Sensors with no reading are skipped during thermal check."""
        sim = FanSimulator(
            fans={"CPU_FAN1": {"max_rpm": 1500, "stall_below": 0}},
            temps=[
                TemperatureSensorData(name="M2NVMeSSD Temp1", temperature=None),
                TemperatureSensorData(name="CPU Temp", temperature=40.0, upper_critical=100.0),
            ],
        )
        sim.set_fan_zone("CPU_FAN1", "cpu")
        # Should not abort — the None sensor is skipped, CPU is fine.
        results = calibrate_fans(sim, {"CPU_FAN1": "cpu"}, sleep=noop_sleep)
        assert len(results) == 1

    def test_thermal_abort_sets_full_speed(self) -> None:
        """Fans are set to 100% when thermal abort triggers."""
        sim = FanSimulator(
            fans={"CPU_FAN1": {"max_rpm": 1500, "stall_below": 0}},
            temps=[
                TemperatureSensorData(
                    name="CPU Temp", temperature=95.0, upper_critical=100.0,
                ),
            ],
        )
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(CalibrationError):
            calibrate_fans(sim, {"CPU_FAN1": "cpu"}, sleep=noop_sleep)
        # Verify full speed was set (enable_manual_control command)
        assert (0x30, 0x45, bytes([0x01, 0x01])) in sim.raw_commands
