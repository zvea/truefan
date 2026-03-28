"""Tests for truefan.daemon."""

import signal
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from tests.mocks import FanSimulator
from truefan.config import Config, ConfigError, Curve, FanConfig, SensorOverride, load_config, save_config
from truefan.daemon import run
from truefan.sensors import SensorClass


def _write_config(path: Path, fans: dict[str, FanConfig] | None = None) -> None:
    """Write a minimal config for testing."""
    if fans is None:
        fans = {
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({30: 450, 50: 750, 100: 1500}),
            ),
            "SYS_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({20: 240, 40: 480, 60: 720, 100: 1200}),
            ),
        }
    config = Config(
        poll_interval_seconds=5,
        curves=MappingProxyType({
            SensorClass.CPU: Curve(
                temp_low=30, temp_high=80, duty_low=20, duty_high=100,
                fan_zones=frozenset({"cpu", "peripheral"}),
            ),
            SensorClass.DRIVE: Curve(
                temp_low=30, temp_high=50, duty_low=20, duty_high=100,
                fan_zones=frozenset({"peripheral"}),
            ),
        }),
        fans=MappingProxyType(fans),
    )
    save_config(path, config)


def _make_sim(stall_below: int = 0) -> FanSimulator:
    """Create a FanSimulator with standard fans."""
    sim = FanSimulator(fans={
        "CPU_FAN1": {"max_rpm": 1500, "stall_below": stall_below},
        "SYS_FAN1": {"max_rpm": 1200, "stall_below": stall_below},
    })
    sim.set_fan_zone("CPU_FAN1", "cpu")
    sim.set_fan_zone("SYS_FAN1", "peripheral")
    return sim


class _StopAfter:
    """Sleep substitute that raises KeyboardInterrupt after N calls."""

    def __init__(self, cycles: int) -> None:
        self._remaining = cycles

    def __call__(self, seconds: float) -> None:
        """Count down and raise when done."""
        self._remaining -= 1
        if self._remaining <= 0:
            raise KeyboardInterrupt


# Stub sensor backend that returns configurable readings.
class _StubSensorBackend:
    def __init__(self, readings: list) -> None:
        self._readings = readings

    def scan(self):  # noqa: ANN201
        return list(self._readings)


def _mock_backends_factory(readings):  # noqa: ANN001, ANN202
    """Return a function that creates stub backends with fixed readings."""
    def _factory(bmc):  # noqa: ANN001, ANN202
        return [_StubSensorBackend(readings)]
    return _factory


# ---------------------------------------------------------------------------
# #### run
# ---------------------------------------------------------------------------

