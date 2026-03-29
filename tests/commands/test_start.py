"""Tests for truefan.commands.start."""

import logging
import os
from logging.handlers import SysLogHandler
from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from tests.mocks import FanSimulator
from truefan.commands.start import (
    _configure_syslog,
    _daemonize,
    _post_daemonize,
    run_start,
)
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
# #### run_start
# ---------------------------------------------------------------------------

class TestRunStart:
    """Tests for run_start."""

    def test_refuses_missing_config(self, tmp_path: Path) -> None:
        """Exits with error when config file doesn't exist."""
        with pytest.raises(SystemExit):
            run_start(tmp_path / "nonexistent.toml")

    def test_refuses_when_locked(self, tmp_path: Path) -> None:
        """Exits with error when PID file is already locked."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("poll_interval_seconds = 5\n")
        pid_path = tmp_path / "truefan.pid"
        with PidFile(pid_path):
            with pytest.raises(SystemExit):
                run_start(cfg, pid_path=pid_path)

    def test_exits_on_malformed_toml(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed TOML prints to stderr and exits before watchdog."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("[invalid\n")
        with pytest.raises(SystemExit) as exc_info:
            run_start(cfg)
        assert exc_info.value.code == 1
        assert "Malformed TOML" in capsys.readouterr().err

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    def test_exits_on_fan_mismatch(
        self, mock_ipmi: object, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Fan mismatch prints to stderr and exits before watchdog."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = FanSimulator(fans={"CPU_FAN1": {"max_rpm": 1500}})
        sim.set_fan_zone("CPU_FAN1", "cpu")
        with pytest.raises(SystemExit) as exc_info:
            run_start(cfg, conn=sim)
        assert exc_info.value.code == 1
        assert "SYS_FAN1" in capsys.readouterr().err

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    @patch("truefan.commands.start._post_daemonize")
    def test_valid_config_foreground(
        self, mock_post: MagicMock, mock_ipmi: object, tmp_path: Path,
    ) -> None:
        """Foreground mode skips daemonize and calls _post_daemonize."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = _make_matching_sim()
        run_start(cfg, conn=sim, foreground=True)
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["foreground"] is True

    @patch("truefan.commands.check_ipmi_access", return_value=None)
    @patch("truefan.commands.start._post_daemonize")
    @patch("truefan.commands.start._daemonize")
    def test_valid_config_daemon_mode(
        self, mock_daemonize: MagicMock, mock_post: MagicMock,
        mock_ipmi: object, tmp_path: Path,
    ) -> None:
        """Daemon mode calls _daemonize then _post_daemonize."""
        cfg = tmp_path / "truefan.toml"
        _write_valid_config(cfg)
        sim = _make_matching_sim()
        run_start(cfg, conn=sim, foreground=False)
        mock_daemonize.assert_called_once()
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["foreground"] is False


# ---------------------------------------------------------------------------
# #### _daemonize
# ---------------------------------------------------------------------------

class TestDaemonize:
    """Tests for _daemonize."""

    @patch("truefan.commands.start.os._exit")
    @patch("truefan.commands.start.os.read", return_value=b"")
    @patch("truefan.commands.start.os.close")
    @patch("truefan.commands.start.os.pipe", return_value=(10, 11))
    @patch("truefan.commands.start.os.fork")
    def test_first_fork_parent_waits_and_exits(
        self, mock_fork: MagicMock, mock_pipe: MagicMock,
        mock_close: MagicMock, mock_read: MagicMock,
        mock_exit: MagicMock,
    ) -> None:
        """The original process reads from pipe and exits."""
        mock_fork.return_value = 42  # Parent path.
        mock_exit.side_effect = SystemExit(0)
        with pytest.raises(SystemExit):
            _daemonize()
        mock_close.assert_any_call(11)  # Write end closed in parent.
        mock_exit.assert_called_once_with(0)

    @patch("truefan.commands.start.os.open", return_value=3)
    @patch("truefan.commands.start.os.dup2")
    @patch("truefan.commands.start.os.write")
    @patch("truefan.commands.start.os.close")
    @patch("truefan.commands.start.os._exit")
    @patch("truefan.commands.start.os.setsid")
    @patch("truefan.commands.start.os.pipe", return_value=(10, 11))
    @patch("truefan.commands.start.os.fork")
    def test_grandchild_sends_pid_and_redirects_stdio(
        self, mock_fork: MagicMock, mock_pipe: MagicMock,
        mock_setsid: MagicMock, mock_exit: MagicMock,
        mock_close: MagicMock, mock_write: MagicMock,
        mock_dup2: MagicMock, mock_open: MagicMock,
    ) -> None:
        """The grandchild writes its PID to the pipe and redirects stdio."""
        mock_fork.side_effect = [0, 0]  # Child in both forks.
        _daemonize()
        assert mock_fork.call_count == 2
        mock_setsid.assert_called_once()
        mock_exit.assert_not_called()
        # Wrote PID to pipe.
        mock_write.assert_called_once()
        # Redirected stdio to /dev/null.
        mock_open.assert_called_once_with(os.devnull, os.O_RDWR)
        assert mock_dup2.call_count == 3

    @patch("truefan.commands.start.os.write")
    @patch("truefan.commands.start.os.close")
    @patch("truefan.commands.start.os._exit")
    @patch("truefan.commands.start.os.setsid")
    @patch("truefan.commands.start.os.pipe", return_value=(10, 11))
    @patch("truefan.commands.start.os.fork")
    def test_second_fork_parent_exits(
        self, mock_fork: MagicMock, mock_pipe: MagicMock,
        mock_setsid: MagicMock, mock_exit: MagicMock,
        mock_close: MagicMock, mock_write: MagicMock,
    ) -> None:
        """The intermediate process exits after the second fork."""
        mock_fork.side_effect = [0, 99]  # Child first, parent second.
        mock_exit.side_effect = SystemExit(0)
        with pytest.raises(SystemExit):
            _daemonize()
        mock_setsid.assert_called_once()
        mock_exit.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# #### _configure_syslog
