"""Tests for truefan.commands.recalibrate."""

from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from tests.mocks import FanSimulator, noop_sleep
from truefan.bmc import TemperatureSensorData
from truefan.commands.recalibrate import run_recalibrate
from truefan.config import Config, Curve, FanConfig, load_config, save_config
from truefan.pidfile import PidFile
from truefan.sensors import SensorClass


def _write_initial_config(path: Path) -> None:
    """Write a config with placeholder setpoints to be recalibrated."""
    config = Config(
        poll_interval_seconds=5,
        curves=MappingProxyType({
            SensorClass.CPU: Curve(
                temp_low=35, temp_high=80, duty_low=25, duty_high=100,
                fan_zones=frozenset({"cpu", "peripheral"}),
            ),
        }),
        fans=MappingProxyType({
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({50: 999, 100: 9999}),
            ),
            "SYS_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({50: 999, 100: 9999}),
            ),
        }),
    )
    save_config(path, config)


def _make_sim() -> FanSimulator:
    """Create a FanSimulator matching the config layout with temp sensors."""
    sim = FanSimulator(
        fans={
            "CPU_FAN1": {"max_rpm": 1500, "stall_below": 30},
            "SYS_FAN1": {"max_rpm": 1200, "stall_below": 20},
        },
        temps=[
            TemperatureSensorData(name="CPU Temp", temperature=35.0, upper_non_critical=80.0, upper_critical=100.0),
        ],
    )
    sim.set_fan_zone("CPU_FAN1", "cpu")
    sim.set_fan_zone("SYS_FAN1", "peripheral")
    return sim


# ---------------------------------------------------------------------------
# #### run_recalibrate
# ---------------------------------------------------------------------------

class TestRunRecalibrate:
    """Tests for run_recalibrate."""

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    def test_updates_setpoints(self, mock_ipmi, tmp_path: Path) -> None:  # noqa: ANN001
        """Recalibration replaces placeholder setpoints with real ones."""
        cfg = tmp_path / "truefan.toml"
        _write_initial_config(cfg)
        run_recalibrate(cfg, conn=_make_sim(), sleep=noop_sleep)
        config = load_config(cfg)
        # Setpoints should be different from the placeholders.
        assert config.fans["CPU_FAN1"].setpoints[100] != 9999
        assert len(config.fans["CPU_FAN1"].setpoints) > 2

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    def test_preserves_curves(self, mock_ipmi, tmp_path: Path) -> None:  # noqa: ANN001
        """Recalibration preserves user curve overrides."""
        cfg = tmp_path / "truefan.toml"
        _write_initial_config(cfg)
        run_recalibrate(cfg, conn=_make_sim(), sleep=noop_sleep)
        config = load_config(cfg)
        assert SensorClass.CPU in config.curves
        assert config.curves[SensorClass.CPU].temp_low == 35

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    def test_preserves_poll_interval(self, mock_ipmi, tmp_path: Path) -> None:  # noqa: ANN001
        """Recalibration preserves poll_interval_seconds."""
        cfg = tmp_path / "truefan.toml"
        _write_initial_config(cfg)
        run_recalibrate(cfg, conn=_make_sim(), sleep=noop_sleep)
        config = load_config(cfg)
        assert config.poll_interval_seconds == 5

    def test_refuses_missing_config(self, tmp_path: Path) -> None:
        """Exits with error when config doesn't exist."""
        with pytest.raises(SystemExit):
            run_recalibrate(tmp_path / "nonexistent.toml", conn=_make_sim(), sleep=noop_sleep)

    def test_refuses_while_daemon_running(self, tmp_path: Path) -> None:
        """Refuses to run when the daemon PID file is locked."""
        cfg = tmp_path / "truefan.toml"
        _write_initial_config(cfg)
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with pytest.raises(SystemExit):
                run_recalibrate(cfg, conn=_make_sim(), sleep=noop_sleep, pid_path=pid_path)