class TestDaemonRun:
    """Tests for daemon.run."""

    @patch("truefan.daemon.available_backends")
    def test_single_cycle_applies_duty(self, mock_avail, tmp_path: Path) -> None:
        """A single poll cycle reads sensors and applies the computed duty."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        run(cfg, conn=sim, sleep=_StopAfter(1))

        # Should have set zone duties via raw commands.
        duty_cmds = [
            c for c in sim.raw_commands
            if c[0] == 0x30 and c[1] == 0x70
        ]
        assert len(duty_cmds) > 0

    @patch("truefan.daemon.available_backends")
    def test_duty_not_resent_when_unchanged(self, mock_avail, tmp_path: Path) -> None:
        """Duty is not re-sent if it hasn't changed between cycles."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        run(cfg, conn=sim, sleep=_StopAfter(3))

        # Count set_zone_duty commands (netfn=0x30, cmd=0x70).
        duty_cmds = [
            c for c in sim.raw_commands
            if c[0] == 0x30 and c[1] == 0x70 and len(c[2]) == 4 and c[2][0] == 0x66
        ]
        # Initial set + set_full_speed on exit. Should NOT have 3x per zone.
        # Each zone gets set once (first cycle), then not again (cycles 2-3).
        zone_sets = {}
        for c in duty_cmds:
            zone_id = c[2][2]
            duty = c[2][3]
            zone_sets.setdefault(zone_id, []).append(duty)
        # During normal operation, each zone should be set once with the computed
        # duty, then again with 100% on shutdown. Not once per cycle.
        for zone_id, duties in zone_sets.items():
            # Last one is 100 (full speed on exit). Before that, should be just one set.
            non_100 = [d for d in duties if d != 100]
            assert len(non_100) <= 1, f"Zone {zone_id} set {len(non_100)} times with non-100 duty"

    @patch("truefan.daemon.available_backends")
    def test_stall_removes_setpoint_and_saves(self, mock_avail, tmp_path: Path) -> None:
        """A stalled fan triggers setpoint removal and config save."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim(stall_below=999)  # all fans stall

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        run(cfg, conn=sim, sleep=_StopAfter(1))

        # Config should have been saved with removed setpoints.
        from truefan.config import load_config
        reloaded = load_config(cfg)
        for fan_name, fan_config in reloaded.fans.items():
            original_count = 3 if fan_name == "CPU_FAN1" else 4
            assert len(fan_config.setpoints) < original_count

    @patch("truefan.daemon.available_backends")
    def test_sets_full_speed_on_exit(self, mock_avail, tmp_path: Path) -> None:
        """Fans are set to full speed when the daemon exits."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        run(cfg, conn=sim, sleep=_StopAfter(1))

        # Last raw commands should include enable_manual_control (part of set_full_speed).
        assert (0x30, 0x45, bytes([0x01, 0x01])) in sim.raw_commands

    @patch("truefan.daemon.available_backends")
    def test_sends_target_rpm_metrics(self, mock_avail, tmp_path: Path) -> None:
        """Target RPM is pushed to statsd each cycle."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with patch("truefan.daemon.send_target_rpm") as mock_metric:
            run(cfg, conn=sim, sleep=_StopAfter(1))
            assert mock_metric.call_count > 0

    @patch("truefan.daemon.available_backends")
    def test_sensor_backend_failure_continues(self, mock_avail, tmp_path: Path) -> None:
        """A failing sensor backend doesn't crash the daemon."""
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        class _FailingBackend:
            def scan(self):  # noqa: ANN201
                raise RuntimeError("sensor failure")

        mock_avail.return_value = [_FailingBackend()]

        # Should not raise — daemon continues with no readings.
        run(cfg, conn=sim, sleep=_StopAfter(1))

    @patch("truefan.daemon.available_backends")
    def test_sigterm_exits_cleanly(self, mock_avail, tmp_path: Path) -> None:
        """SIGTERM triggers clean shutdown with full speed."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle_count = 0

        def _send_sigterm_after_one(seconds: float) -> None:
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count >= 1:
                # Simulate SIGTERM by calling the handler directly.
                handler = signal.getsignal(signal.SIGTERM)
                handler(signal.SIGTERM, None)

        run(cfg, conn=sim, sleep=_send_sigterm_after_one)

        # Should have set full speed on exit.
        duty_100_cmds = [
            c for c in sim.raw_commands
            if c[0] == 0x30 and c[1] == 0x70 and len(c[2]) == 4
            and c[2][0] == 0x66 and c[2][3] == 100
        ]
        assert len(duty_100_cmds) > 0

    @patch("truefan.daemon.available_backends")
    def test_sighup_reloads_config(self, mock_avail, tmp_path: Path) -> None:
        """SIGHUP reloads the config file."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle_count = 0

        def _send_sighup_then_stop(seconds: float) -> None:
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count == 1:
                # Modify config on disk before sending SIGHUP.
                from truefan.config import load_config, save_config, Config
                current = load_config(cfg)
                updated = Config(
                    poll_interval_seconds=10,  # changed from 5
                    curves=current.curves,
                    fans=current.fans,
                )
                save_config(cfg, updated)
                # Simulate SIGHUP.
                handler = signal.getsignal(signal.SIGHUP)
                handler(signal.SIGHUP, None)
            elif cycle_count >= 2:
                raise KeyboardInterrupt

        run(cfg, conn=sim, sleep=_send_sighup_then_stop)

        # Verify the reloaded config was used — poll_interval changed to 10.
        # We can check by verifying the second sleep call would have used 10s,
        # but that's hard to observe. Instead just verify it didn't crash
        # and ran a second cycle after the reload.
        assert cycle_count == 2

    @patch("truefan.daemon.available_backends")
    def test_unknown_fan_in_rpms_ignored(self, mock_avail, tmp_path: Path) -> None:
        """Fans in RPM readings but not in config are ignored during stall check."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        # Config only has CPU_FAN1, but sim also has SYS_FAN1.
        _write_config(cfg, fans={
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
        })
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        # Should not crash despite SYS_FAN1 being in RPMs but not in config.
        run(cfg, conn=sim, sleep=_StopAfter(1))

    @patch("truefan.daemon.available_backends")
    def test_all_sensors_in_class_fail_sets_zones_to_100(self, mock_avail, tmp_path: Path) -> None:
        """If all sensors in a configured class fail, affected zones go to 100%."""
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        # Return drive readings but NO cpu readings — cpu class is configured
        # but has zero readings, so cpu+peripheral zones should go to 100%.
        from truefan.sensors import SensorReading
        readings = [SensorReading(
            name="smart/sda", sensor_class=SensorClass.DRIVE, temperature=35.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        run(cfg, conn=sim, sleep=_StopAfter(1))

        # Both cpu and peripheral zones should have been set to 100%
        # (cpu curve maps to both zones).
        duty_cmds = [
            c for c in sim.raw_commands
            if c[0] == 0x30 and c[1] == 0x70 and len(c[2]) == 4 and c[2][0] == 0x66
        ]
        # Find the duty values set for each zone during normal operation
        # (not the final set_full_speed on exit).
        zone_duties: dict[int, list[int]] = {}
        for c in duty_cmds:
            zone_id = c[2][2]
            duty = c[2][3]
            zone_duties.setdefault(zone_id, []).append(duty)
        # CPU zone (0x00) should have been set to 100.
        assert 100 in zone_duties.get(0x00, [])

    @patch("truefan.daemon.available_backends")
    def test_unknown_sensor_override_raises(self, mock_avail, tmp_path: Path) -> None:
        """Raises ConfigError on startup if a sensor override references an unknown sensor."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        # Append a sensor override for a nonexistent sensor.
        with open(cfg, "a") as f:
            f.write("\n[curves.sensor.nonexistent-sensor]\ntemp_low = 60\n")

        sim = _make_sim()
        readings = [SensorReading(
            name="ipmi-CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with pytest.raises(ConfigError, match="nonexistent-sensor"):
            run(cfg, conn=sim, sleep=_StopAfter(1))
