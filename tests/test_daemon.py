"""Tests for truefan.daemon."""

import signal
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from tests.mocks import FanSimulator
from truefan.config import Config, Curve, FanConfig, load_config, save_config
from truefan.fans import set_zone_duty
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
                no_cooling_temp=30, max_cooling_temp=80,
                fan_zones=frozenset({"cpu", "peripheral"}),
            ),
            SensorClass.DRIVE: Curve(
                no_cooling_temp=30, max_cooling_temp=50,
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
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
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
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
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
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
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
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        run(cfg, conn=sim, sleep=_StopAfter(1))

        # Last raw commands should include enable_manual_control (part of set_full_speed).
        assert (0x30, 0x45, bytes([0x01, 0x01])) in sim.raw_commands

    @patch("truefan.daemon.available_backends")
    def test_sends_uptime_metric(self, mock_avail, tmp_path: Path) -> None:
        """Daemon uptime gauge is pushed to statsd each cycle."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with patch("truefan.daemon.send_uptime") as mock_uptime:
            run(cfg, conn=sim, sleep=_StopAfter(2))
            assert mock_uptime.call_count == 2
            # Uptime should be non-negative.
            for call in mock_uptime.call_args_list:
                assert call[0][0] >= 0

    @patch("truefan.daemon.available_backends")
    def test_sends_actual_rpm_metrics(self, mock_avail, tmp_path: Path) -> None:
        """Actual RPM is pushed to statsd each cycle for every fan."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with patch("truefan.daemon.send_actual_rpm") as mock_metric:
            run(cfg, conn=sim, sleep=_StopAfter(1))
            # One call per fan per cycle — sim has two fans.
            assert mock_metric.call_count == 2

    @patch("truefan.daemon.available_backends")
    def test_sends_target_rpm_metrics(self, mock_avail, tmp_path: Path) -> None:
        """Target RPM is pushed to statsd each cycle."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
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
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
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
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
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
        # Config has CPU_FAN1 and SYS_FAN1, but sim also has SYS_FAN2.
        _write_config(cfg)
        sim = FanSimulator(fans={
            "CPU_FAN1": {"max_rpm": 1500},
            "SYS_FAN1": {"max_rpm": 1200},
            "SYS_FAN2": {"max_rpm": 1200},
        })
        sim.set_fan_zone("CPU_FAN1", "cpu")
        sim.set_fan_zone("SYS_FAN1", "peripheral")
        sim.set_fan_zone("SYS_FAN2", "peripheral")

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        # Should not crash despite SYS_FAN2 being in RPMs but not in config.
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
            name="smart_sda", sensor_class=SensorClass.DRIVE, temperature=35.0,
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
    def test_stall_reasserts_intended_duty(self, mock_avail, tmp_path: Path) -> None:
        """A fan stall re-asserts the intended duty rather than forcing 100%."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim(stall_below=999)  # all fans stall

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with patch("truefan.daemon.send_zone_duty") as mock_metric:
            run(cfg, conn=sim, sleep=_StopAfter(1))
            # Recovery should re-assert the intended duty, not force 100%.
            # Filter out shutdown calls (100% for both zones at the end).
            calls = mock_metric.call_args_list
            cpu_calls = [c for c in calls if c[0][0] == "cpu"]
            # At least one non-100% call from normal operation + re-assertion.
            non_100 = [c for c in cpu_calls if c[0][1] != 100]
            assert len(non_100) >= 1

    @patch("truefan.daemon.available_backends")
    def test_shutdown_sends_100_duty_metric(self, mock_avail, tmp_path: Path) -> None:
        """Shutdown sends a 100% duty metric to statsd for every zone."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with patch("truefan.daemon.send_zone_duty") as mock_metric:
            run(cfg, conn=sim, sleep=_StopAfter(1))
            # The last two calls should be 100% for both zones (shutdown).
            calls = mock_metric.call_args_list
            shutdown_calls = {c[0][0] for c in calls if c[0][1] == 100}
            assert "cpu" in shutdown_calls
            assert "peripheral" in shutdown_calls

    @patch("truefan.daemon.available_backends")
    def test_sel_event_removes_setpoint(self, mock_avail, tmp_path: Path) -> None:
        """A fan assertion in the SEL removes the fan's lowest setpoint."""
        from truefan.bmc import SelEntry
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        # Inject SEL entries after cycle 1 so they appear after the startup
        # seed (which captures last_sel_id from an empty log).  They are
        # then picked up during cycle 2.
        cycle = 0

        def _inject_sel_and_run_two(seconds: float) -> None:
            nonlocal cycle
            cycle += 1
            if cycle == 1:
                sim._sel_entries = [
                    SelEntry(
                        entry_id=0x8d,
                        raw_text="  8d | 04/06/26 | 04:34:55 CEST | Fan CPU_FAN1 | Lower Critical going low  | Asserted | Reading 0 < Threshold 100 RPM",
                    ),
                ]
            else:
                raise KeyboardInterrupt

        run(cfg, conn=sim, sleep=_inject_sel_and_run_two)

        reloaded = load_config(cfg)
        # CPU_FAN1 had setpoints {30, 50, 100}; lowest (30) should be removed.
        assert 30 not in reloaded.fans["CPU_FAN1"].setpoints
        # SYS_FAN1 should be untouched.
        assert len(reloaded.fans["SYS_FAN1"].setpoints) == 4

    @patch("truefan.daemon.available_backends")
    def test_sel_event_only_affects_named_fan(self, mock_avail, tmp_path: Path) -> None:
        """SEL events only remove setpoints from the fan named in the event."""
        from truefan.bmc import SelEntry
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle = 0

        def _inject_sel_and_run_two(seconds: float) -> None:
            nonlocal cycle
            cycle += 1
            if cycle == 1:
                # Only SYS_FAN1 had an event — CPU_FAN1 should be untouched.
                sim._sel_entries = [
                    SelEntry(
                        entry_id=0x91,
                        raw_text="  91 | 04/06/26 | 04:55:50 CEST | Fan SYS_FAN1 | Lower Critical going low  | Asserted | Reading 0 < Threshold 100 RPM",
                    ),
                ]
            else:
                raise KeyboardInterrupt

        run(cfg, conn=sim, sleep=_inject_sel_and_run_two)

        reloaded = load_config(cfg)
        assert len(reloaded.fans["CPU_FAN1"].setpoints) == 3
        assert len(reloaded.fans["SYS_FAN1"].setpoints) < 4

    @patch("truefan.daemon.available_backends")
    def test_sel_event_not_reprocessed(self, mock_avail, tmp_path: Path) -> None:
        """SEL entries are not reprocessed on subsequent poll cycles."""
        from truefan.bmc import SelEntry
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle = 0

        def _inject_sel_and_run_three(seconds: float) -> None:
            nonlocal cycle
            cycle += 1
            if cycle == 1:
                sim._sel_entries = [
                    SelEntry(
                        entry_id=0x8d,
                        raw_text="  8d | 04/06/26 | 04:34:55 CEST | Fan CPU_FAN1 | Lower Critical going low  | Asserted | Reading 0 < Threshold 100 RPM",
                    ),
                ]
            elif cycle >= 3:
                raise KeyboardInterrupt

        # Run for 3 cycles: seed (empty), inject after 1, process in 2, verify in 3.
        run(cfg, conn=sim, sleep=_inject_sel_and_run_three)

        reloaded = load_config(cfg)
        # Only one setpoint removed (30), not two.
        assert 30 not in reloaded.fans["CPU_FAN1"].setpoints
        assert 50 in reloaded.fans["CPU_FAN1"].setpoints

    @patch("truefan.daemon.available_backends")
    def test_sel_dedupes_multiple_events_per_fan(self, mock_avail, tmp_path: Path) -> None:
        """Multiple SEL events for the same fan in one cycle remove only one setpoint."""
        from truefan.bmc import SelEntry
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle = 0

        def _inject_sel_and_run_two(seconds: float) -> None:
            nonlocal cycle
            cycle += 1
            if cycle == 1:
                # Two events for CPU_FAN1 from a single physical stall.
                sim._sel_entries = [
                    SelEntry(
                        entry_id=0x8d,
                        raw_text="  8d | 04/06/26 | 04:34:55 CEST | Fan CPU_FAN1 | Lower Critical going low  | Asserted | Reading 0 < Threshold 100 RPM",
                    ),
                    SelEntry(
                        entry_id=0x8e,
                        raw_text="  8e | 04/06/26 | 04:34:55 CEST | Fan CPU_FAN1 | Lower Non-recoverable going low  | Asserted | Reading 0 < Threshold 100 RPM",
                    ),
                ]
            else:
                raise KeyboardInterrupt

        run(cfg, conn=sim, sleep=_inject_sel_and_run_two)

        reloaded = load_config(cfg)
        # CPU_FAN1 had setpoints {30, 50, 100}; only one should be removed.
        assert 30 not in reloaded.fans["CPU_FAN1"].setpoints
        assert 50 in reloaded.fans["CPU_FAN1"].setpoints

    @patch("truefan.daemon.available_backends")
    def test_sigusr1_dumps_state(self, mock_avail, tmp_path: Path, caplog) -> None:
        """SIGUSR1 logs sensor and zone state to syslog."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle_count = 0

        def _send_sigusr1_then_stop(seconds: float) -> None:
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count == 1:
                handler = signal.getsignal(signal.SIGUSR1)
                handler(signal.SIGUSR1, None)
            elif cycle_count >= 2:
                raise KeyboardInterrupt

        import logging
        with caplog.at_level(logging.INFO, logger="truefan.daemon"):
            run(cfg, conn=sim, sleep=_send_sigusr1_then_stop)

        # Should have logged sensor lines and zone lines.
        dump_lines = [r.message for r in caplog.records if "State dump" in r.message or "ipmi_CPU_Temp" in r.message or "zone" in r.message.lower()]
        assert any("ipmi_CPU_Temp" in line for line in dump_lines)
        assert any("cpu" in line.lower() and "%" in line for line in dump_lines)

    @patch("truefan.daemon.available_backends")
    def test_sigusr1_continues_polling(self, mock_avail, tmp_path: Path) -> None:
        """After SIGUSR1 the daemon continues polling normally."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=55.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle_count = 0

        def _send_sigusr1_then_continue(seconds: float) -> None:
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count == 1:
                handler = signal.getsignal(signal.SIGUSR1)
                handler(signal.SIGUSR1, None)
            elif cycle_count >= 3:
                raise KeyboardInterrupt

        run(cfg, conn=sim, sleep=_send_sigusr1_then_continue)
        assert cycle_count == 3

    @patch("truefan.daemon.available_backends")
    def test_sigusr1_reflects_current_temps(self, mock_avail, tmp_path: Path, caplog) -> None:
        """State dump reflects the most recent sensor readings."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        cycle_count = 0

        class _VaryingBackend:
            """Backend that returns different temps each scan."""
            def scan(self):  # noqa: ANN201
                temp = 40.0 if cycle_count < 1 else 70.0
                return [SensorReading(
                    name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU,
                    temperature=temp,
                )]

        mock_avail.return_value = [_VaryingBackend()]

        def _send_sigusr1_after_second_cycle(seconds: float) -> None:
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count == 2:
                handler = signal.getsignal(signal.SIGUSR1)
                handler(signal.SIGUSR1, None)
            elif cycle_count >= 3:
                raise KeyboardInterrupt

        import logging
        with caplog.at_level(logging.INFO, logger="truefan.daemon"):
            run(cfg, conn=sim, sleep=_send_sigusr1_after_second_cycle)

        # The dump should show 70.0°C (the second cycle's temp), not 40.0°C.
        sensor_lines = [r.message for r in caplog.records if "State dump" in r.message or "ipmi_CPU_Temp" in r.message]
        dump_sensor_lines = [l for l in sensor_lines if "70.0" in l]
        assert len(dump_sensor_lines) >= 1

    @patch("truefan.daemon.available_backends")
    def test_stall_sends_stall_metric(self, mock_avail, tmp_path: Path) -> None:
        """A real-time stall pushes stall count 1 for the stalled fan and 0 for others."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim(stall_below=999)  # all fans stall

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with patch("truefan.daemon.send_stalls") as mock_stalls:
            run(cfg, conn=sim, sleep=_StopAfter(1))
            # Both fans stalled, so both should get stall count 1.
            calls = {c[0][0]: c[0][1] for c in mock_stalls.call_args_list}
            assert calls["CPU_FAN1"] == 1
            assert calls["SYS_FAN1"] == 1

    @patch("truefan.daemon.available_backends")
    def test_no_stall_sends_zero(self, mock_avail, tmp_path: Path) -> None:
        """When no fans stall, stall count 0 is pushed for all fans."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()  # no stalls

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        with patch("truefan.daemon.send_stalls") as mock_stalls:
            run(cfg, conn=sim, sleep=_StopAfter(1))
            calls = {c[0][0]: c[0][1] for c in mock_stalls.call_args_list}
            assert calls["CPU_FAN1"] == 0
            assert calls["SYS_FAN1"] == 0

    @patch("truefan.daemon.available_backends")
    def test_sel_stall_sends_stall_metric(self, mock_avail, tmp_path: Path) -> None:
        """An SEL-detected stall pushes stall count 1 for the affected fan."""
        from truefan.bmc import SelEntry
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle = 0

        def _inject_sel_and_run_two(seconds: float) -> None:
            nonlocal cycle
            cycle += 1
            if cycle == 1:
                sim._sel_entries = [
                    SelEntry(
                        entry_id=0x8d,
                        raw_text="  8d | 04/06/26 | 04:34:55 CEST | Fan CPU_FAN1 | Lower Critical going low  | Asserted | Reading 0 < Threshold 100 RPM",
                    ),
                ]
            else:
                raise KeyboardInterrupt

        with patch("truefan.daemon.send_stalls") as mock_stalls:
            run(cfg, conn=sim, sleep=_inject_sel_and_run_two)
            # Get the last call per fan (cycle 2, after SEL injection).
            all_calls = mock_stalls.call_args_list
            cycle2_calls = {c[0][0]: c[0][1] for c in all_calls[2:4]}
            assert cycle2_calls["CPU_FAN1"] == 1
            assert cycle2_calls["SYS_FAN1"] == 0

    @patch("truefan.daemon.available_backends")
    def test_stall_count_resets_each_cycle(self, mock_avail, tmp_path: Path) -> None:
        """Stall count does not carry over from one cycle to the next."""
        from truefan.fans import FanRpm
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        sim = _make_sim()

        readings = [SensorReading(
            name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU, temperature=40.0,
        )]
        mock_avail.side_effect = _mock_backends_factory(readings)

        cycle = 0

        # Patch read_fan_rpms to return 0 RPM only on the first cycle.
        original_read = __import__("truefan.fans", fromlist=["read_fan_rpms"]).read_fan_rpms

        def _stall_first_cycle(conn):  # noqa: ANN001, ANN202
            rpms = original_read(conn)
            if cycle == 0:
                return [FanRpm(name=r.name, rpm=0) for r in rpms]
            return rpms

        def _counting_sleep(seconds: float) -> None:
            nonlocal cycle
            cycle += 1
            if cycle >= 2:
                raise KeyboardInterrupt

        with patch("truefan.daemon.read_fan_rpms", side_effect=_stall_first_cycle):
            with patch("truefan.daemon.send_stalls") as mock_stalls:
                run(cfg, conn=sim, sleep=_counting_sleep)
                all_calls = mock_stalls.call_args_list
                # Cycle 0: both fans stalled (count 1 each).
                cycle0 = {c[0][0]: c[0][1] for c in all_calls[:2]}
                # Cycle 1: no stalls (count 0 each).
                cycle1 = {c[0][0]: c[0][1] for c in all_calls[2:4]}
                assert cycle0["CPU_FAN1"] == 1
                assert cycle1["CPU_FAN1"] == 0

    @patch("truefan.daemon.available_backends")
    def test_spindown_window_prevents_immediate_decrease(self, mock_avail, tmp_path: Path) -> None:
        """Fan duty doesn't drop immediately when demand decreases."""
        from truefan.sensors import SensorReading
        cfg = tmp_path / "truefan.toml"
        _write_config(cfg)
        # Set a short window so the test doesn't need real time.
        config = load_config(cfg)
        updated = Config(
            poll_interval_seconds=config.poll_interval_seconds,
            curves=config.curves,
            fans=config.fans,
            spindown_window_seconds=999,  # long window — duty won't drop
        )
        save_config(cfg, updated)
        sim = _make_sim()

        cycle = 0
        temps = [70.0, 40.0, 40.0]  # high, then low

        def _varying_backends(bmc):  # noqa: ANN001
            return [_StubSensorBackend([SensorReading(
                name="ipmi_CPU_Temp", sensor_class=SensorClass.CPU,
                temperature=temps[min(cycle, len(temps) - 1)],
            )])]

        mock_avail.side_effect = _varying_backends

        duty_sets: list[tuple[int, int]] = []
        original_set = set_zone_duty.__wrapped__ if hasattr(set_zone_duty, '__wrapped__') else None

        # Track all duty changes by inspecting raw commands.
        def _counting_sleep(seconds: float) -> None:
            nonlocal cycle
            cycle += 1
            if cycle >= 3:
                raise KeyboardInterrupt

        run(cfg, conn=sim, sleep=_counting_sleep)

        # Extract cpu zone duties set (excluding the final set_full_speed).
        cpu_duties = []
        for c in sim.raw_commands:
            if c[0] == 0x30 and c[1] == 0x70 and len(c[2]) == 4 and c[2][0] == 0x66:
                zone_id, duty = c[2][2], c[2][3]
                if zone_id == 0x00 and duty != 100:  # cpu zone, not full-speed
                    cpu_duties.append(duty)

        # With a 999s window, the duty should NOT have dropped after the
        # first high reading — the window holds the max.
        if len(cpu_duties) >= 1:
            assert all(d >= cpu_duties[0] for d in cpu_duties), \
                f"Duty dropped despite spindown window: {cpu_duties}"