# ---------------------------------------------------------------------------

class TestConfigureSyslog:
    """Tests for _configure_syslog."""

    def test_installs_syslog_handler(self) -> None:
        """Installs a SysLogHandler with LOG_DAEMON facility."""
        root = logging.getLogger()
        handlers_before = list(root.handlers)
        try:
            _configure_syslog()
            added = [h for h in root.handlers if h not in handlers_before]
            assert any(isinstance(h, SysLogHandler) for h in added)
            syslog_handler = next(
                h for h in added if isinstance(h, SysLogHandler)
            )
            assert syslog_handler.facility == SysLogHandler.LOG_DAEMON
        finally:
            for h in root.handlers:
                if h not in handlers_before:
                    root.removeHandler(h)


# ---------------------------------------------------------------------------
# #### _daemonize print path
# ---------------------------------------------------------------------------

class TestDaemonizePrint:
    """Tests for the PID-printing path in _daemonize."""

    @patch("truefan.commands.start.os._exit")
    @patch("truefan.commands.start.os.close")
    @patch("truefan.commands.start.os.pipe", return_value=(10, 11))
    @patch("truefan.commands.start.os.fork")
    def test_parent_prints_pid(
        self, mock_fork: MagicMock, mock_pipe: MagicMock,
        mock_close: MagicMock, mock_exit: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The original process prints the daemon PID received via pipe."""
        mock_fork.return_value = 42
        # Simulate reading "1234\n" then EOF from the pipe.
        with patch("truefan.commands.start.os.read", side_effect=[b"1234\n", b""]):
            mock_exit.side_effect = SystemExit(0)
            with pytest.raises(SystemExit):
                _daemonize()
        assert "1234" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# #### _post_daemonize
# ---------------------------------------------------------------------------

class TestPostDaemonize:
    """Tests for _post_daemonize."""

    @patch("truefan.commands.start.watchdog_start")
    @patch("truefan.commands.start._configure_stderr")
    def test_foreground_configures_stderr(
        self, mock_stderr: MagicMock, mock_watchdog: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Foreground mode sets up stderr logging."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        sim = _make_matching_sim()
        _post_daemonize(cfg, sim, pid_path=None, foreground=True)
        mock_stderr.assert_called_once()
        mock_watchdog.assert_called_once()

    @patch("truefan.commands.start.watchdog_start")
    @patch("truefan.commands.start._configure_syslog")
    def test_daemon_configures_syslog(
        self, mock_syslog: MagicMock, mock_watchdog: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Daemon mode sets up syslog logging."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        sim = _make_matching_sim()
        _post_daemonize(cfg, sim, pid_path=None, foreground=False)
        mock_syslog.assert_called_once()

    @patch("truefan.commands.start.watchdog_start")
    @patch("truefan.commands.start._configure_stderr")
    def test_with_pid_file(
        self, mock_stderr: MagicMock, mock_watchdog: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Acquires PID file lock and passes close_fds to watchdog."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        pid_path = tmp_path / "truefan.pid"
        sim = _make_matching_sim()
        _post_daemonize(cfg, sim, pid_path=pid_path, foreground=True)
        mock_watchdog.assert_called_once()
        _, kwargs = mock_watchdog.call_args
        assert "close_fds" in kwargs

    @patch("truefan.commands.start.watchdog_start")
    @patch("truefan.commands.start._configure_stderr")
    def test_pid_file_locked_exits(
        self, mock_stderr: MagicMock, mock_watchdog: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Exits if PID file is already locked."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        pid_path = tmp_path / "truefan.pid"
        sim = _make_matching_sim()
        with PidFile(pid_path):
            with pytest.raises(SystemExit) as exc_info:
                _post_daemonize(cfg, sim, pid_path=pid_path, foreground=True)
            assert exc_info.value.code == 1

    @patch("truefan.commands.start.watchdog_start")
    @patch("truefan.commands.start._configure_stderr")
    def test_no_pid_path(
        self, mock_stderr: MagicMock, mock_watchdog: MagicMock,
        tmp_path: Path,
    ) -> None:
        """With pid_path=None, starts watchdog without PID file."""
        cfg = tmp_path / "truefan.toml"
        cfg.write_text("")
        sim = _make_matching_sim()
        _post_daemonize(cfg, sim, pid_path=None, foreground=True)
        mock_watchdog.assert_called_once()
        _, kwargs = mock_watchdog.call_args
        assert "close_fds" not in kwargs
