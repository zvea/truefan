"""Tests for truefan.commands.init."""

import sys
from pathlib import Path

import pytest

from tests.mocks import FanSimulator, noop_sleep
from truefan.bmc import TemperatureSensorData
from truefan.commands.init import run_init
from truefan.config import load_config
from truefan.pidfile import PidFile
from truefan.sensors import SensorClass


def _make_sim() -> FanSimulator:
    """Create a FanSimulator matching the X11SCA-F layout with temp sensors."""
    sim = FanSimulator(
        fans={
            "CPU_FAN1": {"max_rpm": 1500, "stall_below": 30},
            "SYS_FAN1": {"max_rpm": 1200, "stall_below": 20},
            "SYS_FAN2": {"max_rpm": 1100, "stall_below": 20},
            "SYS_FAN3": {"max_rpm": 900, "stall_below": 30},
        },
        temps=[
            TemperatureSensorData(name="CPU Temp", temperature=35.0, upper_non_critical=80.0, upper_critical=100.0),
            TemperatureSensorData(name="System Temp", temperature=33.0, upper_non_critical=79.0, upper_critical=90.0),
        ],
    )
    sim.set_fan_zone("CPU_FAN1", "cpu")
    sim.set_fan_zone("SYS_FAN1", "peripheral")
    sim.set_fan_zone("SYS_FAN2", "peripheral")
    sim.set_fan_zone("SYS_FAN3", "peripheral")
    return sim


# ---------------------------------------------------------------------------
# #### run_init
# ---------------------------------------------------------------------------

class TestRunInit:
    """Tests for run_init."""

    def test_creates_config(self, tmp_path: Path) -> None:
        """Creates a config file with calibrated fan entries."""
        cfg = tmp_path / "truefan.toml"
        run_init(cfg, conn=_make_sim(), sleep=noop_sleep)
        assert cfg.exists()

    def test_config_loadable(self, tmp_path: Path) -> None:
        """Generated config can be loaded back."""
        cfg = tmp_path / "truefan.toml"
        run_init(cfg, conn=_make_sim(), sleep=noop_sleep)
        config = load_config(cfg)
        from truefan.config import DEFAULT_POLL_INTERVAL_SECONDS
        assert config.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS
        assert "CPU_FAN1" in config.fans
        assert "SYS_FAN1" in config.fans

    def test_fan_setpoints_populated(self, tmp_path: Path) -> None:
        """Each fan has a non-empty setpoint table."""
        cfg = tmp_path / "truefan.toml"
        run_init(cfg, conn=_make_sim(), sleep=noop_sleep)
        config = load_config(cfg)
        for fan_name, fan_config in config.fans.items():
            assert len(fan_config.setpoints) > 0, f"{fan_name} has no setpoints"
            assert 100 in fan_config.setpoints, f"{fan_name} missing 100% setpoint"

    def test_fan_zones_correct(self, tmp_path: Path) -> None:
        """Fan zones match the detected layout."""
        cfg = tmp_path / "truefan.toml"
        run_init(cfg, conn=_make_sim(), sleep=noop_sleep)
        config = load_config(cfg)
        assert config.fans["CPU_FAN1"].zone == "cpu"
        assert config.fans["SYS_FAN1"].zone == "peripheral"

    def test_refuses_existing_config(self, tmp_path: Path) -> None:
        """Refuses to overwrite an existing config file."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("existing")
        with pytest.raises(SystemExit):
            run_init(cfg, conn=_make_sim(), sleep=noop_sleep)

    def test_no_fans_detected(self, tmp_path: Path) -> None:
        """Exits with error when no fans are detected."""
        sim = FanSimulator(fans={})
        cfg = tmp_path / "truefan.toml"
        with pytest.raises(SystemExit):
            run_init(cfg, conn=sim, sleep=noop_sleep)
        assert not cfg.exists()

    def test_detected_classes_get_curves(self, tmp_path: Path) -> None:
        """Only detected sensor classes get curves in the config."""
        cfg = tmp_path / "truefan.toml"
        run_init(cfg, conn=_make_sim(), sleep=noop_sleep)
        config = load_config(cfg)
        # Mock has CPU and ambient (System Temp) IPMI sensors.
        assert SensorClass.CPU in config.curves
        assert SensorClass.AMBIENT in config.curves
        # No drive or NVMe sensors in the mock.
        assert SensorClass.DRIVE not in config.curves
        assert SensorClass.NVME not in config.curves

    def test_refuses_while_daemon_running(self, tmp_path: Path) -> None:
        """Refuses to run when the daemon PID file is locked."""
        cfg = tmp_path / "truefan.toml"
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with pytest.raises(SystemExit):
                run_init(cfg, conn=_make_sim(), sleep=noop_sleep, pid_path=pid_path)
        assert not cfg.exists()
