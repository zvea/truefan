"""Tests for truefan.commands.run."""

from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from tests.mocks import FanSimulator
from truefan.commands.run import run_daemon
from truefan.config import Config, Curve, FanConfig, save_config
from truefan.pidfile import PidFile
from truefan.sensors import SensorClass


def _write_valid_config(path: Path) -> None:
    """Write a config that matches _make_matching_sim."""
    config = Config(
        poll_interval_seconds=5,
        curves=MappingProxyType({
            SensorClass.CPU: Curve(
                temp_low=30, temp_high=80, duty_low=20, duty_high=100,
                fan_zones=frozenset({"cpu", "peripheral"}),
            ),
        }),
        fans=MappingProxyType({
            "CPU_FAN1": FanConfig(
                zone="cpu",
                setpoints=MappingProxyType({30: 450, 100: 1500}),
            ),
            "SYS_FAN1": FanConfig(
                zone="peripheral",
                setpoints=MappingProxyType({20: 240, 100: 1200}),
            ),
        }),
    )
    save_config(path, config)


def _make_matching_sim() -> FanSimulator:
    """Create a FanSimulator that matches _write_valid_config."""
    sim = FanSimulator(fans={
        "CPU_FAN1": {"max_rpm": 1500},
        "SYS_FAN1": {"max_rpm": 1200},
    })
    sim.set_fan_zone("CPU_FAN1", "cpu")
    sim.set_fan_zone("SYS_FAN1", "peripheral")
    return sim


# ---------------------------------------------------------------------------
# #### run_daemon
# ---------------------------------------------------------------------------

class TestRunDaemon:
    """Tests for run_daemon."""

    def test_refuses_missing_config(self, tmp_path: Path) -> None:
        """Exits with error when config file doesn't exist."""
        with pytest.raises(SystemExit):
            run_daemon(tmp_path / "nonexistent.toml")

    def test_refuses_when_locked(self, tmp_path: Path) -> None:
        """Exits with error when PID file is already locked."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("poll_interval_seconds = 5\n")
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with pytest.raises(SystemExit):
                run_daemon(cfg, pid_path=pid_path)

    def test_exits_on_malformed_toml(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Malformed TOML prints to stderr and exits before watchdog."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("[invalid\n")
        with pytest.raises(SystemExit) as exc_info:
            run_daemon(cfg)
        assert exc_info.value.code == 1
        assert "Malformed TOML" in capsys.readouterr().err

    def test_exits_on_fan_mismatch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Fan mismatch prints to stderr and exits before watchdog."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        # Simulator has only CPU_FAN1, missing SYS_FAN1.
        sim = FanSimulator(fans={"CPU_FAN1": {"max_rpm": 1500}})
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(SystemExit) as exc_info:
            run_daemon(cfg, conn=sim)
        assert exc_info.value.code == 1
        assert "SYS_FAN1" in capsys.readouterr().err

    @patch("truefan.commands.run._start")
    def test_valid_config_starts_watchdog(self, mock_start: object, tmp_path: Path) -> None:
        """Valid config + matching hardware proceeds to watchdog."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = _make_matching_sim()
        run_daemon(cfg, conn=sim)
        mock_start.assert_called_once()  # type: ignore[union-attr]
