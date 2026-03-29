"""Tests for truefan.commands.reload."""

import os
import signal
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from tests.mocks import FanSimulator
from truefan.commands.reload import run_reload
from truefan.config import Config, Curve, FanConfig, save_config
from truefan.pidfile import PidFile
from truefan.sensors import SensorClass


def _write_valid_config(path: Path) -> None:
    """Write a config that matches _make_matching_sim."""
    config = Config(
        poll_interval_seconds=5,
        curves=MappingProxyType({
            SensorClass.CPU: Curve(
                no_cooling_temp=30, max_cooling_temp=80,
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
# #### run_reload
# ---------------------------------------------------------------------------

class TestRunReload:
    """Tests for run_reload."""

    def test_no_pid_file(self, tmp_path: Path) -> None:
        """Exits with error when PID file doesn't exist."""
        cfg = tmp_path / "truefan.toml"
        with pytest.raises(SystemExit):
            run_reload(cfg, tmp_path / "nonexistent.pid")

    def test_stale_pid_file(self, tmp_path: Path) -> None:
        """Exits with error when PID file exists but is not locked."""
        cfg = tmp_path / "truefan.toml"
        pid_path = tmp_path / "truefan.pid"
        pid_path.write_text("99999\n")
        with pytest.raises(SystemExit):
            run_reload(cfg, pid_path)

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    def test_sends_sighup(self, mock_ipmi, tmp_path: Path) -> None:  # noqa: ANN001
        """Sends SIGHUP to the PID in the file after validating config."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = _make_matching_sim()
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with patch("truefan.commands.reload.os.kill") as mock_kill:
                run_reload(cfg, pid_path, conn=sim)
                mock_kill.assert_called_once_with(os.getpid(), signal.SIGHUP)

    def test_refuses_bad_config(self, tmp_path: Path) -> None:
        """Exits with error when config is invalid, without sending SIGHUP."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("[invalid\n")
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with patch("truefan.commands.reload.os.kill") as mock_kill:
                with pytest.raises(SystemExit):
                    run_reload(cfg, pid_path)
                mock_kill.assert_not_called()

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    def test_process_not_found(self, mock_ipmi, tmp_path: Path) -> None:  # noqa: ANN001
        """Exits with error when the PID doesn't correspond to a process."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = _make_matching_sim()
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with patch("truefan.commands.reload.os.kill", side_effect=ProcessLookupError):
                with pytest.raises(SystemExit):
                    run_reload(cfg, pid_path, conn=sim)

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    def test_permission_denied(self, mock_ipmi, tmp_path: Path) -> None:  # noqa: ANN001
        """Exits with error when we can't signal the process."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = _make_matching_sim()
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with patch("truefan.commands.reload.os.kill", side_effect=PermissionError):
                with pytest.raises(SystemExit):
                    run_reload(cfg, pid_path, conn=sim)
